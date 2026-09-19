"""Issuing our own OAuth2 tokens, with the client_credentials grant and nothing else.

Minting is called by an organisation's repository system, sometimes from a nightly
batch. There is no person and no browser. The authorization code flow solves the problem
of a person letting a third-party application act for them, which does not arise here.

What is not implemented, said plainly so that nobody discovers it later:

  authorization_code and PKCE  nothing here needs a person's consent; delegate with oidc
  refresh_token                a client secret can fetch another token, without rotation
  introspection and revocation tokens are short-lived JWTs; disable the Client instead

If any of these become necessary, that is the moment to move to an external
authorisation server such as Keycloak, rather than growing half of one here.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from arkhe import errors
from arkhe.auth.apikey import _expired, _mechanism_allowed, _to_principal
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
        raise AuthError(errors.INVALID_CREDENTIALS)
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
    raise AuthError(errors.INVALID_CREDENTIALS)


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
    """Issue an access token with client_credentials.

    A requested scope is intersected with the registered allowed_scopes. Obtaining a
    scope that was never registered, just by asking, would be privilege escalation.
    """
    client = _verify_secret(session, client_id, client_secret)

    allowed = set(client.allowed_scopes.split())
    if requested_scope:
        asked = set(requested_scope.split())
        unknown = asked - allowed
        if unknown:
            # invalid_scope, as RFC 6749 5.2 defines it. The scope is not trimmed
            # silently, or the client would act as though it held the permission and
            # meet a 403 later.
            #
            # The body is shaped differently here. Errors from a token endpoint are
            # read from error, as 5.2 requires and as client libraries expect, so our
            # own code is carried alongside without disturbing that shape.
            raise Forbidden(
                {
                    "error": "invalid_scope",
                    "error_description": errors.INVALID_SCOPE.say(
                        scopes=", ".join(sorted(unknown))
                    ),
                    "code": errors.INVALID_SCOPE.number,
                    "not_allowed": sorted(unknown),
                }
            )
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
    """Verify a token we issued and find the principal.

    The scope comes from the token and the reach from the Client. Putting the naan or
    the shoulder in the token would put hard-to-revoke information outside; read from
    the Client, a merger takes effect from the next token.
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
        raise AuthError(errors.INVALID_CREDENTIALS, reason=str(exc)) from exc

    client = session.scalar(
        select(Client)
        .where(Client.client_id == claims["sub"], Client.active.is_(True))
        .options(selectinload(Client.manager))
    )
    if client is None or _expired(client.expires_at):
        raise AuthError(errors.INVALID_CREDENTIALS, reason="client is no longer active")
    # A mechanism the organisation is not allowed to use is refused, as for API keys.
    if not _mechanism_allowed(session, client, "oauth2"):
        raise AuthError(errors.INVALID_CREDENTIALS,
                        reason="this mechanism is not allowed for the organisation")

    principal = _to_principal(client, mechanism="oauth2")
    # The scope in the token narrows the reach and never widens it.
    granted = frozenset(claims.get("scope", "").split()) & principal.scopes
    return Principal(**{**principal.__dict__, "scopes": granted})
