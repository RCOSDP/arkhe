"""採番・更新の API。**OAuth2 で保護し、shoulder はクライアントから引く。**

すべてのビューが `TokenHasScope` と `ClientStillValid` を持つ:
- 前者は **操作**（`ark:mint` / `ark:update` / `ark:read`）を絞る
- 後者は **即時失効**を効かせる（S1-4）

到達範囲（どの機関の shoulder か）は `authz` が見る。**トークン要求では広げられない。**
"""

from __future__ import annotations

from django.db import transaction
from oauth2_provider.contrib.rest_framework import TokenHasScope
from rest_framework.response import Response
from rest_framework.views import APIView

from jc2ark.arkspec.naming import ArkParseError, ark_key, parse_ark, strip_hyphens

from . import authz
from .models import Ark
from .permissions import ClientStillValid
from .serializers import (
    ArkOutSerializer,
    BulkMintSerializer,
    BulkQuerySerializer,
    BulkUpdateSerializer,
    MintSerializer,
    UpdateSerializer,
)

#: 1 リクエストの上限。F4（outbox パターン）に踏み込むのは万オーダーが要るとき。
BULK_LIMIT = 100


class _Base(APIView):
    permission_classes = [TokenHasScope, ClientStillValid]

    def handle_exception(self, exc):
        """委譲された shoulder への mint は **307 で行き先を案内する。**

        **プロキシはしない。** 我々が外部 minter を代理で呼ぶと、応答が失われた
        ときに「向こうでは採番されたがこちらは知らない ARK」が生まれる。ARK は
        NR を宣言する識別子で取り消せないので、二重管理を作らない。
        """
        if isinstance(exc, authz.ShoulderDelegated) and exc.minter:
            r = Response(exc.detail, status=307)
            r["Location"] = exc.minter
            return r
        return super().handle_exception(exc)


def _key(raw: str) -> str:
    """`ark:/99999/xyz` でも `99999/xyz` でも受ける。"""
    try:
        p = parse_ark(raw if raw.lower().startswith(("ark:", "http")) else f"ark:/{raw}")
    except ArkParseError as exc:
        from rest_framework.exceptions import ValidationError

        raise ValidationError({"ark": str(exc)}) from exc
    return ark_key(p.naan, strip_hyphens(p.name))


def _apply(ark: Ark, data: dict, client) -> Ark:
    for field, value in data.items():
        if field != "ark":
            setattr(ark, field, value)
    ark.updated_by = client.client_id
    return ark


class MintView(_Base):
    """ARK を 1 本採番する。"""

    required_scopes = ["ark:mint"]

    def post(self, request):
        client = authz.client_of(request)
        s = MintSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        shoulder = authz.shoulder_for(client, s.validated_data.get("shoulder") or None)
        authz.assert_shoulder_mintable(shoulder)
        authz.assert_within_quota(client)
        ark, _ = Ark.objects.mint(
            shoulder=shoulder, created_by=client.client_id, **s.fields_for_mint()
        )
        authz.audit(client, "mint", ark.pk)
        return Response(ArkOutSerializer(ark).data, status=201)


class BulkMintView(_Base):
    required_scopes = ["ark:mint"]

    def post(self, request):
        client = authz.client_of(request)
        s = BulkMintSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        rows = s.validated_data["data"]
        if len(rows) > BULK_LIMIT:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"data": f"1 リクエストは {BULK_LIMIT} 件まで"})
        # 到達範囲の検証を**先に全件済ませる**（1 件でも範囲外なら何も作らない）。
        shoulders = [authz.shoulder_for(client, r.get("shoulder") or None) for r in rows]
        for sh in shoulders:
            authz.assert_shoulder_mintable(sh)
        authz.assert_within_quota(client, len(rows))
        made = []
        with transaction.atomic():
            for sh, row in zip(shoulders, rows, strict=True):
                fields = {k: v for k, v in row.items() if k != "shoulder"}
                ark, _ = Ark.objects.mint(shoulder=sh, created_by=client.client_id, **fields)
                made.append(ark)
        authz.audit(client, "bulk_mint", detail_count=len(made))
        return Response({"minted": ArkOutSerializer(made, many=True).data}, status=201)


class UpdateView(_Base):
    """既存 ARK を更新する。**対象の shoulder の manager を照合する**（M3）。"""

    required_scopes = ["ark:update"]

    def put(self, request):
        client = authz.client_of(request)
        s = UpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        ark = authz.fetch_for_update(client, [_key(s.validated_data["ark"])]).popitem()[1]
        authz.assert_may_touch(client, ark)
        _apply(ark, s.validated_data, client).save()
        authz.audit(client, "update", ark.pk)
        return Response(ArkOutSerializer(ark).data)


class BulkUpdateView(_Base):
    """M5: **辞書で引き当て、部分適用しない。**"""

    required_scopes = ["ark:update"]

    def put(self, request):
        client = authz.client_of(request)
        s = BulkUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        rows = s.validated_data["data"]
        if len(rows) > BULK_LIMIT:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"data": f"1 リクエストは {BULK_LIMIT} 件まで"})
        keys = [_key(r["ark"]) for r in rows]
        found = authz.fetch_for_update(client, keys)  # 欠けが 1 件でもあれば 404
        with transaction.atomic():
            for key, row in zip(keys, rows, strict=True):
                ark = found[key]
                authz.assert_may_touch(client, ark)
                _apply(ark, row, client).save()
        authz.audit(client, "bulk_update", detail_count=len(rows))
        return Response({"updated": len(rows)})


class BulkQueryView(_Base):
    """M4: **arklet は認可を一切していなかった。**"""

    required_scopes = ["ark:read"]

    def post(self, request):
        client = authz.client_of(request)
        s = BulkQuerySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        keys = [_key(a) for a in s.validated_data["data"][:BULK_LIMIT]]
        arks = authz.visible_arks(client, keys)
        return Response({"data": ArkOutSerializer(arks, many=True).data})
