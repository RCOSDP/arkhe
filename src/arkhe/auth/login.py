"""管理画面へのログイン。**ブラウザから人が入るための経路。**

API は Bearer トークンで足りるが、**ブラウザは Authorization ヘッダを付けられない**。
そこで管理画面だけ、入口を選べるようにする（`ARKHE_ADMIN_LOGIN`）。

  bearer  既定。ログイン画面を持たない。トークンを付けられる相手（curl・自動化）専用
  oidc    arkhe が **OIDC のクライアント（RP）として**認可コードフローを回し、
          戻ってきた身元をセッションにする
  proxy   前段の認証プロキシ（oauth2-proxy、nginx の OIDC など）が済ませた前提で、
          そのヘッダを信じる

**「クライアントになる」ことと「認可サーバになる」ことは別。** 見送ったのは後者で、
トークンを発行し同意を預かる役目のこと。ここでやるのは、認可サーバに人を送り、
戻ってきた JWT を確かめるだけ——資源側の仕事の範囲に収まる。
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from arkhe.auth.apikey import _expired, _to_principal
from arkhe.auth.errors import AuthError
from arkhe.auth.principal import Principal
from arkhe.db.models import Client
from arkhe.settings import Settings

#: 認可サーバへ送り出すときに、戻り先と PKCE の検証子を預けておく Cookie。
#: **短命**（フローの往復ぶんだけ）。
FLOW_COOKIE = "arkhe_login"
FLOW_TTL = 600


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def start(settings: Settings, *, redirect_uri: str, next_url: str = "/admin/") -> tuple[str, str]:
    """認可要求の URL と、預けておく値（署名前）を作る。

    **PKCE を必ず付ける。** 認可コードはブラウザのアドレス欄・履歴・前段のログに
    残るので、横取りされても使えないようにしておく。
    """
    verifier = _b64u(secrets.token_bytes(32))
    challenge = _b64u(hashlib.sha256(verifier.encode()).digest())
    state = _b64u(secrets.token_bytes(16))
    params = {
        "response_type": "code",
        "client_id": settings.admin_client_id,
        "redirect_uri": redirect_uri,
        "scope": settings.admin_scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = f"{_endpoint(settings, 'authorization_endpoint')}?{urlencode(params)}"
    return url, jwt_flow_payload(state, verifier, next_url)


def jwt_flow_payload(state: str, verifier: str, next_url: str) -> str:
    import json

    return json.dumps({"state": state, "verifier": verifier, "next": next_url})


_discovery: dict | None = None


def _endpoint(settings: Settings, name: str) -> str:
    global _discovery
    if _discovery is None:
        url = f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
        with httpx.Client(timeout=10) as c:
            r = c.get(url)
        r.raise_for_status()
        _discovery = r.json()
    if name not in _discovery:
        raise RuntimeError(f"認可サーバのメタデータに {name} がありません")
    return _discovery[name]


def finish(
    session: Session, settings: Settings, *, code: str, verifier: str, redirect_uri: str
) -> Principal:
    """認可コードをトークンに換え、身元を確かめて主体に写す。"""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": settings.admin_client_id,
        "code_verifier": verifier,
    }
    if settings.admin_client_secret:
        data["client_secret"] = settings.admin_client_secret
    with httpx.Client(timeout=15) as c:
        r = c.post(_endpoint(settings, "token_endpoint"), data=data)
    if r.status_code != 200:
        raise AuthError(f"トークン要求に失敗しました: {r.status_code} {r.text[:200]}")
    tok = r.json()

    from arkhe.auth.oidc import OidcVerifier

    verifier_obj = OidcVerifier(
        settings.oidc_issuer, settings.oidc_audience or settings.admin_client_id,
        settings.oidc_jwks_url,
    )
    claims = verifier_obj.decode(tok.get("id_token") or tok["access_token"])
    subject = claims.get("preferred_username") or claims.get("email") or claims["sub"]
    return by_subject(session, subject, mechanism="oidc-login")


def by_subject(session: Session, subject: str, *, mechanism: str) -> Principal:
    """外部で確かめた身元を、arkhe の台帳に突き合わせる。

    **登録が無ければ通さない。** 認可サーバで認証できることと、この名前空間を
    触ってよいことは別。
    """
    client = session.scalar(
        select(Client)
        .where(Client.client_id == subject, Client.active.is_(True))
        .options(selectinload(Client.manager))
    )
    if client is None or _expired(client.expires_at):
        raise AuthError(f"{subject} はこのリゾルバに登録されていません")
    return _to_principal(client, mechanism=mechanism)


def from_proxy(session: Session, settings: Settings, headers) -> Principal:
    """前段の認証プロキシが立てたヘッダを信じる。

    **arkhe に直接届く経路が残っていると、誰でもヘッダを詐称できる。** この方式を
    選ぶなら、arkhe をプロキシの後ろにだけ置くこと（k8s なら NetworkPolicy、
    単体なら 127.0.0.1 だけで待ち受ける）。設定を明示的に選ばせているのはこのため。
    """
    subject = headers.get(settings.proxy_user_header.lower(), "")
    if not subject:
        raise AuthError(f"{settings.proxy_user_header} が立っていません")
    return by_subject(session, subject, mechanism="proxy")


def decode_id_token_unverified(token: str) -> dict:  # pragma: no cover - 診断用
    return jwt.decode(token, options={"verify_signature": False})
