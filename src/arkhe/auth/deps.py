"""FastAPI の依存。**設定された機構を順に試し、最初に成功したものを採る。**

順序は `ARKHE_AUTH` の並び。`apikey,oidc` なら API キーとして解釈し、駄目なら
OIDC の JWT として解釈する。**失敗の理由は返さない**——どの機構で弾かれたかを
教えると、資格情報の形を総当たりで探る手掛かりになる。

`WWW-Authenticate` には有効な機構だけを載せる。クライアントが「何を出せばよいか」
を発見できるようにするためで、これは仕様上も SHOULD。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from arkhe import observability
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


#: **抽出と文書化を兼ねる。** これを依存に置くことで OpenAPI に
#: `securitySchemes` が載り、Swagger UI に Authorize ボタンが出る。
#: `auto_error=False` なのは、公開情報の読取を未認証で通すため——ここで 403 を
#: 返してしまうと、その方針が壊れる。
bearer_scheme = HTTPBearer(
    scheme_name="bearer",
    description=(
        "API キー（apikey モード）、arkhe が発行したトークン（oauth2 モード）、"
        "外部の認可サーバが発行した JWT（oidc モード）のいずれか。"
        "有効な機構は ARKHE_AUTH で決まる。"
    ),
    auto_error=False,
)


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

    tried: list[str] = []
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
        except AuthError as exc:
            # **理由は利用者に返さないが、ここには残す。** 「鍵が期限切れ」なのか
            # 「組織が停止中」なのかを運用者が知る手段が無いと、切り分けられない。
            tried.append(f"{mechanism}: {exc.detail}")
            continue  # 次の機構を試す
    observability.log("auth failed", mechanisms=tried)
    raise AuthError("invalid credentials", challenge=challenge_for(settings))


def client_ip(request: Request, settings: Settings) -> str:
    """接続元のアドレス。**前段を信じる段数を設定で決める。**

    `X-Forwarded-For` は誰でも付けられるヘッダである。無条件に左端を採ると、
    **監査ログに攻撃者の書いた文字列が並ぶ**——直接の接続元を記録するより悪い。

    だから既定（`trusted_proxies=0`）では見ない。前段が n 段あるなら、
    **右から n 番目**を採る。右端は自分の直前の前段が書いた値で、そこは信じられる。
    ヘッダが短ければ、詐称の疑いがあるので直接の接続元に落とす。
    """
    peer = request.client.host if request.client else ""
    n = settings.trusted_proxies
    if n <= 0:
        return peer
    raw = request.headers.get("x-forwarded-for", "")
    chain = [x.strip() for x in raw.split(",") if x.strip()]
    if len(chain) < n:
        # 前段より短い＝経路が想定と違う。**足りない分を client の申告で埋めない。**
        return peer
    return chain[-n]


def current_principal(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> Principal:
    # トークンは `bearer()` で取る。`_cred` は OpenAPI に載せるためだけの依存で、
    # **値は使わない**——`ark:/…` のようにヘッダ以外から来る経路と扱いを揃えるため。
    p = authenticate(bearer(request), session, settings)
    # **接続元は要求の層でだけ分かる。** 監査に残すために運ぶ。
    return replace(p, ip=client_ip(request, settings))


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
Db = Annotated[Session, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]
