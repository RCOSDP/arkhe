"""The screens that build the ledger: NAANs, organisations and namespaces.

What can be changed from a screen is what is declared and how things are run. Neither an
ARK row nor the spelling of a shoulder can be: if they could, names could be reassigned
in a scheme that declares NR.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from arkhe.api.admin._common import (
    AdminPrincipal,
    Db,
    _ctx,
    _page,
    _redirect,
    _refuse,
    _remember_lang,
    _visible_naans,
    router,
    templates,
)
from arkhe.db.models import (
    Ark,
    CommitmentLevel,
    Manager,
    Naan,
    Shoulder,
    ShoulderStatus,
)
from arkhe.domain import admin_ops as ops
from arkhe.domain import authz
from arkhe.settings import get_settings

# ------------------------------------------------------- The structure of delegation


@router.get("/", response_class=HTMLResponse, name="admin_overview")
def overview(request: Request, principal: AdminPrincipal, session: Db):
    naans = _visible_naans(session, principal)
    for n in naans:
        # Do not assign to the relationship itself (n.managers). SQLAlchemy would
        # read that as "these are all the children of this Naan" and set the naan of
        # every organisation left out to NULL: filtering for display would destroy
        # data. It is kept under another name.
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

    # Count only the shoulders that are visible. This used to aggregate the whole ark
    # table on every request, so the page got slower as ARKs accumulated (a sequential
    # scan). It is written so that ix_ark_shoulder_created applies.
    visible = [sh.id for n in naans for m in n.visible_managers for sh in m.shoulders]
    visible += [sh.id for n in naans for sh in n.visible_orphans]
    counts = (
        dict(
            session.execute(
                select(Ark.shoulder_id, func.count(Ark.ark))
                .where(Ark.shoulder_id.in_(visible))
                .group_by(Ark.shoulder_id)
            ).all()
        )
        if visible
        else {}
    )
    return _remember_lang(
        request,
        templates.TemplateResponse(
            request,
            "overview.html", _ctx(request, principal, "overview", naans=naans, counts=counts)
        ),
    )


# ------------------------------------------------------ Building the ledger
#
# What can be edited from a screen is what is declared and how things are run. Neither
# an ARK row nor the spelling of a shoulder can be edited here: if they could, names
# could be reassigned in a scheme that declares NR.
#
# Who may change what comes from domain.admin_ops. Writing another decision here would
# leave the hole where the button is hidden but the POST still works.


@router.get("/naan/new", response_class=HTMLResponse)
def naan_new(request: Request, principal: AdminPrincipal):
    if not principal.is_system:
        raise _refuse(request, "e.naan_system_only")
    return _page(request, principal, "naan_form.html", "overview", naan=None,
                 mechanisms=ops.MECHANISMS, scopes=authz.SCOPES)


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
    allowed_auth: Annotated[list[str], Form()] = None,
    self_register: Annotated[str, Form()] = "",
    max_scopes: Annotated[list[str], Form()] = None,
    rules: Annotated[str, Form()] = "",
    hold_days: Annotated[int, Form()] = 0,
    hold_reason: Annotated[str, Form()] = "",
    hold_release: Annotated[str, Form()] = "",
):
    ops.create_naan(
        session, principal, naan=naan.strip(), name=name.strip(), na_policy=policy.strip(),
        description=description.strip(),
        is_authoritative=bool(authoritative), redirect=redirect.strip(),
    )
    session.flush()
    # It can be decided at registration. Left until later, some are never applied.
    if rules:
        ops.set_naan_policy(
            session, principal, naan=naan.strip(),
            mechanisms=list(allowed_auth or []),
            may_self_register=bool(self_register),
            max_scopes=list(max_scopes or []),
        )
    session.commit()
    return _redirect(f"/admin/naan/{naan.strip()}")


@router.get("/naan/{naan}", response_class=HTMLResponse)
def naan_edit(request: Request, principal: AdminPrincipal, session: Db, naan: str):
    obj = session.get(Naan, naan)
    # Opening and saving are allowed under the same conditions. With reaches_naan
    # alone an organisation administrator could open it, and a form that looks editable
    # would answer 403 on save, which is the same drift between display and
    # authorisation.
    if obj is None or not principal.is_naan_wide or not principal.reaches_naan(naan):
        raise _refuse(request, "e.out_of_reach_naan")
    return _page(request, principal, "naan_form.html", "overview", naan=obj,
                 mechanisms=ops.MECHANISMS, scopes=authz.SCOPES,
                 hold_max=get_settings().hold_max_days)


@router.post("/naan/{naan}")
def naan_save(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    naan: str,
    policy: Annotated[str, Form()] = "",
    minter: Annotated[str, Form()] = "",
    allowed_auth: Annotated[list[str], Form()] = None,
    self_register: Annotated[str, Form()] = "",
    max_scopes: Annotated[list[str], Form()] = None,
    rules: Annotated[str, Form()] = "",
    hold_days: Annotated[int, Form()] = 0,
    hold_reason: Annotated[str, Form()] = "",
    hold_release: Annotated[str, Form()] = "",
):
    """The NAA policy is declared by whoever hands out the namespace, so it can only
    be changed at NAAN level or above.

    The rules for this namespace, how principals get in, whether they may self-register
    and the ceiling on scopes, are decided here too. They belong at this level: applying
    them per organisation does not scale.
    """
    ops.set_na_policy(session, principal, naan=naan, policy=policy.strip())
    if rules:
        ops.set_naan_policy(
            session, principal, naan=naan,
            mechanisms=list(allowed_auth or []),
            may_self_register=bool(self_register),
            max_scopes=list(max_scopes or []),
        )
    obj = session.get(Naan, naan)
    if minter.strip() != obj.minter:
        if not principal.is_system:
            raise _refuse(request, "e.minter_system_only")
        obj.minter = minter.strip()
        authz.audit(session, principal, "set_minter", naan, minter=obj.minter)
    _apply_hold(
        session, principal, kind="naan", key=naan,
        days=hold_days, reason=hold_reason, release=hold_release,
    )
    session.commit()
    return _redirect(f"/admin/naan/{naan}?saved=1")


def _apply_hold(session, principal, *, kind, key, days: int, reason: str, release: str):
    """Set or lift a hold from the form. It calls the same admin_ops as the CLI.

    Zero days does nothing: re-applying it on every save would keep pushing the expiry
    out until the hold was permanent.
    """
    if release:
        ops.release_hold(session, principal, kind=kind, key=key)
    elif days:
        ops.set_hold(
            session, principal, kind=kind, key=key,
            until=datetime.now(UTC) + timedelta(days=days),
            reason=reason.strip(), max_days=get_settings().hold_max_days,
        )


@router.get("/manager/new", response_class=HTMLResponse)
def manager_new(request: Request, principal: AdminPrincipal, session: Db):
    if not principal.is_naan_wide:
        raise _refuse(request, "e.manager_naan_wide")
    return _page(
        request, principal, "manager_form.html", "overview",
        manager=None, naans=_visible_naans(session, principal), levels=list(CommitmentLevel),
        mechanisms=ops.MECHANISMS, scopes=authz.SCOPES,
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
    allowed_auth: Annotated[list[str], Form()] = None,
    self_register: Annotated[str, Form()] = "",
    max_scopes: Annotated[list[str], Form()] = None,
    policy: Annotated[str, Form()] = "",
):
    m, _ = ops.onboard_manager(
        session, principal, naan=naan, name=name.strip(), shoulder=shoulder.strip(),
        commitment_level=commitment,
        quota_per_day=int(quota) if quota.strip() else None,
    )
    session.flush()
    # Restrictions can be decided while onboarding. Left until later, some of them
    # are never applied.
    if policy:
        ops.set_org_policy(
            session, principal, manager_id=m.id,
            mechanisms=list(allowed_auth or []),
            may_self_register=bool(self_register),
            max_scopes=list(max_scopes or []),
        )
    session.commit()
    return _redirect(f"/admin/manager/{m.id}")


@router.get("/manager/{manager_id}", response_class=HTMLResponse)
def manager_edit(request: Request, principal: AdminPrincipal, session: Db, manager_id: int):
    m = session.get(Manager, manager_id)
    if m is None:
        raise _refuse(request, "e.out_of_reach_manager")
    ops.require_manager(session, principal, m)
    return _page(
        request, principal, "manager_form.html", "overview",
        manager=m, naans=[], levels=list(CommitmentLevel),
        mechanisms=ops.MECHANISMS, scopes=authz.SCOPES,
        # Show what the NAAN already narrows. Otherwise the organisation can choose
        # something that has no effect, and the setting looks broken.
        naan_policy=ops.policy_for(session.get(Naan, m.naan), None),
    )


@router.post("/manager/{manager_id}")
def manager_save(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    manager_id: int,
    commitment: Annotated[str, Form()] = "",
    quota: Annotated[str, Form()] = "",
    allowed_auth: Annotated[list[str], Form()] = None,
    self_register: Annotated[str, Form()] = "",
    max_scopes: Annotated[list[str], Form()] = None,
    policy: Annotated[str, Form()] = "",
):
    """The promise belongs to the organisation, so its administrator can restate the
    level.

    The minting quota does not: it is imposed by whoever handed out the namespace. The
    decision is in admin_ops.
    """
    if commitment:
        ops.set_commitment(session, principal, manager_id=manager_id, level=commitment)
    if principal.is_naan_wide:
        ops.set_quota(
            session, principal, manager_id=manager_id,
            quota_per_day=int(quota) if quota.strip() else None,
        )
        # policy marks that this form showed the restriction fields, so that an empty
        # value from a form that did not show them cannot clear them.
        if policy:
            ops.set_org_policy(
                session, principal, manager_id=manager_id,
                mechanisms=list(allowed_auth or []),
                may_self_register=bool(self_register),
                max_scopes=list(max_scopes or []),
            )
    session.commit()
    return _redirect(f"/admin/manager/{manager_id}?saved=1")


@router.get("/shoulder/new", response_class=HTMLResponse)
def shoulder_new(request: Request, principal: AdminPrincipal, session: Db):
    if not principal.is_naan_wide:
        raise _refuse(request, "e.shoulder_naan_wide")
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
        raise _refuse(request, "e.out_of_reach_shoulder")
    return _page(
        request, principal, "shoulder_form.html", "overview",
        shoulder=sh, naans=[], statuses=list(ShoulderStatus),
        hold_max=get_settings().hold_max_days,
    )


@router.post("/shoulder/{shoulder_id}")
def shoulder_save(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    shoulder_id: int,
    status: Annotated[str, Form()] = "",
    minter: Annotated[str, Form()] = "",
    about: Annotated[str, Form()] = "",
    redirect: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
    hold_days: Annotated[int, Form()] = 0,
    hold_reason: Annotated[str, Form()] = "",
    hold_release: Annotated[str, Form()] = "",
):
    """There is no way back from retired. That decision lives in admin_ops."""
    sh = session.get(Shoulder, shoulder_id)
    if sh is None:
        raise _refuse(request, "e.out_of_reach_shoulder")
    if status and status != sh.status:
        ops.set_shoulder_status(
            session, principal, shoulder_id=shoulder_id, status=status,
            minter=minter.strip(), about=about.strip(), note=note.strip(),
        )
    elif about.strip() != sh.about or minter.strip() != sh.minter:
        # A path that changes the guidance without changing the state, so that an
        # internal host name put there by mistake can be replaced.
        ops.set_shoulder_status(
            session, principal, shoulder_id=shoulder_id, status=sh.status,
            minter=minter.strip(), about=about.strip(),
        )
    if redirect.strip() != sh.redirect:
        ops.set_shoulder_redirect(
            session, principal, shoulder_id=shoulder_id, redirect=redirect.strip()
        )
    _apply_hold(
        session, principal, kind="shoulder", key=shoulder_id,
        days=hold_days, reason=hold_reason, release=hold_release,
    )
    session.commit()
    return _redirect(f"/admin/shoulder/{shoulder_id}?saved=1")




# --------------------------------------------------------- Redirection on hold
#
# Even with an expiry, a hold nobody can see becomes permanent. Whoever set it may
# forget, but on a list someone else notices.


@router.get("/holds", response_class=HTMLResponse)
def holds(request: Request, principal: AdminPrincipal, session: Db):
    """List the holds in force across all three levels on one page."""
    return _page(request, principal, "holds.html", "holds", holds=ops.held(session, principal))
