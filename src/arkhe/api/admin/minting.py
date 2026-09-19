"""The screen for minting one ARK by hand.

Ordinarily an organisation's own system mints through the API. This is for one-off cases
during a migration, for physical objects, and for checking that things work.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Form, Request
from fastapi.responses import HTMLResponse

from arkhe.api import i18n
from arkhe.api.admin._common import (
    RESOURCE_TYPES,
    AdminPrincipal,
    Db,
    _ctx,
    _mintable,
    _refuse,
    _remember_lang,
    router,
    templates,
)
from arkhe.arkspec.naming import compact_ark
from arkhe.domain import authz, minting
from arkhe.domain.resolution import is_registrable

# ----------------------------------------------------------------- Minting


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
                # At NAAN level and above the shoulder must be named: there is no
                # default.
                needs_shoulder=principal.is_naan_wide,
                types=RESOURCE_TYPES,
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
    type: Annotated[str, Form()] = "",  # noqa: A002 - the name of the ERC element
    who: Annotated[str, Form()] = "",
    when: Annotated[str, Form()] = "",
    reserve: Annotated[str, Form()] = "",
):
    """Minting from the screen, through the same path as the API: authz, then
    minting."""
    authz.require_scope(principal, "ark:mint")
    # Refused here as well. The ORM refuses it underneath
    # (Ark._refuse_dangerous_url), but that is only a 500 and tells the operator
    # nothing. This is not the guard; it is what makes the refusal readable.
    if not is_registrable(url):
        raise _refuse(request, "e.url_scheme")
    sh = authz.shoulder_for(session, principal, shoulder or None)
    authz.assert_shoulder_mintable(sh)
    authz.assert_within_quota(session, principal)
    ark, _ = minting.mint(
        session,
        shoulder=sh,
        # It can be minted as reserved, so the screen and the API behave alike
        # (see MintIn.reserve).
        reserve=bool(reserve),
        created_by=principal.client_id,
        url=url,
        title=title,
        type=type,
        who=who,
        when=when,
    )
    authz.audit(session, principal, "mint", ark.ark, via="admin-ui", reserved=bool(reserve))
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
                types=RESOURCE_TYPES,
                minted=ark,
                flash=f"{compact_ark(ark.ark)} "
                + i18n.translator(i18n.pick(request))("mint.flash"),
            ),
        ),
    )


