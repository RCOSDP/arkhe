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
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from arkhe.api import i18n
from arkhe.auth import login as login_flow
from arkhe.auth import session as sess
from arkhe.auth.deps import Config, Db, authenticate, bearer
from arkhe.auth.errors import AuthError, Forbidden
from arkhe.auth.principal import Principal
from arkhe.db.models import (
    Ark,
    AuditEvent,
    Client,
    CommitmentLevel,
    Manager,
    Naan,
    Shoulder,
    ShoulderStatus,
)
from arkhe.domain import admin_ops as ops
from arkhe.domain import authz, minting

# 管理画面は HTML であって API ではない。**OpenAPI には載せない。**
router = APIRouter(prefix="/admin", tags=["admin"], include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _can_add_client(p: Principal) -> bool:
    """利用者を作れるか。組織単位でも自組織なら作れる（`register_client` の判定）。"""
    return p.is_naan_wide or p.manager_id is not None


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
        # 逆に、**押しても断られるだけのボタンも出さない**——押せるものだけを
        # 見せるのが、到達範囲を画面で表すということ。
        "can_manage": principal.is_naan_wide,
        "can_audit": principal.is_naan_wide,
        "can_mint": principal.has("ark:mint"),
        "can_add_client": _can_add_client(principal),
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


@router.get("/", response_class=HTMLResponse, name="admin_overview")
def overview(request: Request, principal: AdminPrincipal, session: Db):
    naans = _visible_naans(session, principal)
    for n in naans:
        # **リレーション名（`n.managers`）には代入しない。** 代入すると SQLAlchemy は
        # 「この Naan の子はこれで全部」と解釈し、**一覧から外した組織の naan を
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


# --------------------------------------------------------- 台帳を組む操作
#
# **画面から編集できるのは、宣言と運用の設定だけ。** ARK の行も shoulder の
# 綴りも、画面からは変えられない——変えられてしまうと、`NR` を宣言している
# はずの体系で名前が振り直せることになる。
#
# 誰が何を変えられるかは `domain.admin_ops` の判定をそのまま使う。ここで
# 別の判定を書くと、ボタンは出ないが POST は通る、という穴になる。


def _redirect(to: str) -> RedirectResponse:
    """POST の後は 303 で GET に戻す（再読み込みで二重に実行させない）。"""
    return RedirectResponse(to, status_code=303)


def _page(request: Request, principal: Principal, template: str, page: str, **extra):
    return _remember_lang(
        request,
        templates.TemplateResponse(request, template, _ctx(request, principal, page, **extra)),
    )


@router.get("/naan/new", response_class=HTMLResponse)
def naan_new(request: Request, principal: AdminPrincipal):
    if not principal.is_system:
        raise Forbidden("NAAN の登録はシステム管理者のみ")
    return _page(request, principal, "naan_form.html", "overview", naan=None)


@router.post("/naan/new")
def naan_create(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    naan: Annotated[str, Form()],
    name: Annotated[str, Form()],
    policy: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    authoritative: Annotated[str, Form()] = "",
    redirect: Annotated[str, Form()] = "",
):
    ops.create_naan(
        session, principal, naan=naan.strip(), name=name.strip(), na_policy=policy.strip(),
        description=description.strip(),
        is_authoritative=bool(authoritative), redirect=redirect.strip(),
    )
    session.commit()
    return _redirect(f"/admin/naan/{naan.strip()}")


@router.get("/naan/{naan}", response_class=HTMLResponse)
def naan_edit(request: Request, principal: AdminPrincipal, session: Db, naan: str):
    obj = session.get(Naan, naan)
    # **開ける条件と保存できる条件を揃える。** `reaches_naan` だけだと組織管理者にも
    # 開けてしまい、編集できるように見えるフォームが保存で 403 になる。
    # 出し分けと認可がずれているのと同じことなので、ここで揃える。
    if obj is None or not principal.is_naan_wide or not principal.reaches_naan(naan):
        raise Forbidden(f"NAAN {naan} はこの主体の範囲外")
    return _page(request, principal, "naan_form.html", "overview", naan=obj)


@router.post("/naan/{naan}")
def naan_save(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    naan: str,
    policy: Annotated[str, Form()] = "",
    minter: Annotated[str, Form()] = "",
):
    """**NAA ポリシーは名前空間を配る側の宣言。** NAAN 単位以上でしか変えられない。"""
    ops.set_na_policy(session, principal, naan=naan, policy=policy.strip())
    obj = session.get(Naan, naan)
    if minter.strip() != obj.minter:
        if not principal.is_system:
            raise Forbidden("採番の案内先の変更はシステム管理者のみ")
        obj.minter = minter.strip()
        authz.audit(session, principal, "set_minter", naan, minter=obj.minter)
    session.commit()
    return _redirect(f"/admin/naan/{naan}?saved=1")


@router.get("/manager/new", response_class=HTMLResponse)
def manager_new(request: Request, principal: AdminPrincipal, session: Db):
    if not principal.is_naan_wide:
        raise Forbidden("組織のオンボードは NAAN 単位以上の権限が要る")
    return _page(
        request, principal, "manager_form.html", "overview",
        manager=None, naans=_visible_naans(session, principal), levels=list(CommitmentLevel),
    )


@router.post("/manager/new")
def manager_create(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    naan: Annotated[str, Form()],
    name: Annotated[str, Form()],
    shoulder: Annotated[str, Form()],
    commitment: Annotated[str, Form()] = "",
    quota: Annotated[str, Form()] = "",
):
    m, _ = ops.onboard_manager(
        session, principal, naan=naan, name=name.strip(), shoulder=shoulder.strip(),
        commitment_level=commitment,
        quota_per_day=int(quota) if quota.strip() else None,
    )
    session.commit()
    return _redirect(f"/admin/manager/{m.id}")


@router.get("/manager/{manager_id}", response_class=HTMLResponse)
def manager_edit(request: Request, principal: AdminPrincipal, session: Db, manager_id: int):
    m = session.get(Manager, manager_id)
    if m is None:
        raise Forbidden("この組織はこの主体の範囲外")
    ops.require_manager(session, principal, m)
    return _page(
        request, principal, "manager_form.html", "overview",
        manager=m, naans=[], levels=list(CommitmentLevel),
    )


@router.post("/manager/{manager_id}")
def manager_save(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    manager_id: int,
    commitment: Annotated[str, Form()] = "",
    quota: Annotated[str, Form()] = "",
):
    """**約束は組織自身のもの**なので、組織管理者も自組織の水準を変えられる。

    採番上限はそうではない（配った側が課すもの）。判定は `admin_ops` 側にある。
    """
    if commitment:
        ops.set_commitment(session, principal, manager_id=manager_id, level=commitment)
    if principal.is_naan_wide:
        ops.set_quota(
            session, principal, manager_id=manager_id,
            quota_per_day=int(quota) if quota.strip() else None,
        )
    session.commit()
    return _redirect(f"/admin/manager/{manager_id}?saved=1")


@router.get("/shoulder/new", response_class=HTMLResponse)
def shoulder_new(request: Request, principal: AdminPrincipal, session: Db):
    if not principal.is_naan_wide:
        raise Forbidden("shoulder の切り出しは NAAN 単位以上の権限が要る")
    return _page(
        request, principal, "shoulder_form.html", "overview",
        shoulder=None, naans=_visible_naans(session, principal),
        statuses=list(ShoulderStatus),
    )


@router.post("/shoulder/new")
def shoulder_create(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    naan: Annotated[str, Form()],
    shoulder: Annotated[str, Form()],
    manager_id: Annotated[str, Form()] = "",
    reserve: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
):
    sh = ops.add_shoulder(
        session, principal, naan=naan, shoulder=shoulder.strip(),
        manager_id=int(manager_id) if manager_id.strip() else None,
        status="reserved" if reserve else "active", note=note.strip(),
    )
    session.commit()
    return _redirect(f"/admin/shoulder/{sh.id}")


@router.get("/shoulder/{shoulder_id}", response_class=HTMLResponse)
def shoulder_edit(request: Request, principal: AdminPrincipal, session: Db, shoulder_id: int):
    sh = session.get(Shoulder, shoulder_id)
    if sh is None or not principal.reaches_naan(sh.naan):
        raise Forbidden("この shoulder はこの主体の範囲外")
    return _page(
        request, principal, "shoulder_form.html", "overview",
        shoulder=sh, naans=[], statuses=list(ShoulderStatus),
    )


@router.post("/shoulder/{shoulder_id}")
def shoulder_save(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    shoulder_id: int,
    status: Annotated[str, Form()] = "",
    minter: Annotated[str, Form()] = "",
    redirect: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
):
    """**retired からは戻せない。** その判定は `admin_ops` 側が持っている。"""
    sh = session.get(Shoulder, shoulder_id)
    if sh is None:
        raise Forbidden("この shoulder はこの主体の範囲外")
    if status and status != sh.status:
        ops.set_shoulder_status(
            session, principal, shoulder_id=shoulder_id, status=status,
            minter=minter.strip(), note=note.strip(),
        )
    if redirect.strip() != sh.redirect:
        ops.set_shoulder_redirect(
            session, principal, shoulder_id=shoulder_id, redirect=redirect.strip()
        )
    session.commit()
    return _redirect(f"/admin/shoulder/{shoulder_id}?saved=1")


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


# ------------------------------------------------------- 利用者と資格情報
#
# **平文の資格情報はここでしか手に入らない。** 発行の直後に一度だけ返し、
# 保存しているのはハッシュだけ。画面を再読み込みしても出てこない——だから
# 発行は POST で受け、そのレスポンスに載せる（リダイレクトすると消える）。


def _reachable_client(session: Session, principal: Principal, client_id: int) -> Client:
    """届く範囲の利用者だけを返す。判定は `admin_ops` と同じものを使う。"""
    c = session.get(Client, client_id)
    if c is None:
        raise Forbidden("この利用者はこの主体の範囲外")
    if not principal.reaches_naan(c.naan):
        raise Forbidden("この利用者はこの主体の範囲外")
    if not principal.is_naan_wide and c.manager_id != principal.manager_id:
        raise Forbidden("この利用者はこの主体の範囲外")
    return c


def _client_page(request: Request, principal: Principal, session: Db, c: Client | None, **extra):
    managers = []
    if principal.is_naan_wide:
        stmt = select(Manager).where(Manager.active.is_(True)).order_by(Manager.naan, Manager.name)
        if not principal.is_system:
            stmt = stmt.where(Manager.naan == principal.naan)
        managers = list(session.scalars(stmt))
    # **`_mintable` は表示用で id を持たない。** 紐づけには実体が要る。
    shoulders = _visible_shoulders(session, principal) if c is None else []
    return _page(
        request, principal, "client_form.html", "clients",
        client=c, managers=managers, shoulders=shoulders,
        creds=sorted(c.credentials, key=lambda x: x.id, reverse=True) if c else [],
        **extra,
    )


@router.get("/client/new", response_class=HTMLResponse)
def client_new(request: Request, principal: AdminPrincipal, session: Db):
    # 出し分けと同じ述語で閉じる（`_ctx` の `can_add_client` と同じもの）。
    if not _can_add_client(principal):
        raise Forbidden("この主体は利用者を登録できない")
    return _client_page(request, principal, session, None)


@router.post("/client/new")
def client_create(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    client_id: Annotated[str, Form()],
    naan: Annotated[str, Form()] = "",
    manager_id: Annotated[str, Form()] = "",
    shoulder_id: Annotated[str, Form()] = "",
    scopes: Annotated[str, Form()] = "ark:mint",
    label: Annotated[str, Form()] = "",
    person: Annotated[str, Form()] = "",
):
    """利用者を登録する。**資格情報はここでは出さない。**

    登録と鍵の発行を分けているのは、`--person` の主体には鍵を出さないから。
    まず何者かを決め、機械であれば次の画面で鍵を出す。
    """
    c = ops.register_client(
        session, principal, client_id=client_id.strip(),
        naan=naan or principal.naan,
        # **自組織以外は選ばせない。** 選択肢を出していないので、値が来ても使わない。
        manager_id=(
            int(manager_id) if principal.is_naan_wide and manager_id.strip()
            else principal.manager_id
        ),
        shoulder_id=int(shoulder_id) if shoulder_id.strip() else None,
        scopes=scopes.strip() or "ark:mint", label=label.strip(),
        subject_type="person" if person else "machine",
    )
    session.commit()
    return _redirect(f"/admin/client/{c.id}")


@router.get("/client/{client_id}", response_class=HTMLResponse)
def client_detail(request: Request, principal: AdminPrincipal, session: Db, client_id: int):
    c = _reachable_client(session, principal, client_id)
    return _client_page(request, principal, session, c)


@router.post("/client/{client_id}/key", response_class=HTMLResponse)
def client_issue_key(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    client_id: int,
    kind: Annotated[str, Form()] = "api_key",
    label: Annotated[str, Form()] = "",
):
    """資格情報を発行する。**平文はこの応答にしか載らない。**

    リダイレクトで一覧に戻さないのはそのため——戻した先では、もう取り出せない。
    """
    c = _reachable_client(session, principal, client_id)
    issued = ops.issue_credential(
        session, principal, client_pk=c.id, kind=kind, label=label.strip()
    )
    secret = issued.secret
    session.commit()
    session.refresh(c)
    return _client_page(request, principal, session, c, issued=secret)


@router.post("/client/{client_id}/revoke")
def client_revoke_key(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    client_id: int,
    credential_id: Annotated[int, Form()],
):
    """**行は消さない。** いつ失効したかが残る。"""
    _reachable_client(session, principal, client_id)
    ops.revoke_credential(session, principal, credential_id=credential_id)
    session.commit()
    return _redirect(f"/admin/client/{client_id}?saved=1")


@router.post("/client/{client_id}/password")
def client_set_password(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    client_id: int,
    password: Annotated[str, Form()],
):
    """人の主体にパスワードを設定する（`ARKHE_ADMIN_LOGIN=password` の構成用）。"""
    c = _reachable_client(session, principal, client_id)
    ops.set_password(session, principal, client_pk=c.id, password=password)
    session.commit()
    return _redirect(f"/admin/client/{client_id}?saved=1")


# ------------------------------------------------------------------ 監査


@router.get("/audit", response_class=HTMLResponse)
def audit(request: Request, principal: AdminPrincipal, session: Db):
    """**監査ログは NAAN 単位以上にしか見せない。**

    誰がいつ何をしたかは、その名前空間を預かる側の情報。組織の担当者に他組織の
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
    import json

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


@router.get("/logout", name="admin_logout")
def logout(request: Request, cfg: Config):
    """ログアウト。**外部で認証しているなら、そちらのセッションも終わらせる。**

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
