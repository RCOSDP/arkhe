"""Principals and their credentials.

A plaintext credential exists only here. It is returned once, immediately after it is
issued; what is stored is a hash.
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
    _refuse,
    _remember_lang,
    _visible_shoulders,
    router,
    templates,
)
from arkhe.auth.principal import Principal
from arkhe.db.models import (
    Client,
    Manager,
    UnknownSubject,
)
from arkhe.domain import admin_ops as ops
from arkhe.domain import authz

# ---------------------------------------------------------------- Principals


def _unknown_subjects(session: Session, principal: Principal) -> list[UnknownSubject]:
    """Principals that arrived without a registration, excluding those since
    registered.

    The comparison is made on each request. Nothing sweeps the table when something is
    registered, so nothing lingers because a sweep was missed.

    It is shown only to principals that reach NAAN level or above. A token does not say
    which organisation it belongs to and nothing here guesses, so showing the list to an
    organisation-level administrator would mix in another organisation's client ids.
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
            c.scope_label = c.naan or "every NAAN"
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


# ------------------------------------------- Principals and their credentials
#
# A plaintext credential exists only here. It is returned once, immediately after it is
# issued, and only a hash is stored, so reloading the page does not show it again. That
# is why issuing is a POST whose own response carries it; a redirect would lose it.


def _reachable_client(
    request: Request, session: Session, principal: Principal, client_id: int
) -> Client:
    """Return only the principals within reach, using the same decision as
    admin_ops."""
    c = session.get(Client, client_id)
    if c is None:
        raise _refuse(request, "e.out_of_reach_client")
    if not principal.reaches_naan(c.naan):
        raise _refuse(request, "e.out_of_reach_client")
    if not principal.is_naan_wide and c.manager_id != principal.manager_id:
        raise _refuse(request, "e.out_of_reach_client")
    return c


def _client_page(request: Request, principal: Principal, session: Db, cfg,
                 c: Client | None, prefill: str = "", **extra):
    managers = []
    if principal.is_naan_wide:
        stmt = select(Manager).where(Manager.active.is_(True)).order_by(Manager.naan, Manager.name)
        if not principal.is_system:
            stmt = stmt.where(Manager.naan == principal.naan)
        managers = list(session.scalars(stmt))
    # _mintable is for display and carries no id; binding needs the rows themselves.
    shoulders = _visible_shoulders(session, principal) if c is None else []
    return _page(
        request, principal, "client_form.html", "clients",
        client=c, managers=managers, shoulders=shoulders,
        creds=sorted(c.credentials, key=lambda x: x.id, reverse=True) if c else [],
        scopes=authz.SCOPES,
        kinds=_issuable_kinds(cfg), uses_oidc="oidc" in cfg.auth,
        entry=_entry_route(c, cfg) if c else "",
        prefill=prefill,
        # When nothing can be chosen, say why rather than showing an empty area.
        missing_mech=("oauth2" if "apikey" in cfg.auth else "apikey")
        if len(_issuable_kinds(cfg)) == 1 else "",
        # Say where to go. "Create it at the authorisation server" does not tell the
        # reader which one.
        issuer=cfg.oidc_issuer,
        **extra,
    )


@router.get("/client/new", response_class=HTMLResponse)
def client_new(
    request: Request, principal: AdminPrincipal, session: Db, cfg: Config,
    client_id: str = "",
):
    # Closed with the same predicate the display uses.
    if not _may_register(session, principal):
        raise _refuse(request, "e.cannot_add_client")
    # The identifier carried over from the unregistered list becomes the default. It
    # is exactly what the authorisation server signed, so retyping it would only create
    # another chance to misspell it.
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
    """Register a principal. No credential is issued here.

    Registration and issuing are separate because a person is issued none. First decide
    what the principal is; if it is a machine, the next page issues a credential.
    """
    c = ops.register_client(
        session, principal, client_id=client_id.strip(),
        naan=naan or principal.naan,
        # Only their own organisation can be chosen. Nothing else was offered, so a
        # value that arrives anyway is not used.
        manager_id=(
            int(manager_id) if principal.is_naan_wide and manager_id.strip()
            else principal.manager_id
        ),
        shoulder_id=int(shoulder_id) if shoulder_id.strip() else None,
        # Anything outside the vocabulary is dropped: a value that was never offered
        # is not used.
        scopes=" ".join(x for x in (scopes or []) if x in authz.SCOPES) or "ark:mint",
        label=label.strip(),
        subject_type="person" if person else "machine",
    )
    session.commit()
    return _redirect(f"/admin/client/{c.id}")


@router.get("/client/{client_id}", response_class=HTMLResponse)
def client_detail(request: Request, principal: AdminPrincipal, session: Db, cfg: Config,
                  client_id: int):
    c = _reachable_client(request, session, principal, client_id)
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
    """Issue a credential. The plaintext appears in this response and nowhere else.

    That is why it does not redirect back to the list: after a redirect it could not be
    retrieved.
    """
    c = _reachable_client(request, session, principal, client_id)
    # Closed with the same predicate the display uses, so no unusable credential is
    # created.
    if kind not in _issuable_kinds(cfg):
        raise _refuse(request, "e.mechanism_off")
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
    """The row is not deleted, so when it was revoked is still known."""
    _reachable_client(request, session, principal, client_id)
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
    """Stop a principal, or start it again.

    Where an authorisation server is used, this is the only lever arkhe has: it holds no
    credential, so there is nothing to revoke.
    """
    c = _reachable_client(request, session, principal, client_id)
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
    """Set a password on a person, for deployments with ARKHE_ADMIN_LOGIN=password."""
    c = _reachable_client(request, session, principal, client_id)
    ops.set_password(session, principal, client_pk=c.id, password=password)
    session.commit()
    return _redirect(f"/admin/client/{client_id}?saved=1")


