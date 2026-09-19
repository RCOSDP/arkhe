"""The audit log, shown only at NAAN level and above.

Who did what belongs to whoever holds the namespace; someone working for one
organisation has no business reading another's history.
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
    _refuse,
    _remember_lang,
    router,
    templates,
)
from arkhe.db.models import (
    AuditEvent,
)

# ------------------------------------------------------------------ Audit


@router.get("/audit", response_class=HTMLResponse)
def audit(request: Request, principal: AdminPrincipal, session: Db,
          q: str = "", page: int = 1):
    """The audit log is shown only at NAAN level and above.

    Who did what and when belongs to whoever holds the namespace, and one
    organisation's staff must not see another's operations.
    """
    if not principal.is_naan_wide:
        raise _refuse(request, "e.audit_naan_wide")
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


