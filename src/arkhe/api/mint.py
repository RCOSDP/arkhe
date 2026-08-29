"""採番・更新の API。**shoulder は主体から引き、リクエストでは広げられない。**

到達範囲の判定は `domain.authz` が一手に引き受ける。ここは HTTP の形を整えるだけ。
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import select

from arkhe.api.schemas import (
    ArkOut,
    BulkMintIn,
    BulkMintOut,
    BulkQueryIn,
    BulkQueryOut,
    BulkUpdateIn,
    BulkUpdateOut,
    MintIn,
    RegisterIn,
    TombstoneIn,
    UpdateIn,
)
from arkhe.arkspec.naming import (
    ArkParseError,
    ark_key,
    normalize_structural,
    parse_ark,
    strip_hyphens,
)
from arkhe.auth.deps import Config, CurrentPrincipal, Db
from arkhe.db.models import Ark, MintReceipt
from arkhe.domain import authz, minting

router = APIRouter(prefix="/api", tags=["ark"])


def _key(raw: str) -> str:
    """`ark:/99999/xyz` でも `99999/xyz` でも受ける。

    **解決側と同じ正規化を通す。** ここだけ素通しにすると、`…/x/` や `…/x..v` を
    送ったクライアントが「同じ ARK」を更新できず 404 になる。
    """
    try:
        p = parse_ark(raw if raw.lower().startswith(("ark:", "http")) else f"ark:/{raw}")
    except ArkParseError as exc:
        raise authz.Invalid({"ark": str(exc)}) from exc
    return ark_key(p.naan, strip_hyphens(normalize_structural(p.name)))


def _replay(session, principal, request_id: str) -> Ark | None:
    """F4: 同じ `request_id` の採番が既にあれば、その ARK を返す。"""
    if not request_id:
        return None
    key = session.scalar(
        select(MintReceipt.ark).where(
            MintReceipt.client_id == principal.client_id,
            MintReceipt.request_id == request_id,
        )
    )
    return session.get(Ark, key) if key else None


def _keep_receipt(session, principal, request_id: str, ark: Ark) -> None:
    """F4: 控えを残す。**採番と同じトランザクションで**——別にすると、控えを書く前に
    落ちたときに「採番したが再送で二重に採番される」が起きる。"""
    if request_id:
        session.add(
            MintReceipt(client_id=principal.client_id, request_id=request_id, ark=ark.ark)
        )


def _apply(ark: Ark, data: dict, principal) -> Ark:
    for field, value in data.items():
        if field == "ark":
            continue
        setattr(ark, "metadata_" if field == "metadata" else field, value)
    ark.updated_by = principal.client_id
    return ark


# ------------------------------------------------------------------- 採番


@router.post("/mint", response_model=ArkOut, status_code=201)
def mint(body: MintIn, principal: CurrentPrincipal, session: Db, response: Response):
    authz.require_scope(principal, "ark:mint")
    # F4: **再送なら採番しない。** 応答が失われただけのときに番号を増やさない。
    if (existing := _replay(session, principal, body.request_id)) is not None:
        response.status_code = 200
        return ArkOut.of(existing)
    shoulder = authz.shoulder_for(session, principal, body.shoulder or None)
    authz.assert_shoulder_mintable(shoulder)
    authz.assert_within_quota(session, principal)
    ark, _ = minting.mint(
        session, shoulder=shoulder, created_by=principal.client_id, **body.writable()
    )
    _keep_receipt(session, principal, body.request_id, ark)
    authz.audit(session, principal, "mint", ark.ark)
    session.commit()
    return ArkOut.of(ark)


@router.post("/mint/bulk", response_model=BulkMintOut, status_code=201)
def bulk_mint(
    body: BulkMintIn, principal: CurrentPrincipal, session: Db, cfg: Config, response: Response
):
    authz.require_scope(principal, "ark:mint")
    rows = body.data
    if len(rows) > cfg.bulk_limit:
        raise authz.Invalid({"data": f"1 リクエストは {cfg.bulk_limit} 件まで"})

    # F4: **既に採番済みの行は飛ばす。** 切れた塊をそのまま再送できるようにする。
    wanted = {r.request_id for r in rows if r.request_id}
    replayed: dict[str, Ark] = {}
    if wanted:
        for rid, key in session.execute(
            select(MintReceipt.request_id, MintReceipt.ark).where(
                MintReceipt.client_id == principal.client_id,
                MintReceipt.request_id.in_(wanted),
            )
        ).all():
            replayed[rid] = session.get(Ark, key)

    fresh = [r for r in rows if r.request_id not in replayed]
    # 到達範囲の検証を**先に全件済ませる**（1 件でも範囲外なら何も作らない）。
    shoulders = [authz.shoulder_for(session, principal, r.shoulder or None) for r in fresh]
    for sh in shoulders:
        authz.assert_shoulder_mintable(sh)
    authz.assert_within_quota(session, principal, len(fresh))

    minted: dict[int, Ark] = {}
    for sh, row in zip(shoulders, fresh, strict=True):
        ark, _ = minting.mint(
            session, shoulder=sh, created_by=principal.client_id, **row.writable()
        )
        _keep_receipt(session, principal, row.request_id, ark)
        minted[id(row)] = ark
    authz.audit(session, principal, "bulk_mint", count=len(minted))
    session.commit()

    # **入力の順序で返す。** 再送ぶんと新規ぶんが混ざるので、呼び出し側が
    # 突き合わせられるように並びを保つ。
    made = [replayed.get(r.request_id) or minted[id(r)] for r in rows]
    if not minted:
        response.status_code = 200
    return BulkMintOut(
        minted=[ArkOut.of(a) for a in made], created=len(minted), replayed=len(made) - len(minted)
    )


@router.post("/register", response_model=ArkOut, status_code=201)
def register(body: RegisterIn, principal: CurrentPrincipal, session: Db):
    """B4: **既存 ARK に修飾子を付けた行を登録する。**

    既定では suffix passthrough が任意の深さを賄う。この口は**その既定を 1 点だけ
    上書きする**ためにある——「このサブツリーだけ別ストレージ」「この変換版だけ別の所在」。

    **`ark:mint` を要求する。** 採番ではないが、**新しく解決可能な識別子が増える**
    ので、更新権限しか持たない主体に渡してはいけない。
    """
    authz.require_scope(principal, "ark:mint")
    base = authz.fetch_for_update(session, principal, [_key(body.ark)]).popitem()[1]
    authz.assert_may_touch(session, principal, base)
    authz.assert_shoulder_mintable(base.shoulder)
    authz.assert_within_quota(session, principal)
    try:
        ark = minting.register_qualified(
            session,
            base=base,
            qualifier=body.qualifier,
            created_by=principal.client_id,
            **body.writable(),
        )
    except (minting.AlreadyRegistered, ValueError) as exc:
        raise authz.Invalid({"qualifier": str(exc)}) from exc
    authz.audit(session, principal, "register_qualified", ark.ark)
    session.commit()
    return ArkOut.of(ark)


# ------------------------------------------------------------------- 更新


@router.put("/update", response_model=ArkOut)
def update(body: UpdateIn, principal: CurrentPrincipal, session: Db):
    """既存 ARK を更新する。**対象の shoulder の manager を照合する**（M3）。"""
    authz.require_scope(principal, "ark:update")
    ark = authz.fetch_for_update(session, principal, [_key(body.ark)]).popitem()[1]
    authz.assert_may_touch(session, principal, ark)
    before = ark.url
    _apply(ark, body.model_dump(), principal)
    # **行き先の履歴は誰が行っても残す**（監査は NAAN 単位以上しか残さない）。
    authz.record_change(session, principal, ark, action="update", before_url=before)
    authz.audit(session, principal, "update", ark.ark)
    session.commit()
    return ArkOut.of(ark)


@router.put("/update/bulk", response_model=BulkUpdateOut)
def bulk_update(body: BulkUpdateIn, principal: CurrentPrincipal, session: Db, cfg: Config):
    """M5: **辞書で引き当て、部分適用しない。**"""
    authz.require_scope(principal, "ark:update")
    rows = body.data
    if len(rows) > cfg.bulk_limit:
        raise authz.Invalid({"data": f"1 リクエストは {cfg.bulk_limit} 件まで"})
    keys = [_key(r.ark) for r in rows]
    found = authz.fetch_for_update(session, principal, keys)  # 欠けが 1 件でもあれば 404
    for key, row in zip(keys, rows, strict=True):
        ark = found[key]
        authz.assert_may_touch(session, principal, ark)
        before = ark.url
        _apply(ark, row.model_dump(), principal)
        authz.record_change(session, principal, ark, action="update", before_url=before)
    authz.audit(session, principal, "bulk_update", count=len(rows))
    session.commit()
    return BulkUpdateOut(updated=len(rows))


@router.put("/tombstone", response_model=ArkOut)
def tombstone(body: TombstoneIn, principal: CurrentPrincipal, session: Db):
    """**対象が失われたと宣言する。** ARK は削除しない。

    `NR`（No Re-assignment）を宣言している以上、識別子は消せない。消せるのは
    対象への到達性だけで、**識別子とメタデータは残る**。

    **scope を `ark:update` と分けてある。** 墓碑化は「どこにあるか」ではなく
    「もう無い」という宣言で、意味も影響も違う。取り消しにくく、公開されると
    信頼に関わるので、投入バッチのような日常の書き手には渡さない。
    """
    authz.require_scope(principal, "ark:tombstone")
    ark = authz.fetch_for_update(session, principal, [_key(body.ark)]).popitem()[1]
    authz.assert_may_touch(session, principal, ark)
    before = ark.url
    # url が空なら、リゾルバが記述そのものを返す（D6 と同じ経路）。
    ark.url = body.url
    if body.commitment:
        ark.commitment = body.commitment
    ark.updated_by = principal.client_id
    authz.record_change(session, principal, ark, action="tombstone", before_url=before)
    authz.audit(session, principal, "tombstone", ark.ark)
    session.commit()
    return ArkOut.of(ark)


@router.post("/query", response_model=BulkQueryOut)
def bulk_query(body: BulkQueryIn, principal: CurrentPrincipal, session: Db, cfg: Config):
    """M4: **読み取りも到達範囲に絞る**（arklet は認可を一切していなかった）。"""
    authz.require_scope(principal, "ark:read")
    keys = [_key(a) for a in body.data[: cfg.bulk_limit]]
    arks = authz.visible_arks(session, principal, keys)
    return BulkQueryOut(data=[ArkOut.of(a) for a in arks])
