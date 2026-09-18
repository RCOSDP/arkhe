"""統計の画面。**数えるのは `domain/stats.py` だけ。**

画面が独自に集計を書くと、CLI や API と違う数を出す——**同じ「件数」が場所に
よって違う**のは、いちばん質の悪いずれである。ここはドメインを呼んで並べるだけ。

**scope では縛らない。** `/api/stats` は `ark:read` を要求するが、画面の一覧
（`/admin/arks`）も scope では縛っていないので、そちらに揃えた。縛っているのは
**到達範囲**で、そこはドメインの側で効いている。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse

from arkhe.api.admin._common import AdminPrincipal, Db, _page, router
from arkhe.domain import stats as stats_domain


@router.get("/stats", response_class=HTMLResponse)
def stats(request: Request, principal: AdminPrincipal, session: Db):
    """**見えている範囲を数えて見せる。**

    届かないものは 1 件も入らない——`domain.stats` が `visible_arks` を通すので、
    ここで認可を書き直していない。**合計もまた、在ることを漏らす。**
    """
    return _page(
        request, principal, "stats.html", "stats",
        st=stats_domain.ledger_stats(session, principal),
    )
