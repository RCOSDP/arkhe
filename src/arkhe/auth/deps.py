"""FastAPI の依存。**設定された機構を順に試し、最初に成功したものを採る。**

順序は `ARKHE_AUTH` の並び。`apikey,oidc` なら API キーとして解釈し、駄目なら
OIDC の JWT として解釈する。**失敗の理由は返さない**——どの機構で弾かれたかを
教えると、資格情報の形を総当たりで探る手掛かりになる。

`WWW-Authenticate` には有効な機構だけを載せる。クライアントが「何を出せばよいか」
を発見できるようにするためで、これは仕様上も SHOULD。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from arkhe.auth import apikey, oauth2
from arkhe.auth.errors import AuthError
from arkhe.auth.oidc import OidcVerifier
from arkhe.auth.principal import Principal
from arkhe.db.session import get_session
from arkhe.settings import Settings, get_settings

_oidc_verifier: OidcVerifier | None = None


def oidc_verifier(settings: Settings) -> OidcVerifier:
    global _oidc_verifier
    if _oidc_verifier is None:
        _oidc_verifier = OidcVerifier(
            settings.oidc_issuer, settings.oidc_audience, settings.oidc_jwks_url
        )
    return _oidc_verifier


def bearer(request: Request) -> str:
    raw = request.headers.get("authorization", "")
    if not raw.lower().startswith("bearer "):
        return ""
    return raw[7:].strip()


def challenge_for(settings: Settings) -> str:
    """有効な機構を `WWW-Authenticate` で広告する。"""
    parts = ['Bearer realm="arkhe"']
    if "oidc" in settings.auth and settings.oidc_issuer:
        parts.append(f'authorization_uri="{settings.oidc_issuer}"')
    if "oauth2" in settings.auth:
        parts.append('token_endpoint="/oauth/token"')
    return ", ".join(parts)


def authenticate(
    token: str, session: Session, settings: Settings
) -> Principal:
    """機構を順に試す。**どれも通らなければ 401。**"""
    if not token:
        raise AuthError("no credentials", challenge=challenge_for(settings))

    for mechanism in settings.auth:
        try:
            if mechanism == "apikey":
                return apikey.authenticate(session, token)
            if mechanism == "oauth2":
                return oauth2.authenticate(
                    session,
                    token,
                    secret_key=settings.token_secret,
                    issuer=settings.token_issuer,
                )
            if mechanism == "oidc":
                return oidc_verifier(settings).authenticate(session, token)
        except AuthError:
            continue  # 次の機構を試す
    raise AuthError("invalid credentials", challenge=challenge_for(settings))


def current_principal(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    return authenticate(bearer(request), session, settings)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
Db = Annotated[Session, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]
