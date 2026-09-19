"""The statistics screen. All counting happens in domain/stats.py.

A screen that aggregates on its own reports different numbers from the CLI and the API,
and one count differing by where it is read is the worst kind of drift. This module
calls the domain and lays the result out.

No scope is required. /api/stats requires ark:read, but the list screen at /admin/arks
has no scope either, so this matches it. What binds is the reach, which the domain
applies.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse

from arkhe.api.admin._common import AdminPrincipal, Db, _page, router
from arkhe.domain import stats as stats_domain


@router.get("/stats", response_class=HTMLResponse)
def stats(request: Request, principal: AdminPrincipal, session: Db):
    """Count what is visible and show it.

    Nothing out of reach is included: domain.stats goes through visible_arks, so the
    authorisation is not written again here. A total leaks existence too.
    """
    return _page(
        request, principal, "stats.html", "stats",
        st=stats_domain.ledger_stats(session, principal),
    )
