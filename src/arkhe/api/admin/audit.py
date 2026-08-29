"""監査ログ。**NAAN 単位以上にしか見せない。**

誰が何をしたかはその名前空間を預かる側の情報で、組織の担当者が他組織の
履歴を読む筋合いは無い。
"""

from __future__ import annotations

import json

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from arkhe.api.admin._common import (
    PAGE,
    AdminPrincipal,
    Db,
    _ctx,
    _remember_lang,
    router,
    templates,
)
from arkhe.auth.errors import Forbidden
from arkhe.db.models import (
    AuditEvent,
)

# ------------------------------------------------------------------ 監査


@router.get("/audit", response_class=HTMLResponse)
def audit(request: Request, principal: AdminPrincipal, session: Db,
          q: str = "", page: int = 1):
    """**監査ログは NAAN 単位以上にしか見せない。**

    誰がいつ何をしたかは、その名前空間を預かる側の情報。組織の担当者に他組織の
    操作履歴が見えてはならない。
    """
    if not principal.is_naan_wide:
        raise Forbidden("監査ログの閲覧は NAAN 単位以上の権限が要る")
    page = max(1, page)
    stmt = select(AuditEvent).order_by(AuditEvent.at.desc())
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            AuditEvent.client_id.ilike(like)
            | AuditEvent.action.ilike(like)
            | AuditEvent.target.ilike(like)
        )
    events = list(session.scalars(stmt.offset((page - 1) * PAGE).limit(PAGE + 1)))
    more = len(events) > PAGE
    events = events[:PAGE]
    for e in events:
        e.detail_text = json.dumps(e.detail, ensure_ascii=False) if e.detail else ""
    return _remember_lang(
        request,
        templates.TemplateResponse(
            request,
            "audit.html",
            _ctx(request, principal, "audit", events=events,
                 q=q.strip(), page_no=page, more=more),
        ),
    )


