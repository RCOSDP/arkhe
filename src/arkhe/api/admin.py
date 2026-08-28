"""管理画面。**テーブルの行編集ではなく、操作の画面。**

画面が呼ぶのは `domain.admin_ops` と `domain.minting` で、DB を直接は触らない。
CLI と同じ関数を通るので、画面から不変条件を破る道が生まれない。

見せる範囲は `Principal` の 3 段（system / naan / manager）でそのまま絞る。
**画面の出し分けと実際の認可は同じ判定**を使う——別々にすると、ボタンは出ないが
URL を直接叩けば通る、という穴ができる。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from arkhe.api import i18n
from arkhe.auth import login as login_flow
from arkhe.auth import session as sess
from arkhe.auth.deps import Config, Db, authenticate, bearer
from arkhe.auth.errors import AuthError, Forbidden
from arkhe.auth.principal import Principal
from arkhe.db.models import Ark, AuditEvent, Client, Manager, Naan, Shoulder
from arkhe.domain import authz, minting

# 管理画面は HTML であって API ではない。**OpenAPI には載せない。**
router = APIRouter(prefix="/admin", tags=["admin"], include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _ctx(request: Request, principal: Principal, page: str, **extra) -> dict:
    lang = i18n.pick(request)
    return {
        "request": request,
        "principal": principal,
        "page": page,
        "lang": lang,
        "langs": i18n.LANGS,
        "t": i18n.translator(lang),
        # **画面の出し分けと実際の認可は同じ判定を使う。**
        # 別々にすると「ボタンは出ないが URL を直接叩けば通る」穴ができる。
        "can_manage": principal.is_naan_wide,
        **extra,
    }


def _remember_lang(request: Request, response):
    """`?lang=` での明示の選択を記憶する。以降のページでも保たれる。"""
    q = request.query_params.get("lang")
    if q in i18n.CATALOGS:
        response.set_cookie(i18n.COOKIE, q, max_age=31536000, httponly=True, samesite="lax")
    return response


def _visible_naans(session: Session, p: Principal) -> list[Naan]:
    """その主体に見える NAAN。system は全部、それ以外は自分の 1 つ。"""
    stmt = select(Naan).order_by(Naan.naan)
    if not p.is_system:
        stmt = stmt.where(Naan.naan == p.naan)
    return list(session.scalars(stmt))


def _visible_shoulders(session: Session, p: Principal) -> list[Shoulder]:
    """採番に使える shoulder。**認可と同じ絞り方**にする。"""
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
    """ログインへ送る。**401 を返さない**——ブラウザにヘッダは付けられないので、
    401 を見せても人には何もできない。"""

    def __init__(self, next_url: str = "/admin/"):
        self.next_url = next_url


def admin_principal(request: Request, session: Db, cfg: Config) -> Principal:
    """管理画面の主体。**入口は設定で選ぶ**（`ARKHE_ADMIN_LOGIN`）。

    どの入口でも、行き着く先は API と同じ `Principal`。到達範囲の判定も同じ。
    違うのは「誰であるかをどう確かめたか」だけ。
    """
    # 1) セッション Cookie（oidc / proxy でログイン済み）
    if cfg.admin_login != "bearer":
        raw = request.cookies.get(sess.COOKIE, "")
        claims = sess.read(raw, secret=cfg.session_secret) if raw else None
        if claims:
            try:
                return login_flow.by_subject(
                    session, claims["sub"], mechanism=claims.get("via", "")
                )
            except AuthError:
                pass  # 登録が消えた・無効化された。ログインし直させる

    # 2) 前段の認証プロキシ
    if cfg.admin_login == "proxy":
        try:
            return login_flow.from_proxy(session, cfg, request.headers)
        except AuthError as exc:
            raise NeedsLogin() from exc

    # 3) Bearer（自動化・curl。bearer モードではこれだけ）
    try:
        return authenticate(bearer(request), session, cfg)
    except AuthError:
        if cfg.admin_login in ("oidc", "password"):
            raise NeedsLogin(str(request.url.path)) from None
        raise


AdminPrincipal = Annotated[Principal, Depends(admin_principal)]


class _ShoulderChoice:
    """採番フォームの選択肢。テンプレートに ORM を直接渡さないための薄い型。"""

    def __init__(self, s: Shoulder):
        self.naan = s.naan
        self.shoulder = s.shoulder
        self.manager_name = s.manager.name if s.manager else ""


def _mintable(session: Session, p: Principal) -> list[_ShoulderChoice]:
    return [_ShoulderChoice(s) for s in _visible_shoulders(session, p) if s.can_mint_here]


# ------------------------------------------------------------------ 委譲の構造


@router.get("/", response_class=HTMLResponse)
def overview(request: Request, principal: AdminPrincipal, session: Db):
    naans = _visible_naans(session, principal)
    for n in naans:
        # **リレーション名（`n.managers`）には代入しない。** 代入すると SQLAlchemy は
        # 「この Naan の子はこれで全部」と解釈し、**一覧から外した機関の naan を
        # NULL に更新する**。表示のための絞り込みがデータを壊す。別名に持つ。
        stmt = (
            select(Manager)
            .where(Manager.naan == n.naan)
            .options(selectinload(Manager.shoulders))
            .order_by(Manager.name)
        )
        if not principal.is_naan_wide:
            stmt = stmt.where(Manager.id == principal.manager_id)
        n.visible_managers = list(session.scalars(stmt))
        n.visible_orphans = (
            list(
                session.scalars(
                    select(Shoulder)
                    .where(Shoulder.naan == n.naan, Shoulder.manager_id.is_(None))
                    .order_by(Shoulder.shoulder)
                )
            )
            if principal.is_naan_wide
            else []
        )

    counts = dict(
        session.execute(
            select(Ark.shoulder_id, func.count()).group_by(Ark.shoulder_id)
        ).all()
    )
    return _remember_lang(
        request,
        templates.TemplateResponse(
            request,
            "overview.html", _ctx(request, principal, "overview", naans=naans, counts=counts)
        ),
    )


# ------------------------------------------------------------------ 採番


@router.get("/mint", response_class=HTMLResponse)
def mint_form(request: Request, principal: AdminPrincipal, session: Db):
    authz.require_scope(principal, "ark:mint")
    return _remember_lang(
        request,
        templates.TemplateResponse(
            request,
            "mint.html",
            _ctx(
                request,
                principal,
                "mint",
                shoulders=_mintable(session, principal),
                # NAAN 単位以上は shoulder の明示が必須（既定を持たない）。
                needs_shoulder=principal.is_naan_wide,
                minted=None,
            ),
        ),
    )


@router.post("/mint", response_class=HTMLResponse)
def mint_submit(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    shoulder: Annotated[str, Form()] = "",
    url: Annotated[str, Form()] = "",
    title: Annotated[str, Form()] = "",
    type: Annotated[str, Form()] = "",  # noqa: A002 - ERC の項目名
    who: Annotated[str, Form()] = "",
    when: Annotated[str, Form()] = "",
):
    """画面からの採番。**API と同じ経路**（authz → minting）を通る。"""
    authz.require_scope(principal, "ark:mint")
    sh = authz.shoulder_for(session, principal, shoulder or None)
    authz.assert_shoulder_mintable(sh)
    authz.assert_within_quota(session, principal)
    ark, _ = minting.mint(
        session,
        shoulder=sh,
        created_by=principal.client_id,
        url=url,
        title=title,
        type=type,
        who=who,
        when=when,
    )
    authz.audit(session, principal, "mint", ark.ark, via="admin-ui")
    session.commit()

    return _remember_lang(
        request,
        templates.TemplateResponse(
            request,
            "mint.html",
            _ctx(
                request,
                principal,
                "mint",
                shoulders=_mintable(session, principal),
                needs_shoulder=principal.is_naan_wide,
                minted=ark,
                flash=f"ark:/{ark.ark} "
                + i18n.translator(i18n.pick(request))("mint.flash"),
            ),
        ),
    )


# ------------------------------------------------------------------ 主体


@router.get("/clients", response_class=HTMLResponse)
def clients(request: Request, principal: AdminPrincipal, session: Db):
    stmt = select(Client).options(
        selectinload(Client.credentials),
        selectinload(Client.manager),
        selectinload(Client.shoulder),
    ).order_by(Client.client_id)
    if not principal.is_system:
        stmt = stmt.where(Client.naan == principal.naan)
    if not principal.is_naan_wide:
        stmt = stmt.where(Client.manager_id == principal.manager_id)
    rows = list(session.scalars(stmt))
    for c in rows:
        c.live_credentials = sum(1 for x in c.credentials if x.active)
        c.dead_credentials = sum(1 for x in c.credentials if not x.active)
        if c.shoulder is not None:
            c.scope_label = f"{c.naan}{c.shoulder.shoulder}"
        elif c.manager is not None:
            c.scope_label = f"{c.naan} · {c.manager.name}"
        else:
            c.scope_label = c.naan or "全 NAAN"
    return _remember_lang(
        request,
        templates.TemplateResponse(
            request,
            "clients.html", _ctx(request, principal, "clients", clients=rows, issued=None)
        ),
    )


# ------------------------------------------------------------------ 監査


@router.get("/audit", response_class=HTMLResponse)
def audit(request: Request, principal: AdminPrincipal, session: Db):
    """**監査ログは NAAN 単位以上にしか見せない。**

    誰がいつ何をしたかは、その名前空間を預かる側の情報。機関の担当者に他機関の
    操作履歴が見えてはならない。
    """
    if not principal.is_naan_wide:
        raise Forbidden("監査ログの閲覧は NAAN 単位以上の権限が要る")
    stmt = select(AuditEvent).order_by(AuditEvent.at.desc()).limit(200)
    events = list(session.scalars(stmt))
    for e in events:
        e.detail_text = json.dumps(e.detail, ensure_ascii=False) if e.detail else ""
    return _remember_lang(
        request,
        templates.TemplateResponse(
            request,
            "audit.html", _ctx(request, principal, "audit", events=events)),
    )


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
        return PlainTextResponse("この構成にログイン画面はありません", status_code=404)
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
        return PlainTextResponse(
            "この構成にログイン画面はありません（ARKHE_ADMIN_LOGIN を確認してください）",
            status_code=404,
        )
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
    import json

    raw = request.cookies.get(login_flow.FLOW_COOKIE, "")
    claims = sess.read(raw, secret=cfg.session_secret) if raw else None
    if not claims:
        return PlainTextResponse(
            "ログインの往復が失効しました。やり直してください", status_code=400
        )
    flow = json.loads(claims["flow"])
    # RFC 6749: **state を突き合わせる**（別の要求への応答を受け取らないため）。
    if request.query_params.get("state") != flow["state"]:
        return PlainTextResponse("state が一致しません", status_code=400)
    if err := request.query_params.get("error"):
        return PlainTextResponse(f"認可サーバが拒否しました: {err}", status_code=403)

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


@router.get("/logout", name="admin_logout")
def logout(cfg: Config):
    r = RedirectResponse("/admin/", status_code=302)
    sess.clear_cookie(r)
    return r
