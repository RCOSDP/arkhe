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

from .models import Client, CommitmentLevel, Manager, Naan, Shoulder

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
