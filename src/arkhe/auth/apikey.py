"""API キー認証（arklet 方式）。**arkhe 単体で完結する**。

arklet は `Key` を NAAN に紐づけ、`Authorization: Bearer <key>` を全件ハッシュ照合
していた。ここでは 2 点変えている。

1. **前置き（prefix）で 1 行に絞ってから照合する。** 全件ループは鍵が増えると
   線形に遅くなり、しかも Argon2 の照合は意図的に重い。前置きは平文の先頭 8 文字で、
   **秘密ではない**（これだけでは鍵にならない）。
2. **紐づけ先は NAAN ではなく Client。** arklet は NAAN 単位でしか認可できず、
   同一 NAAN 内で他組織の名前空間に採番できた（M3）。到達範囲は Client が持つ。
"""

from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from arkhe.auth.errors import AuthError
from arkhe.auth.principal import Principal
from arkhe.db.models import Client, Credential, CredentialKind, Subject

_ph = PasswordHasher()

#: 平文キーの形。`arkhe_` の接頭で「これは arkhe の鍵だ」と分かるようにする
#: （漏洩検知の grep 対象にできる。GitHub の secret scanning もこの形を好む）。
KEY_PREFIX = "arkhe_"
PREFIX_LEN = 8


def generate_key() -> tuple[str, str, str]:
    """新しい API キーを作る。戻り値は (平文, 前置き, ハッシュ)。

    **平文はここでしか手に入らない。** 呼び出し側が利用者に一度だけ見せ、保存しない。
    """
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:PREFIX_LEN], _ph.hash(raw)


def _expired(at: datetime | None) -> bool:
    if at is None:
        return False
    if at.tzinfo is None:  # SQLite は tz を落とす
        at = at.replace(tzinfo=UTC)
    return at <= datetime.now(UTC)


def authenticate(session: Session, raw: str) -> Principal:
    """平文キーから主体を引く。失敗は理由を区別せず一律 401。

    **「鍵が無い」と「鍵が期限切れ」を呼び出し側に区別させない。** 区別できると、
    有効な鍵の存在を総当たりで探れてしまう。
    """
    if not raw:
        raise AuthError("no api key")

    rows = session.scalars(
        select(Credential)
        .where(
            Credential.prefix == raw[:PREFIX_LEN],
            Credential.kind == CredentialKind.API_KEY.value,
            Credential.active.is_(True),
        )
        .options(selectinload(Credential.client).selectinload(Client.manager))
    ).all()

    for cred in rows:
        try:
            _ph.verify(cred.hashed, raw)
        except (VerifyMismatchError, Exception):  # noqa: B014 - 壊れたハッシュも不一致扱い
            continue
        if _expired(cred.expires_at):
            continue
        client = cred.client
        if client is None or not client.active or _expired(client.expires_at):
            continue
        # **人の主体は資格情報で名乗れない。** 身元は外部が保証するものなので、
        # arkhe に鍵を持たせない（持たせると、外部で失効させても入れてしまう）。
        if client.subject_type != Subject.MACHINE:
            continue
        # **組織に許されていない機構では通さない。** 発行を止めるだけだと、
        # 制限を掛ける前に出した鍵が生き残り、制限したつもりで通り続ける。
        if not _mechanism_allowed(session, client, "apikey"):
            continue
        cred.last_used_at = datetime.now(UTC)
        return _to_principal(client, mechanism="apikey")

    # 一致が無いときも、照合と同程度の時間を使う（存在の有無を時間差で漏らさない）。
    hmac.compare_digest(raw, raw)
    raise AuthError("invalid api key")


def _mechanism_allowed(session: Session, client: Client, mechanism: str) -> bool:
    """その機構での入場が許されているか。

    **原則は NAAN、例外は組織。** 決まりを重ねた結果で判断する
    （`admin_ops.policy_for`）——組織側だけを見ると、名前空間の既定が効かない。
    """
    from arkhe.db.models import Naan
    from arkhe.domain.admin_ops import policy_for

    allowed = policy_for(session.get(Naan, client.naan), client.manager).allowed_auth
    return not allowed or mechanism in allowed.split()


def _to_principal(client: Client, *, mechanism: str) -> Principal:
    return Principal(
        client_id=client.client_id,
        naan=client.naan,
        authority=client.authority,
        manager_id=client.manager_id,
        shoulder_id=client.shoulder_id,
        scopes=frozenset(client.allowed_scopes.split()),
        mechanism=mechanism,
    )
