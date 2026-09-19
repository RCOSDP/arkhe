"""The token endpoint, present only when ARKHE_AUTH includes oauth2.

This is how arkhe issues tokens on its own, so that an organisation without an
authorisation server such as Keycloak can still call the API the OAuth2 way.

The only grant is client_credentials. Minting is machine to machine, from an
organisation's own system, and nothing here involves a person letting a third-party
application act for them. Where people have to sign in, that is delegated with oidc; see
ARKHE_ADMIN_LOGIN.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request, Response
from fastapi.openapi.models import OAuthFlowClientCredentials, OAuthFlows
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2

from arkhe import errors
from arkhe.api import i18n
from arkhe.auth import oauth2
from arkhe.auth.deps import Config, Db
from arkhe.auth.errors import AuthError, Forbidden
from arkhe.domain import authz

router = APIRouter(prefix="/oauth", tags=["oauth"])

#: This says in the document where a token comes from. Declaring it on a route puts
#: oauth2 into securitySchemes, gives Swagger UI its Authorize button, and lets a
#: generated client authenticate. The URL used to be in the README and nowhere else.
#:
#: Its value is unused, as with bearer_scheme: it is declared to be documented.
#: Verification happens in one place, auth.deps. auto_error=False for the same reason as
#: there: a public read must not become a 403 here.
#:
#: The vocabulary comes from authz.SCOPES and the wording from the same catalogue as the
#: admin interface. There is no third copy; another one would mean a scope that can be
#: registered with nothing explaining it.
scheme = OAuth2(
    scheme_name="oauth2",
    description="Tokens arkhe issues itself (RFC 6749 §4.4 client_credentials).",
    flows=OAuthFlows(
        clientCredentials=OAuthFlowClientCredentials(
            tokenUrl=f"{router.prefix}/token",
            scopes={s: i18n.EN[f"sc.{s}"] for s in authz.SCOPES},
        )
    ),
    auto_error=False,
)


@router.post(
    "/token",
    summary="Issue an access token (client_credentials)",
    description=(
        "RFC 6749 §4.4 client_credentials.\n\n"
        "Credentials are accepted **in the body or by Basic authentication** "
        "(§2.3.1 recommends Basic and permits the body; client libraries in the "
        "wild use both)."
    ),
)
def token(
    request: Request,
    session: Db,
    cfg: Config,
    response: Response,
    grant_type: Annotated[str, Form()] = "",
    client_id: Annotated[str, Form()] = "",
    client_secret: Annotated[str, Form()] = "",
    scope: Annotated[str, Form()] = "",
):
    """client_credentials, RFC 6749 4.4.

    Credentials are accepted in the body or by Basic authentication. 2.3.1 recommends
    Basic and permits the body, and client libraries in the wild use both.
    """
    if "oauth2" not in cfg.auth:
        return JSONResponse(
            {"error": "unsupported_grant_type",
             "error_description": errors.TOKEN_ENDPOINT_DISABLED.message,
             "code": errors.TOKEN_ENDPOINT_DISABLED.number},
            status_code=404,
        )
    if grant_type != "client_credentials":
        # There is no other grant. What is not implemented is said plainly.
        return JSONResponse(
            {"error": "unsupported_grant_type",
             "error_description": errors.UNSUPPORTED_GRANT_TYPE.message,
             "code": errors.UNSUPPORTED_GRANT_TYPE.number},
            status_code=400,
        )

    if not client_id:
        client_id, client_secret = _basic(request) or ("", "")

    try:
        body = oauth2.issue_token(
            session,
            client_id=client_id,
            client_secret=client_secret,
            requested_scope=scope,
            secret_key=cfg.token_secret,
            ttl=cfg.token_ttl,
            issuer=cfg.token_issuer,
        )
    except AuthError:
        session.commit()
        # RFC 6749 5.2: wrong credentials are invalid_client. The reason is not
        # broken down, or client ids could be found by trying them.
        return JSONResponse(
            {"error": "invalid_client"},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="arkhe"'},
        )
    except Forbidden as exc:
        return JSONResponse(exc.detail, status_code=400)

    session.commit()
    # 5.1: a token response must not be cached.
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return body


def _basic(request: Request) -> tuple[str, str] | None:
    import base64
    import binascii

    raw = request.headers.get("authorization", "")
    if not raw.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(raw[6:].strip()).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
    cid, _, secret = decoded.partition(":")
    return cid, secret
