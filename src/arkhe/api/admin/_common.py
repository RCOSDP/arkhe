"""What the admin screens share: the router, the templates, resolving the principal,
and the predicates that decide what is shown.

The per-screen modules look only at this. Spreading those decisions across the screens
leads to one of two things: a button that is hidden while the URL still works, or a
button that only refuses when pressed.

This was one file of 1,100 lines. Authentication, authorisation, the screens and form
handling lived together and it was impossible to see what a change would affect, so it
was split along the boundaries the comments already marked. The lines moved; nothing
else changed.

The screens call domain.admin_ops and domain.minting rather than touching the database,
so they go through the same functions as the CLI and cannot break an invariant.

What is shown is narrowed by the principal's tier, system, naan or manager. Display and
authorisation use the same decision: kept apart, a button would be hidden while the URL
still works.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from arkhe.api import i18n
from arkhe.auth import login as login_flow
from arkhe.auth import session as sess
from arkhe.auth.deps import Config, Db, authenticate, bearer
from arkhe.auth.errors import AuthError, Forbidden
from arkhe.auth.principal import Principal
from arkhe.db.models import (
    Client,
    CredentialKind,
    Manager,
    Naan,
    Shoulder,
    Subject,
)

# These screens are HTML, not an API, so they are left out of the OpenAPI document.
#: Rows per page. The total is not counted: ARKs only accumulate and counting them on
#: every request costs. Whether there is a next page is decided by fetching one extra.
PAGE = 50


router = APIRouter(prefix="/admin", tags=["admin"], include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _issuable_kinds(cfg) -> list[str]:
    """The kinds of credential this deployment can actually use.

    Without the mechanism enabled, a credential issued here would work nowhere:
    auth.deps.authenticate only tries what ARKHE_AUTH lists. Offering one that cannot be
    used is a button that does nothing.

      apikey in auth  an API key, sent as a bearer token
      oauth2 in auth  a client secret, exchanged at arkhe's own /oauth/token
      oidc alone      neither. The secret is held by the authorisation server, and
                      arkhe holds only the client_id and what it reaches
    """
    kinds = []
    if "apikey" in cfg.auth:
        kinds.append(CredentialKind.API_KEY.value)
    if "oauth2" in cfg.auth:
        kinds.append(CredentialKind.CLIENT_SECRET.value)
    return kinds


def _entry_route(client: Client, cfg) -> str:
    """How this principal gets in.

    With oidc alone, machines hold no credential either. Reporting "0 credentials" made
    a correctly configured principal look unfinished, so this answers whether it can get
    in rather than how many credentials it holds.

    A mechanism is not attached to a principal. Any live mechanism that can present this
    client_id works, so how a principal gets in follows from both what it holds and how
    the deployment is configured. Storing it in the ledger would not be used for
    authentication and would only drift from reality.
    """
    if client.subject_type != Subject.MACHINE:
        return "person"                       # external sign-in or a password
    # A credential for a disabled mechanism does not count. It would not work, so
    # saying it is there would be untrue; an old API key left in an oidc-only
    # deployment is exactly that.
    usable = set(_issuable_kinds(cfg))
    if any(c.active and c.kind in usable for c in client.credentials):
        return "key"                          # a credential arkhe issued
    if "oidc" in cfg.auth:
        return "idp"                          # a token from the authorisation server
    return "none"                             # genuinely unconfigured


def _can_add_client(p: Principal) -> bool:
    """Whether a principal may be created within reach. An organisation may create its
    own."""
    return p.is_naan_wide or p.manager_id is not None


def _may_register(session: Session, p: Principal) -> bool:
    """Whether it can actually be registered. Not if whoever hands out the namespace
    turned self-registration off.

    The default in _ctx looks only at reach, so the organisation's settings are applied
    here: the same conditions register_client refuses on are used to decide what the
    screen shows.
    """
    if not _can_add_client(p):
        return False
    if p.is_naan_wide:
        return True
    m = session.get(Manager, p.manager_id) if p.manager_id else None
    return m is None or m.may_self_register


def _ctx(request: Request, principal: Principal, page: str, **extra) -> dict:
    lang = i18n.pick(request)
    return {
        "request": request,
        "principal": principal,
        "page": page,
        "lang": lang,
        "langs": i18n.LANGS,
        "t": i18n.translator(lang),
        # Display and authorisation use one decision. Kept apart, a button would be
        # hidden while the URL still worked. Equally, nothing is shown that only
        # refuses when pressed: showing what can be used is how reach appears on a
        # screen.
        "can_manage": principal.is_naan_wide,
        "can_audit": principal.is_naan_wide,
        "can_mint": principal.has("ark:mint"),
        "can_add_client": _can_add_client(principal),
        **extra,
    }


def _refuse(request: Request, key: str) -> Forbidden:
    """Return a refusal in the language of the screen.

    The screens switch on ?lang=, the cookie and Accept-Language, while the refusals
    used to be written inline in one language: the reader was dropped out of their own
    language exactly when they were stuck. The wording comes from the same catalogue as
    the screens, so a gap fails at startup.
    """
    return Forbidden(i18n.translator(i18n.pick(request))(key))


def _remember_lang(request: Request, response):
    """Remember an explicit ?lang= choice, so that it holds on later pages."""
    q = request.query_params.get("lang")
    if q in i18n.CATALOGS:
        response.set_cookie(i18n.COOKIE, q, max_age=31536000, httponly=True, samesite="lax")
    return response


def _visible_naans(session: Session, p: Principal) -> list[Naan]:
    """The NAANs this principal can see: all of them for the system administrator, its
    own otherwise."""
    stmt = select(Naan).order_by(Naan.naan)
    if not p.is_system:
        stmt = stmt.where(Naan.naan == p.naan)
    return list(session.scalars(stmt))


def _visible_shoulders(session: Session, p: Principal) -> list[Shoulder]:
    """The shoulders that can be minted into, narrowed as authorisation narrows
    them."""
    stmt = select(Shoulder).options(selectinload(Shoulder.manager)).order_by(
        Shoulder.naan, Shoulder.shoulder
    )
    if not p.is_system:
        stmt = stmt.where(Shoulder.naan == p.naan)
    if not p.is_naan_wide:
        if p.shoulder_id is not None:
            stmt = stmt.where(Shoulder.id == p.shoulder_id)
        else:
            stmt = stmt.where(Shoulder.manager_id == p.manager_id)
    return list(session.scalars(stmt))


class NeedsLogin(Exception):
    """Send them to sign in. Not a 401: a browser cannot add the header, so a 401
    leaves the person with nothing to do."""

    def __init__(self, next_url: str = "/admin/"):
        self.next_url = next_url


def _with_ip(request: Request, cfg: Config, p: Principal) -> Principal:
    """Record the caller's address, using the same decision as the API
    (deps.client_ip)."""
    from dataclasses import replace

    from arkhe.auth.deps import client_ip

    return replace(p, ip=client_ip(request, cfg))


def admin_principal(request: Request, session: Db, cfg: Config) -> Principal:
    """The principal for the admin screens. The entrance is chosen by configuration
    (ARKHE_ADMIN_LOGIN).

    Whichever entrance is used, it ends at the same Principal the API uses, with the
    same reach. Only how identity was established differs.
    """
    # 1) The session cookie, for someone already signed in through oidc or proxy
    if cfg.admin_login != "bearer":
        raw = request.cookies.get(sess.COOKIE, "")
        claims = sess.read(raw, secret=cfg.session_secret) if raw else None
        if claims:
            try:
                return _with_ip(request, cfg, login_flow.by_subject(
                    session, claims["sub"], mechanism=claims.get("via", "")
                ))
            except AuthError:
                pass  # the registration is gone or disabled; sign in again

    # 2) An authenticating proxy in front
    if cfg.admin_login == "proxy":
        try:
            return _with_ip(request, cfg, login_flow.from_proxy(session, cfg, request.headers))
        except AuthError as exc:
            raise NeedsLogin() from exc

    # 3) A bearer token, for automation and curl; the only way in bearer mode
    try:
        return _with_ip(request, cfg, authenticate(bearer(request), session, cfg))
    except AuthError:
        if cfg.admin_login in ("oidc", "password"):
            raise NeedsLogin(str(request.url.path)) from None
        raise


AdminPrincipal = Annotated[Principal, Depends(admin_principal)]


class _ShoulderChoice:
    """A choice on the minting form: a thin type, so no ORM object reaches a
    template."""

    def __init__(self, s: Shoulder):
        self.naan = s.naan
        self.shoulder = s.shoulder
        self.manager_name = s.manager.name if s.manager else ""


#: Suggested values for the type field on the minting form, taken from DataCite's
#: resourceTypeGeneral: a vocabulary this field already uses, rather than one invented
#: here. They are suggestions, not a restriction: the ERC what element defines no
#: vocabulary, so anything outside the list can be typed in.
RESOURCE_TYPES = (
    "Audiovisual", "Award", "Book", "BookChapter", "Collection",
    "ComputationalNotebook", "ConferencePaper", "ConferenceProceeding", "DataPaper",
    "Dataset", "Dissertation", "Event", "Image", "Instrument", "InteractiveResource",
    "Journal", "JournalArticle", "Model", "OutputManagementPlan", "PeerReview",
    "PhysicalObject", "Preprint", "Project", "Report", "Service", "Software", "Sound",
    "Standard", "StudyRegistration", "Text", "Workflow", "Other",
)


def _mintable(session: Session, p: Principal) -> list[_ShoulderChoice]:
    return [_ShoulderChoice(s) for s in _visible_shoulders(session, p) if s.can_mint_here]


def _redirect(to: str) -> RedirectResponse:
    """After a POST, return to a GET with 303, so that reloading does not repeat
    it."""
    return RedirectResponse(to, status_code=303)


def _page(request: Request, principal: Principal, template: str, page: str, **extra):
    return _remember_lang(
        request,
        templates.TemplateResponse(request, template, _ctx(request, principal, page, **extra)),
    )
