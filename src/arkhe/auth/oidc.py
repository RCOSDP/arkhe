"""外部の認可サーバ（Keycloak 等）が発行した JWT を検証する。**arkhe は資源側に徹する。**

トークン発行・利用者管理・同意・認可コードフローはすべて向こうの仕事で、ここは
JWKS で署名を確かめ、`iss` / `aud` / `exp` を見るだけ。認可サーバのコードを
1 行も持たない。

**主体の到達範囲は依然として Client 表から引く。** 外部トークンのクレームに
naan や shoulder が入っていても信用しない——認可サーバは「誰か」を保証するが、
「その人がどの名前空間を触ってよいか」は arkhe の台帳が決めることだから。
"""

from __future__ import annotations

import threading
import time

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from arkhe.auth.apikey import _expired, _mechanism_allowed, _to_principal
from arkhe.auth.errors import AuthError
from arkhe.auth.principal import Principal
from arkhe.db.models import Client

#: JWKS の再取得間隔。鍵の回転に追随しつつ、毎回取りに行かない。
JWKS_TTL = 300


class JwksCache:
    """JWKS を TTL つきで持つ。**取得失敗時に古い鍵で凌ぐ**（認可サーバの一時停止で
    解決まで巻き添えにしない）。"""

    def __init__(self, url: str, ttl: int = JWKS_TTL):
        self.url = url
        self.ttl = ttl
        self._lock = threading.Lock()
        self._client: jwt.PyJWKClient | None = None
        self._at = 0.0

    def client(self) -> jwt.PyJWKClient:
        with self._lock:
            if self._client is None or time.time() - self._at > self.ttl:
                try:
                    self._client = jwt.PyJWKClient(self.url, cache_keys=True)
                    self._at = time.time()
                except Exception:
                    if self._client is None:
                        raise
            return self._client


def discover_jwks_url(issuer: str, *, verify: bool | str = True) -> str:
    """issuer の OIDC discovery から JWKS の場所を引く。"""
    url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    with httpx.Client(verify=verify, timeout=10) as c:
        r = c.get(url)
    r.raise_for_status()
    jwks = r.json().get("jwks_uri")
    if not jwks:
        raise RuntimeError(f"{url} に jwks_uri がありません")
    return jwks


class OidcVerifier:
    def __init__(
        self, issuer: str, audience: str, jwks_url: str = "", *, verify: bool | str = True
    ):
        self.issuer = issuer
        self.audience = audience
        self._verify = verify
        self._jwks_url = jwks_url
        self._cache: JwksCache | None = None

    def _jwks(self) -> JwksCache:
        if self._cache is None:
            url = self._jwks_url or discover_jwks_url(self.issuer, verify=self._verify)
            self._cache = JwksCache(url)
        return self._cache

    def decode(self, token: str) -> dict:
        key = self._jwks().client().get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256", "ES256"],
            issuer=self.issuer,
            audience=self.audience or None,
            leeway=10,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )

    def authenticate(self, session: Session, token: str) -> Principal:
        try:
            claims = self.decode(token)
        except Exception as exc:
            raise AuthError(f"invalid token: {exc}") from exc

        # 外部の主体を arkhe の台帳に突き合わせる。**登録が無ければ通さない。**
        # 認可サーバで認証できることと、この ARK 名前空間を触ってよいことは別。
        subject = claims.get("azp") or claims.get("client_id") or claims["sub"]
        client = session.scalar(
            select(Client)
            .where(Client.client_id == subject, Client.active.is_(True))
            .options(selectinload(Client.manager))
        )
        if client is None or _expired(client.expires_at):
            raise AuthError(f"subject {subject} is not registered with this resolver")
        # **組織に許されていない機構では通さない**（apikey / oauth2 と同じ）。
        if not _mechanism_allowed(client, "oidc"):
            raise AuthError("this mechanism is not allowed for the organisation")

        principal = _to_principal(client, mechanism="oidc")
        return Principal(**{**principal.__dict__, "scopes": _granted(claims, principal)})


def _granted(claims: dict, principal: Principal) -> frozenset[str]:
    """トークンの scope で**絞る**（広げはしない）。

    認可サーバが arkhe の語彙（`ark:*`）を持っているなら、それが権限の表明なので
    登録済みの範囲との積を採る。**持っていないなら登録済みの範囲をそのまま使う。**

    後者を素通しにしても危なくないのは、`aud` の検証が先に効いているから——
    このリゾルバ宛でないトークンはここに届かない。逆に、無関係な語彙
    （`profile` `email` など）と積を採ると必ず空集合になり、「認証は通ったのに
    何もできない」という分かりにくい 403 を生むだけになる。
    """
    raw = claims.get("scope") or " ".join(claims.get("scp") or [])
    asked = {s for s in raw.split() if s.startswith("ark:")}
    return frozenset(asked & principal.scopes) if asked else principal.scopes
