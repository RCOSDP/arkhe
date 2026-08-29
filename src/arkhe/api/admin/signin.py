"""入り口——ログイン、認可サーバとの往復、ログアウト、そこへ戻す案内。

**どの入口でも、行き着く先は API と同じ `Principal`。** 違うのは
「誰であるかをどう確かめたか」だけ。
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
from arkhe.auth.errors import AuthError

# ------------------------------------------------------------------ ログイン
#
# **ここで arkhe がやるのは「クライアント（RP）になる」こと。** 認可サーバになる
# こと——トークンを発行し、同意を預かる役目——とは別で、そちらは持たない。


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
    """ログインに戻す画面。**行き止まりを作らない。**

    ここは未ログインの人が見る画面なので、管理画面の骨組み（`base.html`）は
    使えない（`principal` が要る）。ログイン画面と同じ外枠を共有する。
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
    """ID とパスワードを確かめてセッションにする。

    **失敗しても理由を分けない。** 「その ID は無い」と分かると、利用者の一覧を
    総当たりで作れてしまう。
    """
    if cfg.admin_login != "password":
        return _notice(request, cfg, "nologin", 404, retry="/admin/")
    from arkhe.auth import password as pw

    try:
        principal = pw.authenticate(session, username, password)
    except AuthError as exc:
        session.commit()  # 失敗回数と施錠を残す
        return _login_page(request, cfg, error=str(exc.detail), status=401)
    session.commit()

    # **入れ先は自分のところに限る。** 外部 URL を next に入れられると、
    # ログイン直後に別サイトへ飛ばす踏み台になる（open redirect）。
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
    # state と PKCE の検証子は**署名して預ける**。往復のあいだだけ持てばよい。
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
    # RFC 6749: **state を突き合わせる**（別の要求への応答を受け取らないため）。
    if request.query_params.get("state") != flow["state"]:
        return _notice(request, cfg, "state", 400)
    if err := request.query_params.get("error"):
        return _notice(request, cfg, "denied", 403, err=err)

    principal = login_flow.finish(
        session, cfg,
        code=request.query_params.get("code", ""),
        verifier=flow["verifier"],
        redirect_uri=_redirect_uri(request),
    )
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
def logout(request: Request, cfg: Config):
    """ログアウト。**外部で認証しているなら、そちらのセッションも終わらせる。**

    GET ではなく POST。`SameSite=Lax` は**トップレベルの GET 遷移では Cookie を
    送る**ので、GET のままだと外部サイトから `<img src=".../logout">` で強制
    ログアウトさせられる。実害は嫌がらせ程度だが、直す手間も同じくらい小さい。

    こちらの Cookie を消すだけでは足りない。次に `/admin/` を開くと認可サーバへ
    送られ、そちらのセッションが生きているので何も訊かれずに戻ってくる——
    利用者から見れば「ログアウトできない」。
    """
    back = str(request.url_for("admin_overview"))
    target = "/admin/"
    if cfg.admin_login == "oidc":
        target = login_flow.end_session_url(cfg, post_logout_redirect=back) or "/admin/"
    r = RedirectResponse(target, status_code=302)
    sess.clear_cookie(r)
    return r
