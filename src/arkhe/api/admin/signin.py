"""The way in: signing in, the round trip to an authorisation server, signing out, and
the pages that lead back here.

Whichever entrance is used, it ends at the same Principal the API uses. Only how
identity was established differs.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import Form, Request
from fastapi.responses import RedirectResponse

from arkhe.api import i18n
from arkhe.api.admin._common import (
    Config,
    Db,
    router,
    templates,
)
from arkhe.auth import login as login_flow
from arkhe.auth import session as sess
from arkhe.auth.deps import client_ip
from arkhe.auth.errors import AuthError
from arkhe.domain import authz

# ---------------------------------------------------------------- Signing in
#
# What arkhe does here is act as a relying party. Being an authorisation server,
# issuing tokens and holding consent, is a different job, and not one it has.


def _redirect_uri(request: Request) -> str:
    return str(request.url_for("admin_callback"))


def _login_page(request: Request, cfg: Config, *, error: str = "", status: int = 200):
    lang = i18n.pick(request)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "lang": lang,
            "langs": i18n.LANGS,
            "t": i18n.translator(lang),
            "error": error,
            "next_url": request.query_params.get("next", "/admin/"),
        },
        status_code=status,
    )


def _notice(request: Request, cfg, key: str, status: int, retry: str = "/admin/login", **fmt):
    """A page that leads back to signing in, so that nothing is a dead end.

    Whoever sees it is not signed in, so the admin layout (base.html) cannot be used: it
    needs a principal. This shares the frame with the login page.
    """
    lang = i18n.pick(request)
    tr = i18n.translator(lang)
    return templates.TemplateResponse(
        request, "notice.html",
        {"request": request, "lang": lang, "langs": i18n.LANGS, "t": tr,
         "heading": tr(f"notice.{key}.h"), "message": tr(f"notice.{key}.m").format(**fmt),
         "retry_url": retry, "next_url": ""},
        status_code=status,
    )


@router.post("/login", name="admin_login_submit")
def login_submit(
    request: Request,
    session: Db,
    cfg: Config,
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "/admin/",  # noqa: A002
):
    """Check a username and password, and start a session.

    Failures are not broken down by reason. If "no such user" were distinguishable, the
    list of users could be found by trying names.
    """
    if cfg.admin_login != "password":
        return _notice(request, cfg, "nologin", 404, retry="/admin/")
    from arkhe.auth import password as pw

    ip = client_ip(request, cfg)
    try:
        principal = pw.authenticate(session, username, password)
    except AuthError as exc:
        # A failed sign-in is the one worth recording. The username typed is kept;
        # the password is not, and is not in exc.detail either.
        authz.record_sign_in(
            session, action="sign_in", client_id=username[:255], ip=ip,
            mechanism="password", ok=False, reason=str(exc.detail),
        )
        session.commit()  # the failure count, the lock, and the record
        # Show it in the language of the screen. password.py raises with a catalogue
        # key, since that layer knows nothing about the request; anything that is not a
        # key is returned unchanged.
        shown = i18n.translator(i18n.pick(request))(str(exc.detail))
        return _login_page(request, cfg, error=shown, status=401)
    authz.record_sign_in(
        session, action="sign_in", client_id=principal.client_id,
        authority=principal.authority, ip=ip, mechanism="password",
    )
    session.commit()

    # Only our own pages are allowed. An external URL in next would make this a
    # stepping stone that sends people elsewhere right after signing in.
    target = next if next.startswith("/admin") else "/admin/"
    r = RedirectResponse(target, status_code=302)
    sess.set_cookie(
        r,
        sess.issue(principal.client_id, secret=cfg.session_secret, ttl=cfg.session_ttl,
                   extra={"via": "password"}),
        ttl=cfg.session_ttl, secure=cfg.session_secure,
    )
    return r


@router.get("/login", name="admin_login")
def login(request: Request, cfg: Config):
    if cfg.admin_login == "password":
        return _login_page(request, cfg)
    if cfg.admin_login != "oidc":
        return _notice(request, cfg, "nologin", 404, retry="/admin/")
    next_url = request.query_params.get("next", "/admin/")
    url, payload = login_flow.start(cfg, redirect_uri=_redirect_uri(request), next_url=next_url)
    r = RedirectResponse(url, status_code=302)
    # The state and the PKCE verifier are signed and handed over; they only have to
    # survive the round trip.
    r.set_cookie(
        login_flow.FLOW_COOKIE,
        sess.issue("flow", secret=cfg.session_secret, ttl=login_flow.FLOW_TTL,
                   extra={"flow": payload}),
        max_age=login_flow.FLOW_TTL, httponly=True, samesite="lax",
        secure=cfg.session_secure, path="/admin",
    )
    return r


@router.get("/callback", name="admin_callback")
def callback(request: Request, session: Db, cfg: Config):

    raw = request.cookies.get(login_flow.FLOW_COOKIE, "")
    claims = sess.read(raw, secret=cfg.session_secret) if raw else None
    if not claims:
        return _notice(request, cfg, "expired", 400)
    flow = json.loads(claims["flow"])
    # RFC 6749: match the state, so that a response to another request is not taken.
    if request.query_params.get("state") != flow["state"]:
        return _notice(request, cfg, "state", 400)
    if err := request.query_params.get("error"):
        authz.record_sign_in(
            session, action="sign_in", client_id="", ip=client_ip(request, cfg),
            mechanism="oidc-login", ok=False, reason=err[:200],
        )
        session.commit()
        return _notice(request, cfg, "denied", 403, err=err)

    principal = login_flow.finish(
        session, cfg,
        code=request.query_params.get("code", ""),
        verifier=flow["verifier"],
        redirect_uri=_redirect_uri(request),
    )
    authz.record_sign_in(
        session, action="sign_in", client_id=principal.client_id,
        authority=principal.authority, ip=client_ip(request, cfg),
        mechanism="oidc-login",
    )
    session.commit()
    r = RedirectResponse(flow.get("next") or "/admin/", status_code=302)
    sess.set_cookie(
        r,
        sess.issue(principal.client_id, secret=cfg.session_secret, ttl=cfg.session_ttl,
                   extra={"via": "oidc-login"}),
        ttl=cfg.session_ttl, secure=cfg.session_secure,
    )
    r.delete_cookie(login_flow.FLOW_COOKIE, path="/admin")
    return r


@router.post("/logout", name="admin_logout")
def logout(request: Request, session: Db, cfg: Config):
    """Sign out, ending the session at the authorisation server too where one is used.

    POST rather than GET. SameSite=Lax still sends the cookie on a top-level GET, so as
    a GET another site could sign people out with <img src=".../logout">. The harm is
    only nuisance, and so is the cost of preventing it.

    Dropping our cookie is not enough. Opening /admin/ again goes to the authorisation
    server, and with the session there still alive the person comes back without being
    asked anything: from where they stand, signing out does not work.
    """
    # Record who left, as far as the session says; empty when it cannot be read.
    claims = sess.read(request.cookies.get(sess.COOKIE, ""), secret=cfg.session_secret)
    authz.record_sign_in(
        session, action="sign_out", client_id=(claims or {}).get("sub", ""),
        ip=client_ip(request, cfg), mechanism=(claims or {}).get("via", ""),
    )
    session.commit()
    back = str(request.url_for("admin_overview"))
    target = "/admin/"
    if cfg.admin_login == "oidc":
        target = login_flow.end_session_url(cfg, post_logout_redirect=back) or "/admin/"
    r = RedirectResponse(target, status_code=302)
    sess.clear_cookie(r)
    return r
