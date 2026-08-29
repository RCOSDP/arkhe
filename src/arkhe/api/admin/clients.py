"""利用者と鍵。

**平文の資格情報はここでしか手に入らない。** 発行の直後に一度だけ返し、
保存しているのはハッシュだけ。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from arkhe.api.admin._common import (
    PAGE,
    AdminPrincipal,
    Config,
    Db,
    _ctx,
    _entry_route,
    _issuable_kinds,
    _may_register,
    _page,
    _redirect,
    _remember_lang,
    _visible_shoulders,
    router,
    templates,
)
from arkhe.auth.errors import Forbidden
from arkhe.auth.principal import Principal
from arkhe.db.models import (
    Client,
    Manager,
    UnknownSubject,
)
from arkhe.domain import admin_ops as ops
from arkhe.domain import authz

# ------------------------------------------------------------------ 主体


def _unknown_subjects(session: Session, principal: Principal) -> list[UnknownSubject]:
    """登録の無いまま来た主体。**登録が済んだものは出さない。**

    照合はここで毎回やる。登録のたびに行を消して回る処理を持たないので、
    **消し忘れが原因でいつまでも残る**ということが起きない。

    見せるのは NAAN 以上に届く主体だけ。トークンからは**どの組織のものか
    分からず**、推測もしないので、組織単位の管理者に見せると他組織の
    client_id が混ざって出てしまう。
    """
    if not principal.is_naan_wide:
        return []
    registered = select(Client.client_id)
    return list(
        session.scalars(
            select(UnknownSubject)
            .where(UnknownSubject.subject.not_in(registered))
            .order_by(UnknownSubject.last_seen.desc())
            .limit(20)
        )
    )


@router.get("/clients", response_class=HTMLResponse)
def clients(
    request: Request, principal: AdminPrincipal, session: Db, cfg: Config,
    q: str = "", page: int = 1,
):
    stmt = select(Client).options(
        selectinload(Client.credentials),
        selectinload(Client.manager),
        selectinload(Client.shoulder),
    ).order_by(Client.client_id)
    if not principal.is_system:
        stmt = stmt.where(Client.naan == principal.naan)
    if not principal.is_naan_wide:
        stmt = stmt.where(Client.manager_id == principal.manager_id)
    term = q.strip()
    if term:
        stmt = stmt.where(Client.client_id.ilike(f"%{term}%") | Client.label.ilike(f"%{term}%"))
    page = max(1, page)
    rows = list(session.scalars(stmt.offset((page - 1) * PAGE).limit(PAGE + 1)))
    more = len(rows) > PAGE
    rows = rows[:PAGE]
    for c in rows:
        c.live_credentials = sum(1 for x in c.credentials if x.active)
        c.dead_credentials = sum(1 for x in c.credentials if not x.active)
        c.entry = _entry_route(c, cfg)
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
            "clients.html",
            _ctx(request, principal, "clients", clients=rows, issued=None,
                 q=term, page_no=page, more=more,
                 can_add_client=_may_register(session, principal),
                 unknown=_unknown_subjects(session, principal)),
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


def _client_page(request: Request, principal: Principal, session: Db, cfg,
                 c: Client | None, prefill: str = "", **extra):
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
        scopes=authz.SCOPES,
        kinds=_issuable_kinds(cfg), uses_oidc="oidc" in cfg.auth,
        entry=_entry_route(c, cfg) if c else "",
        prefill=prefill,
        # 選べないなら**なぜ選べないか**まで出す（空欄を見せて終わらせない）。
        missing_mech=("oauth2" if "apikey" in cfg.auth else "apikey")
        if len(_issuable_kinds(cfg)) == 1 else "",
        # **どこへ行けばよいかまで見せる。** 「認可サーバで作れ」だけでは、
        # どの認可サーバのことか画面から分からない。
        issuer=cfg.oidc_issuer,
        **extra,
    )


@router.get("/client/new", response_class=HTMLResponse)
def client_new(
    request: Request, principal: AdminPrincipal, session: Db, cfg: Config,
    client_id: str = "",
):
    # 出し分けと同じ述語で閉じる。
    if not _may_register(session, principal):
        raise Forbidden("この主体は利用者を登録できない")
    # **未登録の一覧から渡ってきた識別子を初期値にする。** 認可サーバが署名した
    # 値そのものなので、打ち直させると綴り違いを作る機会をわざわざ増やすことになる。
    return _client_page(request, principal, session, cfg, None, prefill=client_id.strip())


@router.post("/client/new")
def client_create(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    client_id: Annotated[str, Form()],
    naan: Annotated[str, Form()] = "",
    manager_id: Annotated[str, Form()] = "",
    shoulder_id: Annotated[str, Form()] = "",
    scopes: Annotated[list[str], Form()] = None,
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
        # **語彙の外は捨てる。** 画面に出していない値が送られてきても使わない。
        scopes=" ".join(x for x in (scopes or []) if x in authz.SCOPES) or "ark:mint",
        label=label.strip(),
        subject_type="person" if person else "machine",
    )
    session.commit()
    return _redirect(f"/admin/client/{c.id}")


@router.get("/client/{client_id}", response_class=HTMLResponse)
def client_detail(request: Request, principal: AdminPrincipal, session: Db, cfg: Config,
                  client_id: int):
    c = _reachable_client(session, principal, client_id)
    return _client_page(request, principal, session, cfg, c)


@router.post("/client/{client_id}/key", response_class=HTMLResponse)
def client_issue_key(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    cfg: Config,
    client_id: int,
    kind: Annotated[str, Form()] = "api_key",
    label: Annotated[str, Form()] = "",
):
    """資格情報を発行する。**平文はこの応答にしか載らない。**

    リダイレクトで一覧に戻さないのはそのため——戻した先では、もう取り出せない。
    """
    c = _reachable_client(session, principal, client_id)
    # 出し分けと同じ述語で閉じる。**使えない鍵を作らせない。**
    if kind not in _issuable_kinds(cfg):
        raise Forbidden(f"この構成は {kind} を受け付けない（ARKHE_AUTH を確認すること）")
    issued = ops.issue_credential(
        session, principal, client_pk=c.id, kind=kind, label=label.strip()
    )
    secret = issued.secret
    session.commit()
    session.refresh(c)
    return _client_page(request, principal, session, cfg, c, issued=secret)


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


@router.post("/client/{client_id}/active")
def client_toggle_active(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    client_id: int,
    active: Annotated[str, Form()] = "",
):
    """主体を止める／戻す。

    **認可サーバに寄せた構成では、これが arkhe 側の唯一の止め方。** 資格情報を
    arkhe が持たないので、失効させるものが無い。
    """
    c = _reachable_client(session, principal, client_id)
    ops.set_client_active(session, principal, client_pk=c.id, active=bool(active))
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


