"""手作業で 1 本採番する画面。

通常の採番は組織のシステムが API から行う。ここは移行時の個別対応、
物理オブジェクト、動作確認のためのもの。
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
    _remember_lang,
    router,
    templates,
)
from arkhe.domain import authz, minting

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
                types=RESOURCE_TYPES,
                minted=ark,
                flash=f"ark:/{ark.ark} "
                + i18n.translator(i18n.pick(request))("mint.flash"),
            ),
        ),
    )


