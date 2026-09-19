"""Minted ARKs and the record of their targets changing.

The filtering lives in domain.queries. Written separately for the screens and the CLI,
fixing one would leave them showing different things.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from arkhe.api.admin._common import (
    PAGE,
    AdminPrincipal,
    Db,
    _page,
    _redirect,
    _refuse,
    router,
)
from arkhe.db.models import Ark, ArkChange
from arkhe.domain import admin_ops as ops
from arkhe.domain import authz
from arkhe.domain.queries import ARK_STATES, narrow_arks, selectable_orgs, visible_arks
from arkhe.settings import get_settings

# -------------------------------------------------------------- Minted ARKs
#
# The count only grows, so pagination and search are there from the start. Added
# later, people would already be used to a page that shows everything.


@router.get("/arks", response_class=HTMLResponse)
def arks(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    q: str = "",
    org: str = "",
    state: str = "",
    page: int = 1,
):
    """The list of minted ARKs."""
    stmt = narrow_arks(
        visible_arks(principal).options(selectinload(Ark.shoulder)),
        org=org, q=q, state=state,
    )
    page = max(1, page)
    rows = list(
        session.scalars(
            stmt.order_by(Ark.created_at.desc()).offset((page - 1) * PAGE).limit(PAGE + 1)
        )
    )
    more = len(rows) > PAGE
    # An organisation-level administrator is not offered the filter: only one
    # organisation is visible, so a filter with one choice adds work.
    orgs = list(session.scalars(selectable_orgs(principal))) if principal.is_naan_wide else []
    return _page(
        request, principal, "arks.html", "arks",
        arks=rows[:PAGE], q=q.strip(), page_no=page, more=more,
        org=org.strip(), orgs=orgs, state=state.strip(), states=ARK_STATES,
    )


@router.get("/arks/{ark:path}", response_class=HTMLResponse)
def ark_detail(request: Request, principal: AdminPrincipal, session: Db, ark: str):
    """One ARK, and the record of its target changing.

    The reach uses the same query as the list (visible_arks). Written separately,
    something absent from the list would be reachable by typing the URL.
    """
    key = ark.removeprefix("ark:/").removeprefix("ark:")
    row = session.scalar(
        visible_arks(principal).options(selectinload(Ark.shoulder)).where(Ark.ark == key)
    )
    if row is None:
        raise _refuse(request, "e.out_of_reach_ark")
    changes = list(
        session.scalars(
            select(ArkChange).where(ArkChange.ark == key).order_by(ArkChange.at.desc())
        )
    )
    return _page(
        request, principal, "ark_detail.html", "arks",
        ark=row, changes=changes, hold_max=get_settings().hold_max_days,
        # Only show what can be used, looking at both the state and the scope. The
        # same decision applies in admin_ops; hiding a control is a courtesy, not the
        # guard.
        can_publish=row.published_at is None and principal.has("ark:mint"),
        can_unpublish=row.published_at is not None and principal.has("ark:unpublish"),
        can_withdraw=row.published_at is None and principal.has("ark:delete"),
        can_purge=row.published_at is not None and principal.has("ark:purge"),
        # Whether it was ever public. That decides whether a reason and a
        # confirmation are asked for: the weight comes from the name's history, not
        # from the caller's tier.
        was_exposed=row.first_published_at is not None,
    )


@router.post("/arks/{ark:path}/publish")
def ark_publish(request: Request, principal: AdminPrincipal, session: Db, ark: str):
    """Publish it to the world. The screens, the CLI and the API call one operation.

    The scope is checked here as well: hiding a button leaves the URL, which is why the
    same decision is used as in _ctx.
    """
    key = ark.removeprefix("ark:/").removeprefix("ark:")
    authz.require_scope(principal, "ark:mint")
    ops.publish_ark(session, principal, ark=key)
    session.commit()
    return _redirect(f"/admin/arks/{key}")


@router.post("/arks/{ark:path}/unpublish")
def ark_unpublish(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    ark: str,
    reason: Annotated[str, Form()] = "",
    confirm: Annotated[str, Form()] = "",
):
    """Withdraw the publication. The row stays, so it returns to the detail page.

    The reason and the confirmation are asked for on the screen, but admin_ops is what
    refuses. A required attribute is a courtesy, not a guard.
    """
    key = ark.removeprefix("ark:/").removeprefix("ark:")
    authz.require_scope(principal, "ark:unpublish")
    ops.unpublish_ark(session, principal, ark=key, reason=reason, confirm=confirm)
    session.commit()
    return _redirect(f"/admin/arks/{key}")


@router.post("/arks/{ark:path}/delete")
def ark_delete(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    ark: str,
    reason: Annotated[str, Form()] = "",
    confirm: Annotated[str, Form()] = "",
):
    """Delete an ARK that is not published. While it is, admin_ops answers 409.

    It returns to the list rather than the detail page, which no longer exists.
    """
    key = ark.removeprefix("ark:/").removeprefix("ark:")
    authz.require_scope(principal, "ark:delete")
    ops.withdraw_ark(session, principal, ark=key, reason=reason, confirm=confirm)
    session.commit()
    return _redirect("/admin/arks")


@router.post("/arks/{ark:path}/purge")
def ark_purge(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    ark: str,
    reason: Annotated[str, Form()] = "",
    confirm: Annotated[str, Form()] = "",
):
    """Purge a published ARK in one step, within the caller's reach.

    The screen asks for the ARK again and for a reason, but admin_ops is what refuses. A
    required attribute is a courtesy, not a guard.
    """
    key = ark.removeprefix("ark:/").removeprefix("ark:")
    authz.require_scope(principal, "ark:purge")
    ops.purge_ark(session, principal, ark=key, reason=reason, confirm=confirm)
    session.commit()
    return _redirect("/admin/arks")


@router.post("/arks/{ark:path}/hold")
def ark_hold(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    ark: str,
    days: Annotated[int, Form()] = 0,
    reason: Annotated[str, Form()] = "",
    release: Annotated[str, Form()] = "",
):
    """The screens and the CLI behave alike: this calls what arkhe hold add and release
    call.

    The reach is decided in admin_ops as well. Written again here, it would leave the
    hole where the button is hidden but the POST still works.
    """
    key = ark.removeprefix("ark:/").removeprefix("ark:")
    if release:
        ops.release_hold(session, principal, kind="ark", key=key)
    else:
        ops.set_hold(
            session, principal, kind="ark", key=key,
            until=datetime.now(UTC) + timedelta(days=days),
            reason=reason, max_days=get_settings().hold_max_days,
        )
    session.commit()
    return _redirect(f"/admin/arks/{key}")
