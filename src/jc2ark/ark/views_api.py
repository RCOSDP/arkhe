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

from jc2ark.arkspec.naming import (
    ArkParseError,
    ark_key,
    normalize_structural,
    parse_ark,
    strip_hyphens,
)

from . import authz
from .models import AlreadyRegistered, Ark, MintReceipt
from .permissions import ClientStillValid
from .serializers import (
    ArkOutSerializer,
    BulkMintSerializer,
    BulkQuerySerializer,
    BulkUpdateSerializer,
    MintSerializer,
    RegisterSerializer,
    TombstoneSerializer,
    UpdateSerializer,
)

#: 1 リクエストの上限。**万オーダーはこれで分割して投げる**（F4）。
#: 冪等鍵（`request_id`）があるので、切れた塊はそのまま再送してよい。
BULK_LIMIT = 100


def _replay(client, request_id: str):
    """F4: 同じ `request_id` の採番が既にあれば、その ARK を返す。"""
    if not request_id:
        return None
    receipt = (
        MintReceipt.objects.select_related("ark")
        .filter(client_id=client.client_id, request_id=request_id)
        .first()
    )
    return receipt.ark if receipt else None


def _replayed_map(client, rows) -> dict:
    """F4: 一括採番のうち、既に採番済みの `request_id` → `Ark`。"""
    keys = [r.get("request_id") or "" for r in rows]
    wanted = {k for k in keys if k}
    if not wanted:
        return {}
    return {
        r.request_id: r.ark
        for r in MintReceipt.objects.select_related("ark").filter(
            client_id=client.client_id, request_id__in=wanted
        )
    }


def _keep_receipt(client, request_id: str, ark) -> None:
    """F4: 控えを残す。**採番と同じトランザクションで**——別にすると、控えを
    書く前に落ちたときに「採番したが再送で二重に採番される」が起きる。"""
    if request_id:
        MintReceipt.objects.create(client_id=client.client_id, request_id=request_id, ark=ark)


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
    # **解決側と同じ正規化を通す。** ここだけ素通しにすると、`…/x/` や `…/x..v`
    # を送ったクライアントが「同じ ARK」を更新できず 404 になる。
    return ark_key(p.naan, strip_hyphens(normalize_structural(p.name)))


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
        request_id = s.validated_data.get("request_id") or ""
        # F4: **再送なら採番しない。** 応答が失われただけのときに番号を増やさない。
        if (existing := _replay(client, request_id)) is not None:
            return Response(ArkOutSerializer(existing).data, status=200)
        shoulder = authz.shoulder_for(client, s.validated_data.get("shoulder") or None)
        authz.assert_shoulder_mintable(shoulder)
        authz.assert_within_quota(client)
        with transaction.atomic():
            ark, _ = Ark.objects.mint(
                shoulder=shoulder, created_by=client.client_id, **s.fields_for_mint()
            )
            _keep_receipt(client, request_id, ark)
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
        # F4: **既に採番済みの行は飛ばす。** 切れた塊をそのまま再送できるようにする。
        replayed = _replayed_map(client, rows)
        fresh = [r for r in rows if (r.get("request_id") or "") not in replayed]
        # 到達範囲の検証を**先に全件済ませる**（1 件でも範囲外なら何も作らない）。
        shoulders = [authz.shoulder_for(client, r.get("shoulder") or None) for r in fresh]
        for sh in shoulders:
            authz.assert_shoulder_mintable(sh)
        authz.assert_within_quota(client, len(fresh))
        minted = {}
        with transaction.atomic():
            for sh, row in zip(shoulders, fresh, strict=True):
                request_id = row.get("request_id") or ""
                fields = {k: v for k, v in row.items() if k not in ("shoulder", "request_id")}
                ark, _ = Ark.objects.mint(shoulder=sh, created_by=client.client_id, **fields)
                _keep_receipt(client, request_id, ark)
                minted[id(row)] = ark
        # **入力の順序で返す。** 再送ぶんと新規ぶんが混ざるので、呼び出し側が
        # 突き合わせられるように並びを保つ。
        made = [replayed.get(r.get("request_id") or "") or minted[id(r)] for r in rows]
        authz.audit(client, "bulk_mint", detail_count=len(minted))
        return Response(
            {
                "minted": ArkOutSerializer(made, many=True).data,
                "created": len(minted),
                "replayed": len(made) - len(minted),
            },
            status=201 if minted else 200,
        )


class RegisterView(_Base):
    """B4: **既存 ARK に修飾子を付けた行を登録する。**

    既定では suffix passthrough が任意の深さを賄う（祖先の URL に修飾子を足す）。
    この口は**その既定を 1 点だけ上書きする**ためにある——「このサブツリーだけ別
    ストレージ」「この変換版だけ別の所在」。

    **`ark:mint` を要求する。** 採番ではないが、**新しく解決可能な識別子が増える**
    ので、更新権限しか持たないクライアントに渡してはいけない（発行と更新を分けた
    趣旨がここで効く）。
    """

    required_scopes = ["ark:mint"]

    def post(self, request):
        from rest_framework.exceptions import ValidationError

        client = authz.client_of(request)
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        base = authz.fetch_for_update(client, [_key(s.validated_data["ark"])]).popitem()[1]
        authz.assert_may_touch(client, base)
        authz.assert_shoulder_mintable(base.shoulder)
        authz.assert_within_quota(client)
        try:
            ark = Ark.objects.register_qualified(
                base=base,
                qualifier=s.validated_data["qualifier"],
                created_by=client.client_id,
                **s.fields_for_register(),
            )
        except AlreadyRegistered as exc:
            raise ValidationError({"qualifier": str(exc)}) from exc
        except ValueError as exc:
            raise ValidationError({"qualifier": str(exc)}) from exc
        authz.audit(client, "register_qualified", ark.pk)
        return Response(ArkOutSerializer(ark).data, status=201)


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


class TombstoneView(_Base):
    """**対象が失われたと宣言する。** ARK は削除しない。

    `NR`（No Re-assignment）を宣言している以上、識別子は消せない。消せるのは
    対象への到達性だけで、**識別子とメタデータは残る**。

    **scope を `ark:update` と分けてある。** 墓碑化は「どこにあるか」ではなく
    「もう無い」という宣言で、意味も影響も違う。取り消しにくく、公開されると
    信頼に関わるので、投入バッチのような日常の書き手には渡さない。
    """

    required_scopes = ["ark:tombstone"]

    def put(self, request):
        client = authz.client_of(request)
        s = TombstoneSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        ark = authz.fetch_for_update(client, [_key(s.validated_data["ark"])]).popitem()[1]
        authz.assert_may_touch(client, ark)
        # url が空なら、リゾルバが記述そのものを返す（D6 と同じ経路）。
        ark.url = s.validated_data.get("url", "")
        if s.validated_data.get("commitment"):
            ark.commitment = s.validated_data["commitment"]
        ark.updated_by = client.client_id
        ark.save()
        authz.audit(client, "tombstone", ark.pk)
        return Response(ArkOutSerializer(ark).data)


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
