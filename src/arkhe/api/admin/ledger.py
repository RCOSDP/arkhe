"""台帳を組む画面——NAAN、組織、名前空間。

**画面から変えられるのは、宣言と運用の設定だけ。** ARK の行も shoulder の
綴りも変えられない——変えられると、`NR` を宣言しているはずの体系で名前が
振り直せることになる。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from arkhe.api.admin._common import (
    AdminPrincipal,
    Db,
    _ctx,
    _page,
    _redirect,
    _remember_lang,
    _visible_naans,
    router,
    templates,
)
from arkhe.auth.errors import Forbidden
from arkhe.db.models import (
    Ark,
    CommitmentLevel,
    Manager,
    Naan,
    Shoulder,
    ShoulderStatus,
)
from arkhe.domain import admin_ops as ops
from arkhe.domain import authz
from arkhe.settings import get_settings

# ------------------------------------------------------------------ 委譲の構造


@router.get("/", response_class=HTMLResponse, name="admin_overview")
def overview(request: Request, principal: AdminPrincipal, session: Db):
    naans = _visible_naans(session, principal)
    for n in naans:
        # **リレーション名（`n.managers`）には代入しない。** 代入すると SQLAlchemy は
        # 「この Naan の子はこれで全部」と解釈し、**一覧から外した組織の naan を
        # NULL に更新する**。表示のための絞り込みがデータを壊す。別名に持つ。
        stmt = (
            select(Manager)
            .where(Manager.naan == n.naan)
            .options(selectinload(Manager.shoulders))
            .order_by(Manager.name)
        )
        if not principal.is_naan_wide:
            stmt = stmt.where(Manager.id == principal.manager_id)
        n.visible_managers = list(session.scalars(stmt))
        n.visible_orphans = (
            list(
                session.scalars(
                    select(Shoulder)
                    .where(Shoulder.naan == n.naan, Shoulder.manager_id.is_(None))
                    .order_by(Shoulder.shoulder)
                )
            )
            if principal.is_naan_wide
            else []
        )

    # **見えている shoulder の分だけ数える。** 以前は `ark` 全体を毎回集計して
    # いたので、ARK が増えるほど画面が重くなった（`Seq Scan on ark`）。
    # `ix_ark_shoulder_created` が効く形にしてある。
    visible = [sh.id for n in naans for m in n.visible_managers for sh in m.shoulders]
    visible += [sh.id for n in naans for sh in n.visible_orphans]
    counts = (
        dict(
            session.execute(
                select(Ark.shoulder_id, func.count())
                .where(Ark.shoulder_id.in_(visible))
                .group_by(Ark.shoulder_id)
            ).all()
        )
        if visible
        else {}
    )
    return _remember_lang(
        request,
        templates.TemplateResponse(
            request,
            "overview.html", _ctx(request, principal, "overview", naans=naans, counts=counts)
        ),
    )


# --------------------------------------------------------- 台帳を組む操作
#
# **画面から編集できるのは、宣言と運用の設定だけ。** ARK の行も shoulder の
# 綴りも、画面からは変えられない——変えられてしまうと、`NR` を宣言している
# はずの体系で名前が振り直せることになる。
#
# 誰が何を変えられるかは `domain.admin_ops` の判定をそのまま使う。ここで
# 別の判定を書くと、ボタンは出ないが POST は通る、という穴になる。


@router.get("/naan/new", response_class=HTMLResponse)
def naan_new(request: Request, principal: AdminPrincipal):
    if not principal.is_system:
        raise Forbidden("NAAN の登録はシステム管理者のみ")
    return _page(request, principal, "naan_form.html", "overview", naan=None,
                 mechanisms=ops.MECHANISMS, scopes=authz.SCOPES)


@router.post("/naan/new")
def naan_create(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    naan: Annotated[str, Form()],
    name: Annotated[str, Form()],
    policy: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    authoritative: Annotated[str, Form()] = "",
    redirect: Annotated[str, Form()] = "",
    allowed_auth: Annotated[list[str], Form()] = None,
    self_register: Annotated[str, Form()] = "",
    max_scopes: Annotated[list[str], Form()] = None,
    rules: Annotated[str, Form()] = "",
    hold_days: Annotated[int, Form()] = 0,
    hold_reason: Annotated[str, Form()] = "",
    hold_release: Annotated[str, Form()] = "",
):
    ops.create_naan(
        session, principal, naan=naan.strip(), name=name.strip(), na_policy=policy.strip(),
        description=description.strip(),
        is_authoritative=bool(authoritative), redirect=redirect.strip(),
    )
    session.flush()
    # **登録の時点で決められるようにする。** 後回しにすると掛け忘れが残る。
    if rules:
        ops.set_naan_policy(
            session, principal, naan=naan.strip(),
            mechanisms=list(allowed_auth or []),
            may_self_register=bool(self_register),
            max_scopes=list(max_scopes or []),
        )
    session.commit()
    return _redirect(f"/admin/naan/{naan.strip()}")


@router.get("/naan/{naan}", response_class=HTMLResponse)
def naan_edit(request: Request, principal: AdminPrincipal, session: Db, naan: str):
    obj = session.get(Naan, naan)
    # **開ける条件と保存できる条件を揃える。** `reaches_naan` だけだと組織管理者にも
    # 開けてしまい、編集できるように見えるフォームが保存で 403 になる。
    # 出し分けと認可がずれているのと同じことなので、ここで揃える。
    if obj is None or not principal.is_naan_wide or not principal.reaches_naan(naan):
        raise Forbidden(f"NAAN {naan} はこの主体の範囲外")
    return _page(request, principal, "naan_form.html", "overview", naan=obj,
                 mechanisms=ops.MECHANISMS, scopes=authz.SCOPES,
                 hold_max=get_settings().hold_max_days)


@router.post("/naan/{naan}")
def naan_save(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    naan: str,
    policy: Annotated[str, Form()] = "",
    minter: Annotated[str, Form()] = "",
    allowed_auth: Annotated[list[str], Form()] = None,
    self_register: Annotated[str, Form()] = "",
    max_scopes: Annotated[list[str], Form()] = None,
    rules: Annotated[str, Form()] = "",
    hold_days: Annotated[int, Form()] = 0,
    hold_reason: Annotated[str, Form()] = "",
    hold_release: Annotated[str, Form()] = "",
):
    """**NAA ポリシーは名前空間を配る側の宣言。** NAAN 単位以上でしか変えられない。

    この名前空間の決まり（入り方・自己登録・scope の上限）もここで決める。
    **原則をここに置く**——組織が増えると 1 つずつ掛けるのが現実的でなくなる。
    """
    ops.set_na_policy(session, principal, naan=naan, policy=policy.strip())
    if rules:
        ops.set_naan_policy(
            session, principal, naan=naan,
            mechanisms=list(allowed_auth or []),
            may_self_register=bool(self_register),
            max_scopes=list(max_scopes or []),
        )
    obj = session.get(Naan, naan)
    if minter.strip() != obj.minter:
        if not principal.is_system:
            raise Forbidden("採番の案内先の変更はシステム管理者のみ")
        obj.minter = minter.strip()
        authz.audit(session, principal, "set_minter", naan, minter=obj.minter)
    _apply_hold(
        session, principal, kind="naan", key=naan,
        days=hold_days, reason=hold_reason, release=hold_release,
    )
    session.commit()
    return _redirect(f"/admin/naan/{naan}?saved=1")


def _apply_hold(session, principal, *, kind, key, days: int, reason: str, release: str):
    """画面のフォームから保留を掛ける／外す。**CLI と同じ `admin_ops` を呼ぶ。**

    日数が 0 なら何もしない——保存のたびに「掛け直す」ことになると、
    期限が延び続けて恒久になる。
    """
    if release:
        ops.release_hold(session, principal, kind=kind, key=key)
    elif days:
        ops.set_hold(
            session, principal, kind=kind, key=key,
            until=datetime.now(UTC) + timedelta(days=days),
            reason=reason.strip(), max_days=get_settings().hold_max_days,
        )


@router.get("/manager/new", response_class=HTMLResponse)
def manager_new(request: Request, principal: AdminPrincipal, session: Db):
    if not principal.is_naan_wide:
        raise Forbidden("組織のオンボードは NAAN 単位以上の権限が要る")
    return _page(
        request, principal, "manager_form.html", "overview",
        manager=None, naans=_visible_naans(session, principal), levels=list(CommitmentLevel),
        mechanisms=ops.MECHANISMS, scopes=authz.SCOPES,
    )


@router.post("/manager/new")
def manager_create(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    naan: Annotated[str, Form()],
    name: Annotated[str, Form()],
    shoulder: Annotated[str, Form()],
    commitment: Annotated[str, Form()] = "",
    quota: Annotated[str, Form()] = "",
    allowed_auth: Annotated[list[str], Form()] = None,
    self_register: Annotated[str, Form()] = "",
    max_scopes: Annotated[list[str], Form()] = None,
    policy: Annotated[str, Form()] = "",
):
    m, _ = ops.onboard_manager(
        session, principal, naan=naan, name=name.strip(), shoulder=shoulder.strip(),
        commitment_level=commitment,
        quota_per_day=int(quota) if quota.strip() else None,
    )
    session.flush()
    # **迎える時点で制限を決められるようにする。** 後から掛け直す運用にすると、
    # 必ず掛け忘れが残る。
    if policy:
        ops.set_org_policy(
            session, principal, manager_id=m.id,
            mechanisms=list(allowed_auth or []),
            may_self_register=bool(self_register),
            max_scopes=list(max_scopes or []),
        )
    session.commit()
    return _redirect(f"/admin/manager/{m.id}")


@router.get("/manager/{manager_id}", response_class=HTMLResponse)
def manager_edit(request: Request, principal: AdminPrincipal, session: Db, manager_id: int):
    m = session.get(Manager, manager_id)
    if m is None:
        raise Forbidden("この組織はこの主体の範囲外")
    ops.require_manager(session, principal, m)
    return _page(
        request, principal, "manager_form.html", "overview",
        manager=m, naans=[], levels=list(CommitmentLevel),
        mechanisms=ops.MECHANISMS, scopes=authz.SCOPES,
        # **NAAN 側で既に絞られている分を見せる。** 見せないと、組織側で
        # 選んだのに効かない項目が出て、設定が効いていないように見える。
        naan_policy=ops.policy_for(session.get(Naan, m.naan), None),
    )


@router.post("/manager/{manager_id}")
def manager_save(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    manager_id: int,
    commitment: Annotated[str, Form()] = "",
    quota: Annotated[str, Form()] = "",
    allowed_auth: Annotated[list[str], Form()] = None,
    self_register: Annotated[str, Form()] = "",
    max_scopes: Annotated[list[str], Form()] = None,
    policy: Annotated[str, Form()] = "",
):
    """**約束は組織自身のもの**なので、組織管理者も自組織の水準を変えられる。

    採番上限はそうではない（配った側が課すもの）。判定は `admin_ops` 側にある。
    """
    if commitment:
        ops.set_commitment(session, principal, manager_id=manager_id, level=commitment)
    if principal.is_naan_wide:
        ops.set_quota(
            session, principal, manager_id=manager_id,
            quota_per_day=int(quota) if quota.strip() else None,
        )
        # `policy` はこのフォームが制限欄を出したという印。**出していない画面から
        # 送られた空値で、既存の制限を消さないため。**
        if policy:
            ops.set_org_policy(
                session, principal, manager_id=manager_id,
                mechanisms=list(allowed_auth or []),
                may_self_register=bool(self_register),
                max_scopes=list(max_scopes or []),
            )
    session.commit()
    return _redirect(f"/admin/manager/{manager_id}?saved=1")


@router.get("/shoulder/new", response_class=HTMLResponse)
def shoulder_new(request: Request, principal: AdminPrincipal, session: Db):
    if not principal.is_naan_wide:
        raise Forbidden("shoulder の切り出しは NAAN 単位以上の権限が要る")
    return _page(
        request, principal, "shoulder_form.html", "overview",
        shoulder=None, naans=_visible_naans(session, principal),
        statuses=list(ShoulderStatus),
    )


@router.post("/shoulder/new")
def shoulder_create(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    naan: Annotated[str, Form()],
    shoulder: Annotated[str, Form()],
    manager_id: Annotated[str, Form()] = "",
    reserve: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
):
    sh = ops.add_shoulder(
        session, principal, naan=naan, shoulder=shoulder.strip(),
        manager_id=int(manager_id) if manager_id.strip() else None,
        status="reserved" if reserve else "active", note=note.strip(),
    )
    session.commit()
    return _redirect(f"/admin/shoulder/{sh.id}")


@router.get("/shoulder/{shoulder_id}", response_class=HTMLResponse)
def shoulder_edit(request: Request, principal: AdminPrincipal, session: Db, shoulder_id: int):
    sh = session.get(Shoulder, shoulder_id)
    if sh is None or not principal.reaches_naan(sh.naan):
        raise Forbidden("この shoulder はこの主体の範囲外")
    return _page(
        request, principal, "shoulder_form.html", "overview",
        shoulder=sh, naans=[], statuses=list(ShoulderStatus),
        hold_max=get_settings().hold_max_days,
    )


@router.post("/shoulder/{shoulder_id}")
def shoulder_save(
    request: Request,
    principal: AdminPrincipal,
    session: Db,
    shoulder_id: int,
    status: Annotated[str, Form()] = "",
    minter: Annotated[str, Form()] = "",
    redirect: Annotated[str, Form()] = "",
    note: Annotated[str, Form()] = "",
    hold_days: Annotated[int, Form()] = 0,
    hold_reason: Annotated[str, Form()] = "",
    hold_release: Annotated[str, Form()] = "",
):
    """**retired からは戻せない。** その判定は `admin_ops` 側が持っている。"""
    sh = session.get(Shoulder, shoulder_id)
    if sh is None:
        raise Forbidden("この shoulder はこの主体の範囲外")
    if status and status != sh.status:
        ops.set_shoulder_status(
            session, principal, shoulder_id=shoulder_id, status=status,
            minter=minter.strip(), note=note.strip(),
        )
    if redirect.strip() != sh.redirect:
        ops.set_shoulder_redirect(
            session, principal, shoulder_id=shoulder_id, redirect=redirect.strip()
        )
    _apply_hold(
        session, principal, kind="shoulder", key=shoulder_id,
        days=hold_days, reason=hold_reason, release=hold_release,
    )
    session.commit()
    return _redirect(f"/admin/shoulder/{shoulder_id}?saved=1")




# ------------------------------------------------------------ 保留中の転送
#
# **期限つきでも、目に見えないと恒久化する。** 掛けた人が忘れても、一覧に
# 残っていれば誰かが気づく。


@router.get("/holds", response_class=HTMLResponse)
def holds(request: Request, principal: AdminPrincipal, session: Db):
    """今かかっている保留を、層をまたいで 1 枚に並べる。"""
    return _page(request, principal, "holds.html", "holds", holds=ops.held(session, principal))
