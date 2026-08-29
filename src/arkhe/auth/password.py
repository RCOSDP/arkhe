"""管理画面へのローカルログイン。**外部 IdP を持たない構成のための入口。**

`oidc` や `proxy` が使えるならそちらがよい——身元の管理が 1 か所に集まり、
退職や異動が組織側の操作だけで効くから。ここは**それが無い組織でも単体で建てられる**
ようにするためのもの。

守っていること:

  * 平文は保存しない（Argon2）
  * **利用者の存在を漏らさない。** 未登録でも誤ったパスワードでも同じ応答・同じ所要時間
  * **総当たりを止める。** 連続失敗で一時的に施錠する。ログイン画面を出す以上、
    これが無いと辞書攻撃に素で晒される
  * 人の主体にしか設定できない（機械はパスワードを覚えない）
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from arkhe.auth.apikey import _expired, _to_principal
from arkhe.auth.errors import AuthError
from arkhe.auth.principal import Principal
from arkhe.db.models import Client, Credential, CredentialKind, Subject

_ph = PasswordHasher()

#: 連続失敗の上限と施錠の長さ。**利用者を締め出しすぎない範囲**で、
#: 総当たりが現実的でなくなればよい。
MAX_ATTEMPTS = 5
LOCK_MINUTES = 15
MIN_LENGTH = 12

#: 存在しない利用者でも同じだけ時間を使うためのダミー。**応答時間で存在を漏らさない。**
_DUMMY_HASH = _ph.hash("arkhe-timing-equalizer")


class WeakPassword(ValueError):
    pass


def check_strength(password: str) -> None:
    """**長さだけ見る。** 記号や大文字を強いる規則は、覚えられない文字列を
    生んで結局どこかに書き留められるので採らない（NIST SP 800-63B の方針）。"""
    if len(password) < MIN_LENGTH:
        raise WeakPassword(f"パスワードは {MIN_LENGTH} 文字以上にしてください")


def hash_password(password: str) -> str:
    check_strength(password)
    return _ph.hash(password)


def _locked(cred: Credential) -> bool:
    if cred.locked_until is None:
        return False
    until = cred.locked_until
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    return until > datetime.now(UTC)


def authenticate(session: Session, subject: str, password: str) -> Principal:
    """ID とパスワードで主体を引く。**失敗の理由は返さない。**"""
    cred = None
    if subject:
        cred = session.scalar(
            select(Credential)
            .join(Client, Credential.client_pk == Client.id)
            .where(
                Client.client_id == subject,
                Credential.kind == CredentialKind.PASSWORD,
                Credential.active.is_(True),
            )
            .options(selectinload(Credential.client).selectinload(Client.manager))
        )

    if cred is None:
        # **存在しない利用者でも同じだけ時間を使う。** ここを省くと、応答の速さで
        # 「その ID は無い」と分かってしまう。
        try:
            _ph.verify(_DUMMY_HASH, password or "x")
        except Exception:  # noqa: BLE001 - 常に失敗する。時間を使うのが目的
            pass
        raise AuthError("ID かパスワードが違います")

    if _locked(cred):
        raise AuthError("試行が続いたため一時的に受け付けません。しばらく待ってください")

    try:
        _ph.verify(cred.hashed, password)
    except (VerifyMismatchError, Exception):  # noqa: B014
        cred.failed_attempts += 1
        if cred.failed_attempts >= MAX_ATTEMPTS:
            cred.locked_until = datetime.now(UTC) + timedelta(minutes=LOCK_MINUTES)
            cred.failed_attempts = 0
        raise AuthError("ID かパスワードが違います") from None

    client = cred.client
    if client is None or not client.active or _expired(client.expires_at):
        raise AuthError("ID かパスワードが違います")
    if client.subject_type != Subject.PERSON:
        # 機械にパスワードは無いはずだが、経路として塞いでおく。
        raise AuthError("ID かパスワードが違います")
    if _expired(cred.expires_at):
        raise AuthError("パスワードの有効期限が切れています")

    cred.failed_attempts = 0
    cred.locked_until = None
    cred.last_used_at = datetime.now(UTC)
    return _to_principal(client, mechanism="password")
