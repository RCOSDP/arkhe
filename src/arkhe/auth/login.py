"""Signing in to the admin interface: how a person gets in from a browser.

A bearer token is enough for the API, but a browser cannot set an Authorization header,
so the admin interface has a choice of entrances (ARKHE_ADMIN_LOGIN).

  bearer  the default. No login page; for callers that can send a token, such as curl
  oidc    arkhe acts as an OIDC relying party, runs the authorization code flow and
          turns the identity it gets back into a session
  proxy   an authenticating proxy in front (oauth2-proxy, nginx with OIDC) has already
          done the work, and its header is trusted

Being a client and being an authorisation server are different jobs. The second one,
issuing tokens and holding consent, is not done here. This sends a person to the
authorisation server and verifies the JWT that comes back, which stays within what the
resource side does.
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
from arkhe.db.models import Client, Subject
from arkhe.settings import Settings

#: The cookie that carries where to return to and the PKCE verifier while the person is
#: at the authorisation server. It lives only for that round trip.
FLOW_COOKIE = "arkhe_login"
FLOW_TTL = 600


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def start(settings: Settings, *, redirect_uri: str, next_url: str = "/admin/") -> tuple[str, str]:
    """Build the authorisation request URL and the values to carry, before signing.

    PKCE is always used. An authorization code appears in the address bar, in history
    and in the logs of anything in front, so it must be useless to whoever intercepts
    it.
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
        raise RuntimeError(f"the authorisation server metadata has no {name}")
    return _discovery[name]


def end_session_url(settings: Settings, *, post_logout_redirect: str) -> str:
    """The URL that also ends the session at the authorisation server (OIDC
    RP-Initiated Logout 1.0).

    Dropping our cookie is not signing out. Opening /admin/ again goes to the
    authorisation server, and with the session there still alive the person comes back
    without being asked anything: from where they stand, signing out does not work.

    id_token_hint is not sent. Sending it would mean keeping the ID token in the session
    cookie, and where claims about membership and roles are many the cookie passes 4 KB,
    at which point browsers drop it and nobody can sign in at all. client_id is sent
    instead. The authorisation server then asks for confirmation, which also guards
    against sign-out by cross-site request.

    With no end_session_endpoint in the metadata this returns an empty string: that
    server does not support logout initiated by the relying party, so it is ended
    here alone.
    """
    try:
        endpoint = _endpoint(settings, "end_session_endpoint")
    except RuntimeError:
        return ""
    query = urlencode(
        {
            "client_id": settings.admin_client_id,
            "post_logout_redirect_uri": post_logout_redirect,
        }
    )
    return f"{endpoint}?{query}"


def finish(
    session: Session, settings: Settings, *, code: str, verifier: str, redirect_uri: str
) -> Principal:
    """Exchange the authorization code for tokens, verify the identity and map it to a
    principal."""
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
        raise AuthError(f"token request failed: {r.status_code} {r.text[:200]}")
    tok = r.json()

    from arkhe.auth.oidc import OidcVerifier

    # The aud of an ID token is always this client itself (OIDC Core, 2). The API's
    # oidc_audience must not be reused: an access token and an ID token are addressed
    # differently, and mixing them breaks one of the two.
    verifier_obj = OidcVerifier(
        settings.oidc_issuer, settings.admin_client_id, settings.oidc_jwks_url
    )
    claims = verifier_obj.decode(tok.get("id_token") or tok["access_token"])
    subject = claims.get("preferred_username") or claims.get("email") or claims["sub"]
    return by_subject(session, subject, mechanism="oidc-login")


def by_subject(session: Session, subject: str, *, mechanism: str) -> Principal:
    """Match an identity established elsewhere against this ledger.

    Without a registration it does not get in: authenticating at the authorisation
    server and being allowed to touch this namespace are different things.
    """
    client = session.scalar(
        select(Client)
        .where(Client.client_id == subject, Client.active.is_(True))
        .options(selectinload(Client.manager))
    )
    if client is None or _expired(client.expires_at):
        raise AuthError(f"subject {subject} is not registered with this resolver")
    # A machine principal cannot sign in this way. Even if the proxy is misconfigured
    # and the header arrives from outside, nobody can become the loading batch or a
    # minting client.
    if client.subject_type != Subject.PERSON:
        raise AuthError(f"subject {subject} is not a person and cannot sign in")
    return _to_principal(client, mechanism=mechanism)


def from_proxy(session: Session, settings: Settings, headers) -> Principal:
    """Trust the header set by an authenticating proxy in front.

    If anything can still reach arkhe directly, anyone can forge that header. Choosing
    this mode means putting arkhe only behind the proxy: a NetworkPolicy on Kubernetes,
    or listening on 127.0.0.1 alone. That is why the mode has to be chosen explicitly.
    """
    subject = headers.get(settings.proxy_user_header.lower(), "")
    if not subject:
        raise AuthError(f"{settings.proxy_user_header} is not set")
    return by_subject(session, subject, mechanism="proxy")


def decode_id_token_unverified(token: str) -> dict:  # pragma: no cover - for diagnosis
    return jwt.decode(token, options={"verify_signature": False})
