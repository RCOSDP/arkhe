"""発行した ARK と、その行き先が変わった記録。

**到達範囲でそのまま絞る。** 一覧の絞り込みと認可を別々に書かない。
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from arkhe.api.admin._common import (
    PAGE,
    AdminPrincipal,
    Db,
    _page,
    router,
)
from arkhe.auth.errors import Forbidden
from arkhe.auth.principal import Principal
from arkhe.db.models import (
    Ark,
    ArkChange,
    Manager,
    Shoulder,
)

# ------------------------------------------------------------ 発行した ARK
#
# **到達範囲でそのまま絞る。** システム管理者は全件、NAAN 単位はその NAAN、
# 組織単位は自組織の shoulder に限る——一覧の絞り込みと認可を別々に書かない。
#
# 件数は増える一方なので、**最初からページ送りと検索を入れる**。後から足すと、
# それまでの利用者は「全部出る」前提の画面に慣れてしまう。

def _visible_arks(session: Session, p: Principal):
    stmt = select(Ark).options(selectinload(Ark.shoulder))
    if not p.is_system:
        stmt = stmt.where(Ark.naan == p.naan)
    if not p.is_naan_wide:
        # 組織単位は自組織の shoulder に限る。**主体が shoulder に固定されて
        # いればそれだけ**（採番できる範囲と同じ絞り方にする）。
        if p.shoulder_id is not None:
            stmt = stmt.where(Ark.shoulder_id == p.shoulder_id)
        else:
            stmt = stmt.where(
                Ark.shoulder_id.in_(
                    select(Shoulder.id).where(Shoulder.manager_id == p.manager_id)
                )
            )
    return stmt


def _selectable_orgs(session: Session, p: Principal) -> list[Manager]:
    """絞り込みに出す組織。**届く範囲のものだけ。**

    組織単位の管理者には出さない——自組織しか見えないので、選択肢が 1 つの
    絞り込みは操作を増やすだけになる。
    """
    if not p.is_naan_wide:
        return []
    stmt = select(Manager).order_by(Manager.naan, Manager.name)
    if not p.is_system:
        stmt = stmt.where(Manager.naan == p.naan)
    return list(session.scalars(stmt))


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
    stmt = _visible_arks(session, principal)
    # **組織で絞る。** 到達範囲を広げる手段ではない——`_visible_arks` で先に
    # 絞ったうえに重ねるので、届かない組織を指定しても何も出ない。
    if org.strip().isdigit():
        stmt = stmt.where(
            Ark.shoulder_id.in_(
                select(Shoulder.id).where(Shoulder.manager_id == int(org))
            )
        )
    term = q.strip()
    if term:
        # **ARK そのものと、行き先と、題名で引く。** 運用で手元にあるのはどれか
        # 分からないので、3 つとも見る。
        like = f"%{term}%"
        stmt = stmt.where(
            Ark.ark.ilike(like) | Ark.url.ilike(like) | Ark.title.ilike(like)
        )
    page = max(1, page)
    rows = list(
        session.scalars(
            stmt.order_by(Ark.created_at.desc()).offset((page - 1) * PAGE).limit(PAGE + 1)
        )
    )
    more = len(rows) > PAGE
    return _page(
        request, principal, "arks.html", "arks",
        arks=rows[:PAGE], q=term, page_no=page, more=more,
        org=org.strip(), orgs=_selectable_orgs(session, principal),
    )


@router.get("/arks/{ark:path}", response_class=HTMLResponse)
def ark_detail(request: Request, principal: AdminPrincipal, session: Db, ark: str):
    """1 本の ARK と、**その行き先が変わった記録**。

    到達範囲の判定は一覧と同じ式を使う（`_visible_arks`）——別に書くと、
    一覧に出ないものが URL 直打ちで見える。
    """
    key = ark.removeprefix("ark:/").removeprefix("ark:")
    row = session.scalar(_visible_arks(session, principal).where(Ark.ark == key))
    if row is None:
        raise Forbidden("この ARK はこの主体の範囲外")
    changes = list(
        session.scalars(
            select(ArkChange).where(ArkChange.ark == key).order_by(ArkChange.at.desc())
        )
    )
    return _page(request, principal, "ark_detail.html", "arks", ark=row, changes=changes)


