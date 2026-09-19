"""FastAPI dependencies. Each configured mechanism is tried in turn and the first that
succeeds wins.

The order is the order of ARKHE_AUTH: with apikey,oidc a token is read as an API key
first and as an OIDC JWT second. No reason is returned, because saying which mechanism
refused it helps in guessing the shape of a credential.

WWW-Authenticate advertises only the mechanisms that are live, so that a client can
discover what to send. The specification recommends this too.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from arkhe import errors, observability
from arkhe.auth import apikey, oauth2
from arkhe.auth.errors import AuthError, UnregisteredSubject
from arkhe.auth.oidc import OidcVerifier
from arkhe.auth.principal import Principal
from arkhe.db.session import get_session
from arkhe.domain import authz
from arkhe.settings import Settings, get_settings

_oidc_verifier: OidcVerifier | None = None


def oidc_verifier(settings: Settings) -> OidcVerifier:
    global _oidc_verifier
    if _oidc_verifier is None:
        _oidc_verifier = OidcVerifier(
            settings.oidc_issuer, settings.oidc_audience, settings.oidc_jwks_url
        )
    return _oidc_verifier


#: This both extracts the token and documents it: declaring it as a dependency puts
#: securitySchemes into the OpenAPI document and gives Swagger UI an Authorize button.
#: auto_error=False keeps public reads open to anonymous callers; answering 403 here
#: would break that.
bearer_scheme = HTTPBearer(
    scheme_name="bearer",
    description=(
        "An API key (apikey mode), a token arkhe issued (oauth2 mode), or a JWT from "
        "an external authorisation server (oidc mode). Which mechanisms are live is "
        "set by ARKHE_AUTH."
    ),
    auto_error=False,
)


def bearer(request: Request) -> str:
    raw = request.headers.get("authorization", "")
    if not raw.lower().startswith("bearer "):
        return ""
    return raw[7:].strip()


def challenge_for(settings: Settings) -> str:
    """Advertise the live mechanisms in WWW-Authenticate."""
    parts = ['Bearer realm="arkhe"']
    if "oidc" in settings.auth and settings.oidc_issuer:
        parts.append(f'authorization_uri="{settings.oidc_issuer}"')
    if "oauth2" in settings.auth:
        parts.append('token_endpoint="/oauth/token"')
    return ", ".join(parts)


def authenticate(
    token: str, session: Session, settings: Settings, ip: str = ""
) -> Principal:
    """Try each mechanism in turn; 401 if none of them succeeds."""
    if not token:
        raise AuthError(errors.NO_CREDENTIALS, challenge=challenge_for(settings))

    tried: list[str] = []
    unregistered: UnregisteredSubject | None = None
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
        except UnregisteredSubject as exc:
            # The signature verified but the principal is not in the ledger. The
            # string is kept: a misspelt client_id is the most common way this setup
            # gets stuck, and an operator can register it without retyping.
            unregistered = exc
            tried.append(f"{mechanism}: {exc.detail}")
            continue
        except AuthError as exc:
            # The reason is not returned to the caller but it is kept here. Without
            # it, nobody can tell an expired credential from a stopped organisation.
            tried.append(f"{mechanism}: {exc.detail}")
            continue  # try the next mechanism
    observability.log("auth failed", mechanisms=tried)
    if unregistered is not None:
        _remember(session, unregistered, ip)
    raise AuthError(errors.INVALID_CREDENTIALS, challenge=challenge_for(settings))


def _remember(session: Session, exc: UnregisteredSubject, ip: str) -> None:
    """Record an unregistered principal. A failure here still answers 401.

    The record is a convenience for operators, not part of the decision. A deployment
    may point at a read-only database, and failing to write must not turn into a 500.

    It commits immediately. An AuthError follows and the request session is rolled back
    (db/session.py), so without the commit the record would be rolled back with it.
    """
    try:
        authz.record_unknown_subject(
            session, subject=exc.subject, issuer=exc.issuer, ip=ip
        )
        session.commit()
    except Exception as err:  # pragma: no cover - only happens on the database side
        session.rollback()
        observability.log("could not record unknown subject", error=str(err))


def client_ip(request: Request, settings: Settings) -> str:
    """The caller's address. How many proxies to trust is a setting.

    Anyone can set X-Forwarded-For. Taking the leftmost entry unconditionally fills the
    audit log with strings an attacker chose, which is worse than recording the direct
    peer.

    So by default (trusted_proxies=0) the header is ignored. With n proxies in front,
    the nth entry from the right is used: the rightmost was written by the proxy
    immediately in front, which can be trusted. A shorter header is suspect, so it falls
    back to the direct peer.
    """
    peer = request.client.host if request.client else ""
    n = settings.trusted_proxies
    if n <= 0:
        return peer
    raw = request.headers.get("x-forwarded-for", "")
    chain = [x.strip() for x in raw.split(",") if x.strip()]
    if len(chain) < n:
        # Shorter than expected means the route is not what we assumed. What is
        # missing is never filled in from what the client claims.
        return peer
    return chain[-n]


def current_principal(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> Principal:
    # The token is read by bearer(). _cred is declared only so that it appears in the
    # OpenAPI document; its value is unused, which keeps this the same as the paths
    # where the credential does not come from a header.
    #
    # The caller address is known only at the request layer. It is carried for the audit
    # log, and it is needed when recording an unregistered principal, so it is taken
    # before authentication.
    ip = client_ip(request, settings)
    return replace(authenticate(bearer(request), session, settings, ip), ip=ip)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
Db = Annotated[Session, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]
