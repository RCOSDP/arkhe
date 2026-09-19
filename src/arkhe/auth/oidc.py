"""Verifying a JWT issued by an external authorisation server, such as Keycloak. arkhe
is purely the resource side.

Issuing tokens, managing users, consent and the authorization code flow all belong over
there. Here the signature is checked against the JWKS and iss, aud and exp are read.
There is no authorisation server code in this file.

The principal's reach still comes from the Client table. A naan or a shoulder in the
token's claims is not trusted: the authorisation server vouches for who someone is,
while which namespace they may touch is decided by this ledger.
"""

from __future__ import annotations

import threading
import time

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from arkhe import errors
from arkhe.auth.apikey import _expired, _mechanism_allowed, _to_principal
from arkhe.auth.errors import AuthError, UnregisteredSubject
from arkhe.auth.principal import Principal
from arkhe.db.models import Client

#: How often the JWKS is fetched again: often enough to follow key rotation, not on
#: every request.
JWKS_TTL = 300


class JwksCache:
    """Holds the JWKS with a TTL, falling back to the old keys when a fetch fails, so
    that a brief outage at the authorisation server does not take resolution with
    it."""

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
    """Find the JWKS location through the issuer's OIDC discovery document."""
    url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    with httpx.Client(verify=verify, timeout=10) as c:
        r = c.get(url)
    r.raise_for_status()
    jwks = r.json().get("jwks_uri")
    if not jwks:
        raise RuntimeError(f"{url} has no jwks_uri")
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
            raise AuthError(errors.INVALID_CREDENTIALS, reason=str(exc)) from exc

        # Match the external principal against this ledger. Without a registration it
        # does not get in: authenticating at the authorisation server and being allowed
        # to touch this namespace are different things.
        subject = claims.get("azp") or claims.get("client_id") or claims["sub"]
        client = session.scalar(
            select(Client)
            .where(Client.client_id == subject)
            .options(selectinload(Client.manager))
        )
        if client is None:
            # Keep the string that was refused. The caller records it, and an
            # operator can register it without retyping
            # (domain.authz.record_unknown_subject).
            raise UnregisteredSubject(subject, self.issuer)
        # A stopped principal is not an unregistered one. Listing something stopped
        # on purpose as forgotten would mean registering it again to clear the list,
        # which undoes the stopping. The answer is 401 either way; the record differs.
        if not client.active or _expired(client.expires_at):
            raise AuthError(errors.INVALID_CREDENTIALS,
                            reason=f"subject {subject} is registered but not usable")
        # A mechanism the organisation may not use is refused, as for apikey and
        # oauth2.
        if not _mechanism_allowed(session, client, "oidc"):
            raise AuthError(errors.INVALID_CREDENTIALS,
                            reason="this mechanism is not allowed for the organisation")

        principal = _to_principal(client, mechanism="oidc")
        return Principal(**{**principal.__dict__, "scopes": _granted(claims, principal)})


def _granted(claims: dict, principal: Principal) -> frozenset[str]:
    """Narrow the reach by the token's scope; never widen it.

    If the authorisation server knows our vocabulary (ark:*), that is a statement of
    permission, so it is intersected with what was registered. If it does not, the
    registered reach is used as it stands.

    Passing the second case through is safe because aud has already been verified: a
    token not meant for this resolver never reaches here. Intersecting with an unrelated
    vocabulary such as profile or email would always give the empty set, and produce a
    confusing 403 where authentication succeeded but nothing is permitted.
    """
    raw = claims.get("scope") or " ".join(claims.get("scp") or [])
    asked = {s for s in raw.split() if s.startswith("ark:")}
    return frozenset(asked & principal.scopes) if asked else principal.scopes
