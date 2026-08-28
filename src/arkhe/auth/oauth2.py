"""OAuth2 の自前発行。**client_credentials グラント 1 本だけ。**

なぜ 1 本か。ARK の採番を叩くのは機関のリポジトリシステムで、夜間バッチのことも
ある。そこに利用者もブラウザもいない。認可コードフローが解くのは「**利用者が
第三者アプリに自分の代理を許可する**」問題で、この構図が発生しない。

実装しないものを明記しておく（後から「無い」と驚かないように）:

  authorization_code / PKCE  … 利用者の同意が要る場面が無い。要るなら `oidc` で委譲する
  refresh_token              … client_secret があれば再取得できる。回転の複雑さを持ち込まない
  introspection / revocation … トークンは自己完結の JWT で短命。失効は Client を無効にする

これらが要るようになったら、その時点で外部の認可サーバ（Keycloak 等）に寄せる。
中途半端な認可サーバを育てるより、そのほうが安全。
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from arkhe.auth.apikey import _expired, _to_principal
from arkhe.auth.errors import AuthError, Forbidden
from arkhe.auth.principal import Principal
from arkhe.db.models import Client, CredentialKind

_ph = PasswordHasher()
ALGORITHM = "HS256"
SECRET_PREFIX = "arkhes_"
PREFIX_LEN = 8


def generate_secret() -> tuple[str, str, str]:
    raw = SECRET_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:PREFIX_LEN], _ph.hash(raw)


def _verify_secret(session: Session, client_id: str, secret: str) -> Client:
    client = session.scalar(
        select(Client)
        .where(Client.client_id == client_id, Client.active.is_(True))
        .options(selectinload(Client.credentials), selectinload(Client.manager))
    )
    if client is None or _expired(client.expires_at):
        raise AuthError("invalid client")
    for cred in client.credentials:
        if cred.kind != CredentialKind.CLIENT_SECRET.value or not cred.active:
            continue
        if _expired(cred.expires_at):
            continue
        try:
            _ph.verify(cred.hashed, secret)
        except (VerifyMismatchError, Exception):  # noqa: B014
            continue
        return client
    raise AuthError("invalid client")


def issue_token(
    session: Session,
    *,
    client_id: str,
    client_secret: str,
    requested_scope: str = "",
    secret_key: str,
    ttl: int = 3600,
    issuer: str = "",
) -> dict:
    """client_credentials でアクセストークンを発行する。

    **要求された scope は、登録済みの `allowed_scopes` との積しか出さない。**
    登録に無い scope をトークン要求で取れてしまうのは、権限昇格そのもの。
    """
    client = _verify_secret(session, client_id, client_secret)

    allowed = set(client.allowed_scopes.split())
    if requested_scope:
        asked = set(requested_scope.split())
        unknown = asked - allowed
        if unknown:
            # RFC 6749 §5.2 の invalid_scope。**黙って削らない**——クライアントが
            # 「取れたつもり」で動いて後段の 403 に驚くのを避ける。
            raise Forbidden({"error": "invalid_scope", "not_allowed": sorted(unknown)})
        granted = asked
    else:
        granted = allowed

    now = datetime.now(UTC)
    claims = {
        "sub": client.client_id,
        "client_id": client.client_id,
        "scope": " ".join(sorted(granted)),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
    }
    if issuer:
        claims["iss"] = issuer
    token = jwt.encode(claims, secret_key, algorithm=ALGORITHM)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": ttl,
        "scope": claims["scope"],
    }


def authenticate(session: Session, token: str, *, secret_key: str, issuer: str = "") -> Principal:
    """自前発行のトークンを検証して主体を引く。

    **scope はトークンから、到達範囲は Client から**取る。トークンに naan や
    shoulder を載せないのは、載せると失効させにくい情報が外に出るため
    （機関の統廃合で manager が変わっても、次のトークンから自然に反映される）。
    """
    try:
        options = {"require": ["exp", "iat", "sub"]}
        claims = jwt.decode(
            token,
            secret_key,
            algorithms=[ALGORITHM],
            issuer=issuer or None,
            options=options,
        )
    except jwt.PyJWTError as exc:
        raise AuthError(f"invalid token: {exc}") from exc

    client = session.scalar(
        select(Client)
        .where(Client.client_id == claims["sub"], Client.active.is_(True))
        .options(selectinload(Client.manager))
    )
    if client is None or _expired(client.expires_at):
        raise AuthError("client is no longer active")

    principal = _to_principal(client, mechanism="oauth2")
    # トークンに載った scope で**絞る**（広げはしない）。
    granted = frozenset(claims.get("scope", "").split()) & principal.scopes
    return Principal(**{**principal.__dict__, "scopes": granted})
