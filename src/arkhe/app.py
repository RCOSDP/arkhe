"""Assembling the application. The routes it has follow its role.

  resolver  resolution only: it cannot mint and has no admin interface, so it can be
            pointed at a read-only role
  minter    the minting and update API
  admin     the admin screens, only when ARKHE_ADMIN=on

They are separate so that resolvers can be scaled on their own, and so that a process
without any minting route can exist. That allows running things where resolution must
never stop while minting may.
"""

from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import Response

from arkhe import __version__, observability
from arkhe.auth.errors import AuthError, Forbidden
from arkhe.db.session import session_factory
from arkhe.domain.authz import Conflict, Invalid, NotFound, ShoulderDelegated, Throttled
from arkhe.settings import Settings, get_settings

#: The description at the top of Swagger UI, putting what matters about the
#: specification where it is read before anything is tried.
API_DESCRIPTION = """\
Minting and resolution of ARK identifiers.

**An ARK is never re-assigned (NR).** That one commitment shapes most of this API.

* **A minted ARK cannot be withdrawn.** There is no delete; when an object is lost you
  `tombstone` it (the description stays, only reachability goes).
* **A resend does not mint again.** Send a `request_id` and the same value resent
  returns the same ARK. Batches of tens of thousands are interrupted more often than
  not, so an interrupted batch can simply be sent again.
* **Naming a shoulder in a request does not widen anything.** Reach comes from the
  credential's registration; omit it and the organisation's default is used.
* **Child resources are not minted.** A deep reference such as
  `ark:99999/x9tn1qkq2g7/page/3` is covered by suffix passthrough, so one record per
  minting is enough.

### Authentication

Put a bearer token in via `Authorize`. Which credentials are accepted is set at start-up
by `ARKHE_AUTH`: an API key, a token arkhe issued, or a JWT from an external
authorisation server (any combination).

**Reading public information needs no authentication**, because a repository shows its
public records to anyone.
"""

TAGS = [
    {
        "name": "ark",
        "description": (
            "Minting and updating. "
            "**A write never reaches outside the caller's registered reach.**"
        ),
    },
    {
        "name": "resolve",
        "description": (
            "Resolution, with the `?` (a brief description), `??` (the persistence "
            "statement), `?info` (for a person) and `?json` (for a program) "
            "inflections. **A description can be answered even when the object "
            "cannot be reached** (FAIR A2). Present only when started with "
            "`ARKHE_RESOLVER=1`."
        ),
    },
]


def _install_handlers(app: FastAPI) -> None:
    """Map domain exceptions to HTTP, so that the domain never knows about HTTP."""

    @app.exception_handler(AuthError)
    async def _auth(request: Request, exc: AuthError):  # noqa: ARG001
        return JSONResponse(
            exc.body(), status_code=401, headers={"WWW-Authenticate": exc.challenge}
        )

    @app.exception_handler(ShoulderDelegated)
    async def _delegated(request: Request, exc: ShoulderDelegated):  # noqa: ARG001
        # Point at the other endpoint with 307 rather than proxying. Calling on
        # someone's behalf means a lost response leaves an ARK minted over there that
        # we know nothing about.
        #
        # With no endpoint to call, 403. Location means "send the same request
        # there", so a page for people must not go in it; the guidance goes in the
        # body.
        if exc.minter:
            return JSONResponse(exc.body(), status_code=307, headers={"Location": exc.minter})
        return JSONResponse(exc.body(), status_code=403)

    from arkhe.api.admin import NeedsLogin

    @app.exception_handler(NeedsLogin)
    async def _needs_login(request: Request, exc: NeedsLogin):  # noqa: ARG001
        # Not a 401. A browser cannot add an Authorization header, so a 401 leaves
        # the person with nothing to do. Send them to sign in.
        from urllib.parse import quote

        return RedirectResponse(f"/admin/login?next={quote(exc.next_url)}", status_code=302)

    for exc_type, code in (
        (Forbidden, 403), (NotFound, 404), (Invalid, 400), (Conflict, 409),
        (Throttled, 429),
    ):

        @app.exception_handler(exc_type)
        async def _h(request: Request, exc, _code=code):  # noqa: ARG001
            # When a code is attached, use its status. If the type and the code
            # disagree, trusting the type would return a different code and make
            # diagnosis unreliable.
            return JSONResponse(exc.body(), status_code=getattr(exc, "status", _code))


#: The protective headers. The CSP is the substance; the rest supports it.
#:
#: Target schemes are restricted both when written and when read, but ?info is a public
#: page that needs no credentials, and whoever minted the ARK chooses the text on it.
#: Inline script is forbidden so that nothing runs even if the first layer is bypassed.
#:
#: style-src needs unsafe-inline because these pages embed their CSS in the HTML, which
#: keeps the number of served files down. No script is embedded at all, so script-src
#: can be none.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; "
        "script-src 'none'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # Whether this is served over HTTPS is decided in front, so no HSTS is added
    # here: on a deployment served over http it would make the host unreachable.
}


#: The API documentation is the exception. Swagger UI loads script from a CDN, so
#: script-src none would leave a blank page. It is loosened by naming the sources.
DOCS_CSP = (
    "default-src 'none'; "
    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'"
)
DOCS_PATHS = ("/api/docs", "/api/redoc")


#: A1: the label matches case-insensitively. draft-kunze-ark-42, 3.2, step 3:
#: "The **first case-insensitive match** on 'ark:/' or 'ark:' is converted to 'ark:'".
_LABEL_IN_PATH = re.compile(r"^/ark:", re.IGNORECASE)


def _install_ark_label_case(app: FastAPI) -> None:
    """Lower-case the ark: label in the path before the router matches it.

    parse_ark has always ignored case, but route matching does not, so /ARK:/99999/x9abc
    never reached the router and answered 404. Step 3 requires the label to match
    case-insensitively, and that is about what is accepted, which must not be narrowed.

    Only the five characters of the label are changed. The case of the name is part of
    the identifier (step 5: the case of all other letters must be preserved), so the
    rest of the path is left alone.

    raw_path is not touched. parse_ark strips the label case-insensitively, so it is
    unnecessary, and changing it would add a rewrite to the path that preserves percent
    encoding (A4).
    """

    @app.middleware("http")
    async def _label(request: Request, call_next):
        path = request.scope.get("path", "")
        if _LABEL_IN_PATH.match(path) and not path.startswith("/ark:"):
            request.scope["path"] = "/ark:" + path[5:]
        return await call_next(request)


def _install_allowed_hosts(app: FastAPI, hosts: list[str]) -> None:
    """Check the Host header. The setting existed for a while and was read by nothing.

    A setting that is declared and documented but does nothing is worse than no setting:
    an operator who set it counts the problem as handled while nothing is restricted.

    With ["*"], the default, no middleware is installed. Where a proxy terminates the
    connection it usually checks this, and refusing twice makes problems harder to
    place.
    """
    if not hosts or hosts == ["*"]:
        return
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)


def _install_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def _headers(request: Request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path in DOCS_PATHS:
            response.headers["Content-Security-Policy"] = DOCS_CSP
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build one application. Which routes it has follows the role (ARKHE_RESOLVER).

    Without settings it reads the environment, which is how it starts in production (
    `uvicorn arkhe.app:create_app --factory`）。
    """
    s = settings or get_settings()
    s.check()

    app = FastAPI(
        title="arkhe",
        summary="ARK identifier infrastructure — minter and resolver as separate services",
        description=API_DESCRIPTION,
        version=__version__,
        license_info={"name": "MIT", "identifier": "MIT"},
        openapi_tags=TAGS,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    # Pass the settings this app uses down to the request layer. Config and
    # get_session both receive Depends(get_settings), which caches the environment and
    # is not necessarily what create_app(settings=...) was given. When they differ, the
    # routes and the choice of database follow different settings: an app meant to be a
    # resolver connects to the write database, and a minter writes to a read-only
    # replica.
    app.dependency_overrides[get_settings] = lambda: s

    _install_handlers(app)
    _install_ark_label_case(app)
    _install_security_headers(app)
    _install_allowed_hosts(app, s.allowed_hosts)
    observability.configure(s.log_level)
    observability.install(app)

    # Every role needs a liveness endpoint. This used to live only on the resolve
    # router, so the minter and the admin interface answered 404 to the probe and
    # kubelet kept killing them. It touches neither authentication nor the database: it
    # answers only whether this process itself is up.
    @app.get("/healthz", include_in_schema=False)
    def healthz():
        """Whether the process is alive. It looks at no dependency: adding one would
        take away what this probe is for."""
        return {"ok": True}

    @app.get("/readyz", include_in_schema=False)
    def readyz(response: Response):
        """Whether requests can be served. This one looks at the database.

        Both used to share /healthz, so with the database down it kept answering Ready
        and kept receiving traffic. Being alive and being able to serve are different
        questions.

        It probes the side this role actually reads. A resolver reads from
        ARKHE_READ_DATABASE_URL, the replica, so probing the primary proves nothing:
        with the replica down and resolution answering 500, a live primary kept it
        answering Ready. That was checked by taking a replica down.
        """
        # Not taken as a dependency. A failure while dependencies are resolved would
        # be a 500 before this function runs, and it could not answer 503. The session
        # is opened here instead.
        try:
            with session_factory(read_only=s.resolver, settings=s)() as probe:
                probe.execute(text("select 1"))
        except Exception as exc:  # noqa: BLE001 - whatever the reason, it cannot serve
            observability.log("not ready", reason=type(exc).__name__)
            response.status_code = 503
            return {"ok": False, "db": "unreachable"}
        return {"ok": True}

    if s.resolver:
        from arkhe.api import resolve

        app.include_router(resolve.router)
        return app  # as the minter has no resolution route, a resolver has no
                    # minting route

    from arkhe.api import admin, mint

    if "oauth2" in s.auth:
        # The endpoint exists only where we issue tokens ourselves. A deployment that
        # does not use it should not expose it.
        from arkhe.api import token

        app.include_router(token.router)
    else:
        # Without the endpoint, it is not advertised either. A client generated from
        # a document that says "get one here" would fetch it and meet a 404.
        #
        # It is removed afterwards because scopes are decided per route while whether
        # to advertise is decided per app. Routes are built at import time, where that
        # condition cannot be seen; see mint.needs().
        _hide_oauth2(app)
    app.include_router(mint.router)
    app.include_router(admin.router)
    return app


def _hide_oauth2(app: FastAPI) -> None:
    """Remove the oauth2 advertisement from the document of a deployment that does not
    offer it."""
    build = app.openapi

    def openapi() -> dict:
        schema = build()
        if schema.get("components", {}).get("securitySchemes", {}).pop("oauth2", None) is None:
            return schema  # already removed; FastAPI caches the result
        for methods in schema.get("paths", {}).values():
            for op in methods.values():
                if not (req := op.get("security")):
                    continue
                op["security"] = [x for x in req if "oauth2" not in x]
                if not op["security"]:
                    del op["security"]
        return schema

    app.openapi = openapi
