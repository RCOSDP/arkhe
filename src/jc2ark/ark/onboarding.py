"""機関オンボーディング。**1 系統で完結させる**（`design_ark_multitenant_authz.md` §2.4）。

中間状態（shoulder はあるが機関が無い／機関はあるが採番できない）を作らないよう、
判定 → Manager → shoulder → default → Client → 資格情報 を 1 トランザクションで行う。

**資格情報は shoulder ではなく Manager に紐づける**——部局別・分野別に shoulder を
足しても鍵の再発行が要らない。**`client_id` に shoulder を流用しない**——shoulder は
公開名前空間に現れるので、片方から他方が推測できてはいけない。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from django.db import IntegrityError, transaction

from jc2ark.arkspec.shoulder import DEFAULT_SHOULDER_LENGTH, generate_shoulder

from .models import (
    AuditEvent,
    Client,
    CommitmentLevel,
    Manager,
    Naan,
    Shoulder,
    ShoulderStatus,
)

SHOULDER_ALLOCATION_RETRIES = 50


@dataclass
class Onboarded:
    manager: Manager
    shoulder: Shoulder
    client: Client
    #: **発行時に 1 回だけ**返す。以降は再発行のみ（保存も再表示もしない）。
    client_secret: str


def allocate_shoulder(
    naan: Naan, manager: Manager, length: int = DEFAULT_SHOULDER_LENGTH
) -> Shoulder:
    """不透明な shoulder を 1 つ割り当てる。**連番にしない**（加入順が漏れる）。"""
    for _ in range(SHOULDER_ALLOCATION_RETRIES):
        try:
            with transaction.atomic():
                return Shoulder.objects.create(
                    shoulder=generate_shoulder(length), naan=naan, manager=manager
                )
        except IntegrityError:
            continue
    raise RuntimeError("shoulder の空きが見つからない（長さを増やすこと）")


@transaction.atomic
def onboard(
    *,
    naan: Naan,
    name: str,
    label: str,
    scopes: str = "ark:mint",
    commitment_level: str = CommitmentLevel.PERMANENT_DYNAMIC,
    quota_per_day: int | None = None,
) -> Onboarded:
    manager = Manager.objects.create(
        naan=naan, name=name, commitment_level=commitment_level, quota_per_day=quota_per_day
    )
    shoulder = allocate_shoulder(naan, manager)
    manager.default_shoulder = shoulder
    manager.save(update_fields=["default_shoulder"])

    secret = secrets.token_urlsafe(32)
    client = Client(
        name=f"{name} / {label}",
        label=label,
        manager=manager,
        naan=naan,
        allowed_scopes=scopes,
        client_type=Client.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Client.GRANT_CLIENT_CREDENTIALS,
        client_secret=secret,
    )
    client.save()
    return Onboarded(manager=manager, shoulder=shoulder, client=client, client_secret=secret)


@transaction.atomic
def succeed(*, predecessor: Manager, successor: Manager, retire_shoulders: bool = False) -> dict:
    """**統廃合の承継。** 旧機関の名前空間を承継先に移す。

    `ark_succession.md` §2.1。**既存 ARK は 1 本も変わらない**——`Ark.shoulder` は
    そのままで、その shoulder の管理主体だけが変わる。解決先も変わらない。

    **shoulder は消さない**（名前空間の再利用は `NR` 違反）。`retire_shoulders=True`
    なら新規採番だけ止める。

    旧機関のクライアントは全部失効させる——**承継後は承継先の資格情報で採番する**。
    """
    if predecessor.pk == successor.pk:
        raise ValueError("承継元と承継先が同じ")
    if predecessor.naan_id != successor.naan_id:
        # NAAN をまたぐ承継は、レジストリ側（who / where）の変更を伴うので
        # 自動化しない（ARK Alliance への人手申請が要る。§2.2）。
        raise ValueError("NAAN をまたぐ承継はここでは扱わない（レジストリの who 変更が要る）")

    moved = list(predecessor.shoulders.all())
    for sh in moved:
        sh.manager = successor
        if retire_shoulders:
            sh.status = ShoulderStatus.RETIRED
            sh.note = (sh.note + " / ").lstrip(" /") + f"{predecessor.name} から承継"
        sh.save()

    revoked = list(predecessor.clients.filter(active=True))
    for c in revoked:
        c.active = False
        c.save(update_fields=["active"])

    if successor.default_shoulder_id is None and moved:
        successor.default_shoulder = moved[0]
        successor.save(update_fields=["default_shoulder"])

    predecessor.active = False
    predecessor.succeeded_by = successor
    predecessor.save(update_fields=["active", "succeeded_by"])

    AuditEvent.objects.create(
        client_id="",
        authority="operator",
        action="succeed",
        target=f"{predecessor.name} -> {successor.name}",
        detail={
            "shoulders": [s.shoulder for s in moved],
            "revoked_clients": [c.client_id for c in revoked],
            "retired": retire_shoulders,
        },
    )
    return {"shoulders": [s.shoulder for s in moved], "revoked": len(revoked)}


@transaction.atomic
def reserve_shoulder(
    *,
    naan: Naan,
    note: str = "",
    manager: Manager | None = None,
    minter: str = "",
    length: int = DEFAULT_SHOULDER_LENGTH,
) -> Shoulder:
    """**リザーブ枠**を切る。名前空間を押さえるだけで採番はできない。

    用途:
      - 将来の機関のために先に確保する
      - **外部 minter に渡す予定の枠**を先に切っておく（`minter` を渡すと
        `delegated` になり、mint 要求はそこへ案内される）
      - 乱数割当で当たってほしくない枠を除外する
    """
    status = ShoulderStatus.DELEGATED if minter else ShoulderStatus.RESERVED
    for _ in range(SHOULDER_ALLOCATION_RETRIES):
        try:
            with transaction.atomic():
                return Shoulder.objects.create(
                    shoulder=generate_shoulder(length),
                    naan=naan,
                    manager=manager,
                    minter=minter,
                    status=status,
                    note=note,
                )
        except IntegrityError:
            continue
    raise RuntimeError("shoulder の空きが見つからない（長さを増やすこと）")


@transaction.atomic
def issue_client(
    *, manager: Manager, label: str, scopes: str = "ark:mint", shoulder: Shoulder | None = None
) -> tuple[Client, str]:
    """既存の機関に**追加の**クライアントを発行する。

    **同一 shoulder に複数のクライアントが並ぶのは正常。** 鍵を共有させないための
    仕組みで、`(manager, label)` が有効なものの中で一意になる。
    """
    if not label.strip():
        raise ValueError("label（用途）は必須")
    if shoulder is not None and shoulder.manager_id != manager.pk:
        raise ValueError("shoulder がこの機関のものでない")
    secret = secrets.token_urlsafe(32)
    client = Client(
        name=f"{manager.name} / {label}",
        label=label,
        manager=manager,
        naan=manager.naan,
        shoulder=shoulder,
        allowed_scopes=scopes,
        client_type=Client.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Client.GRANT_CLIENT_CREDENTIALS,
        client_secret=secret,
    )
    client.save()
    return client, secret


@transaction.atomic
def issue_break_glass(
    *, naan: Naan, label: str, hours: int = 72, scopes: str = "ark:mint ark:update"
) -> tuple[Client, str]:
    """§10.3: **平時は発行しない。** `label`（発行理由）と `expires_at` が必須。"""
    from django.utils import timezone

    if not label.strip():
        raise ValueError("break-glass は発行理由（label）が必須")
    secret = secrets.token_urlsafe(32)
    client = Client(
        name=f"break-glass / {label}",
        label=label,
        manager=None,
        naan=naan,
        authority=Client.Authority.NAAN,
        allowed_scopes=scopes,
        expires_at=timezone.now() + timezone.timedelta(hours=hours),
        client_type=Client.CLIENT_CONFIDENTIAL,
        authorization_grant_type=Client.GRANT_CLIENT_CREDENTIALS,
        client_secret=secret,
    )
    client.save()
    return client, secret
