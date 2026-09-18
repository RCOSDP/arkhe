"""発行した ARK と、その行き先が変わった記録。

**絞り込みは `domain.queries` に置く。** 画面と CLI で別々に書くと、片方だけ
直したときに見える範囲がずれる。
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
    state: str = "",
    page: int = 1,
):
    """発行した ARK の一覧。"""
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
    # **組織単位の管理者には選択肢を出さない**——自組織しか見えないので、
    # 選択肢が 1 つの絞り込みは操作を増やすだけになる。
    orgs = list(session.scalars(selectable_orgs(principal))) if principal.is_naan_wide else []
    return _page(
        request, principal, "arks.html", "arks",
        arks=rows[:PAGE], q=q.strip(), page_no=page, more=more,
        org=org.strip(), orgs=orgs, state=state.strip(), states=ARK_STATES,
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
        raise _refuse(request, "e.out_of_reach_ark")
    changes = list(
        session.scalars(
            select(ArkChange).where(ArkChange.ark == key).order_by(ArkChange.at.desc())
        )
    )
    return _page(
        request, principal, "ark_detail.html", "arks",
        ark=row, changes=changes, hold_max=get_settings().hold_max_days,
        # **押せるものだけ見せる。** 状態と scope の両方を見る（判定は
        # `admin_ops` 側と同じものが効く。出し分けは親切であって防御ではない）。
        can_publish=row.published_at is None and principal.has("ark:mint"),
        can_unpublish=row.published_at is not None and principal.has("ark:unpublish"),
        can_withdraw=row.published_at is None and principal.has("ark:delete"),
        can_purge=row.published_at is not None and principal.has("ark:purge"),
        # **一度でも外に出したか。** 理由と打ち直しを出すかがこれで決まる
        # ——重さは主体の位ではなく、名前の履歴で決まる。
        was_exposed=row.first_published_at is not None,
    )


@router.post("/arks/{ark:path}/publish")
def ark_publish(request: Request, principal: AdminPrincipal, session: Db, ark: str):
    """**グローバルに公開する。** 画面と CLI と API が同じ操作を呼ぶ。

    scope の検査もここでする——ボタンを出し分けるだけでは、URL を直接叩く道が
    残る（`_ctx` の出し分けと同じ判定を使うのはそのため）。
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
    """**公開を取り下げる。** 行は残るので、戻り先は詳細のまま。

    理由と打ち直しの入力は画面に置いてあるが、**弾くのは `admin_ops` 側**である
    ——画面の required 属性は親切であって、防御ではない。
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
    """**公開していない ARK を消す。** 公開中なら `admin_ops` が 409 で断る。

    戻り先は詳細ではなく一覧——**その詳細ページはもう無い**。
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
    """**公開した ARK を一手で破棄する。** 届く範囲の内側だけ。

    画面には確認の入力（ARK の打ち直し）と理由を置いてあるが、**弾くのは
    `admin_ops` 側**である——画面の required 属性は親切であって、防御ではない。
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
    """**画面と CLI に差を作らない。** `arkhe hold add/release` と同じ操作を呼ぶ。

    到達範囲の判定も `admin_ops` 側に任せる——ここで独自に書くと、ボタンは
    出ないのに POST は通る、という穴になる。
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
