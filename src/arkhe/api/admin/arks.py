"""発行した ARK と、その行き先が変わった記録。

**絞り込みは `domain.queries` に置く。** 画面と CLI で別々に書くと、片方だけ
直したときに見える範囲がずれる。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from arkhe.api.admin._common import (
    PAGE,
    AdminPrincipal,
    Db,
    _page,
    router,
)
from arkhe.auth.errors import Forbidden
from arkhe.db.models import Ark, ArkChange
from arkhe.domain.queries import narrow_arks, selectable_orgs, visible_arks

# ------------------------------------------------------------ 発行した ARK
#
# 件数は増える一方なので、**最初からページ送りと検索を入れる**。後から足すと、
# それまでの利用者は「全部出る」前提の画面に慣れてしまう。


@router.get("/arks", response_class=HTMLResponse)
def arks(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    q: str = "",
    org: str = "",
    page: int = 1,
):
    """発行した ARK の一覧。"""
    stmt = narrow_arks(
        visible_arks(principal).options(selectinload(Ark.shoulder)), org=org, q=q
    )
    page = max(1, page)
    rows = list(
        session.scalars(
            stmt.order_by(Ark.created_at.desc()).offset((page - 1) * PAGE).limit(PAGE + 1)
        )
    )
    more = len(rows) > PAGE
    # **組織単位の管理者には選択肢を出さない**——自組織しか見えないので、
    # 選択肢が 1 つの絞り込みは操作を増やすだけになる。
    orgs = list(session.scalars(selectable_orgs(principal))) if principal.is_naan_wide else []
    return _page(
        request, principal, "arks.html", "arks",
        arks=rows[:PAGE], q=q.strip(), page_no=page, more=more,
        org=org.strip(), orgs=orgs,
    )


@router.get("/arks/{ark:path}", response_class=HTMLResponse)
def ark_detail(request: Request, principal: AdminPrincipal, session: Db, ark: str):
    """1 本の ARK と、**その行き先が変わった記録**。

    到達範囲の判定は一覧と同じ式を使う（`visible_arks`）——別に書くと、
    一覧に出ないものが URL 直打ちで見える。
    """
    key = ark.removeprefix("ark:/").removeprefix("ark:")
    row = session.scalar(
        visible_arks(principal).options(selectinload(Ark.shoulder)).where(Ark.ark == key)
    )
    if row is None:
        raise Forbidden("この ARK はこの主体の範囲外")
    changes = list(
        session.scalars(
            select(ArkChange).where(ArkChange.ark == key).order_by(ArkChange.at.desc())
        )
    )
    return _page(request, principal, "ark_detail.html", "arks", ark=row, changes=changes)
