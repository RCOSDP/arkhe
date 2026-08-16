"""認可の中核。**shoulder はリクエストで受け取らずクライアントから引く。**

これ 1 点で、越境（R1）と 800 機関の振り分けが同時に片づく。arklet は
`{naan, shoulder}` を本文で受けて NAAN 単位でしか認可していなかったため、
**設定ミスでも詐称でも他機関の名前空間に採番できた**（実測で 200）。

受け入れ条件: R1・M3・M4・M5・R2
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework.exceptions import (
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)

from .models import Ark, AuditEvent, Client, Shoulder, ShoulderStatus


def client_of(request) -> Client:
    """認証済みクライアントを取り出す。"""
    app = getattr(getattr(request, "auth", None), "application", None)
    if app is None:
        raise PermissionDenied("no client bound to this token")
    return app


def shoulder_for(client: Client, requested: str | None) -> Shoulder:
    """このクライアントが採番に使える shoulder を決める。

    **リクエストの `shoulder` は任意。** 省略時は manager の `default_shoulder`。
    指定された場合は**そのクライアントの到達範囲に含まれるかを検証する**だけで、
    範囲を広げる手段にはしない。
    """
    if client.authority == Client.Authority.NAAN:
        # break-glass。NAAN 配下ならどれでも使えるが、**明示が必須**
        # （既定を持たないので、誤って他機関の shoulder に打つ事故を防ぐ）。
        if not requested:
            raise ValidationError(
                {"shoulder": "authority=naan のクライアントは shoulder を明示すること"}
            )
        found = Shoulder.objects.filter(naan_id=client.naan_id, shoulder=requested).first()
        if found is None:
            raise ValidationError({"shoulder": f"shoulder {requested} は存在しない"})
        return found

    manager = client.manager
    if manager is None or not manager.active:
        raise PermissionDenied("client has no active manager")

    # **クライアントが shoulder に固定されている場合はそれだけ。**
    # 同じ shoulder を複数のクライアントが使うのは正常（鍵は共有しない）。
    if client.shoulder_id is not None:
        if requested and requested != client.shoulder.shoulder:
            raise PermissionDenied(f"shoulder {requested} はこのクライアントの範囲外")
        return client.shoulder

    if not requested:
        if manager.default_shoulder_id is None:
            raise ValidationError({"shoulder": "この機関に default_shoulder が設定されていない"})
        return manager.default_shoulder

    found = Shoulder.objects.filter(
        naan_id=client.naan_id, shoulder=requested, manager_id=manager.pk
    ).first()
    if found is None:
        # **他機関の shoulder を指定しても、存在の有無を漏らさず一律に拒む。**
        raise PermissionDenied(f"shoulder {requested} はこのクライアントの範囲外")
    return found


class ShoulderDelegated(PermissionDenied):
    """**採番はここではなく外部 minter で行う。** 行き先を添えて返す。

    プロキシしない——プロキシすると (1) 名前空間を誰が消費したか二重管理になり、
    (2) 応答が失われたとき**誰も指していない ARK** が両側に残りうる。ARK は
    NR を宣言する識別子なので、それは取り返しがつかない。
    """

    def __init__(self, shoulder: Shoulder):
        self.minter = shoulder.minter
        super().__init__(
            {
                "detail": f"shoulder {shoulder.shoulder} の採番は委譲されている",
                "minter": shoulder.minter,
                "note": shoulder.note,
            }
        )


def assert_shoulder_mintable(shoulder: Shoulder) -> None:
    """**リザーブ枠・委譲・引退した shoulder では採番しない。**"""
    if shoulder.status == ShoulderStatus.ACTIVE:
        return
    if shoulder.status == ShoulderStatus.DELEGATED:
        raise ShoulderDelegated(shoulder)
    raise PermissionDenied(
        {
            "detail": f"shoulder {shoulder.shoulder} は status={shoulder.status} で採番できない",
            "note": shoulder.note,
        }
    )


def assert_may_touch(client: Client, ark: Ark) -> None:
    """既存 ARK に触れてよいか。

    M3: **arklet の `update` は shoulder を参照すらしていなかった**ため、同一 NAAN
    内の任意の ARK の解決先を書き換えられた（実測で 302 先が実際に変わった）。
    採番より重い——**永続識別子の乗っ取り**になる。
    """
    if ark.naan_id != client.naan_id:
        raise PermissionDenied("ARK が別の NAAN に属している")
    if client.authority == Client.Authority.NAAN:
        return
    if client.manager_id is None or ark.shoulder.manager_id != client.manager_id:
        raise PermissionDenied("ARK がこのクライアントの範囲外")


def visible_arks(client: Client, keys: list[str]):
    """M4: 読み取りも到達範囲に絞る。"""
    qs = Ark.objects.filter(pk__in=keys, naan_id=client.naan_id).select_related("shoulder")
    if client.authority != Client.Authority.NAAN:
        qs = qs.filter(shoulder__manager_id=client.manager_id)
    return qs


def fetch_for_update(client: Client, keys: list[str]) -> dict[str, Ark]:
    """M5: **ARK をキーにした辞書で引き当てる。**

    arklet は順序不定の queryset を入力と `zip` しており、**別の ARK に他レコードの
    値を書き込みうる**データ破壊バグがあった。件数が一致しない場合も黙って
    切り詰められていた。

    **1 件でも欠けるか範囲外なら全体を失敗させる**（部分適用しない）。
    """
    found = {a.pk: a for a in visible_arks(client, keys)}
    missing = [k for k in keys if k not in found]
    if missing:
        raise NotFound({"missing": missing[:20], "count": len(missing)})
    return found


def assert_within_quota(client: Client, count: int = 1) -> None:
    """R3: 機関単位の 1 日あたり採番上限。**一機関の暴走を止める。**

    `Manager.quota_per_day` が null なら無制限。break-glass（authority=naan）は
    manager を持たないので対象外——障害対応で止まっては困る。
    """
    manager = client.manager
    if manager is None or manager.quota_per_day is None:
        return
    since = timezone.now() - timedelta(days=1)
    used = Ark.objects.filter(shoulder__manager_id=manager.pk, created_at__gte=since).count()
    if used + count > manager.quota_per_day:
        raise Throttled(
            detail={
                "quota_per_day": manager.quota_per_day,
                "used_last_24h": used,
                "requested": count,
            }
        )


def audit(client: Client, action: str, target: str = "", **detail) -> None:
    """R2: **`authority=naan` の操作は全件記録する。**"""
    if client.authority != Client.Authority.NAAN:
        return
    AuditEvent.objects.create(
        client_id=client.client_id,
        authority=client.authority,
        action=action,
        target=target,
        detail=detail,
    )
