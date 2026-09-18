"""台帳の統計。**数えるのはここだけ。**

画面・CLI・API が別々に集計を書くと、**同じ「件数」が場所によって違う**という
いちばん質の悪いずれが起きる。絞り込みを `queries.py` に置いたのと同じ理由で、
数え方もここに 1 つだけ置く。

**到達範囲は `queries.visible_arks` をそのまま通す。** 統計は合計しか返さないが、
**合計は在ることを漏らす**——他組織の ARK が何件あるかは、その組織の規模であり、
こちらが教えてよい事実ではない。認可を書き直さず、一覧と同じ式に重ねる。

**数え方の費用について正直に書いておく。** ここは `COUNT(*)` を使うので、費用は
行数に比例する（一覧が `COUNT` を避けて「1 件多く取る」で済ませているのと対照的
である——あちらが欲しいのは有無だけで、こちらは数そのものが目的だから）。
100 万件の台帳で 1 回あたり数百 ms を見込む。**呼ぶ側が毎秒叩く口ではない。**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arkhe.auth.principal import Principal
from arkhe.db.models import (
    Ark,
    Client,
    Manager,
    Naan,
    Shoulder,
    ShoulderStatus,
    WithdrawnName,
)
from arkhe.domain.queries import narrow_arks, visible_arks

#: 採番の勢いを見る窓。**日・週・月**で、運用の相談で実際に使う単位に合わせた。
WINDOWS = (("24h", 1), ("7d", 7), ("30d", 30))


@dataclass
class ShoulderStat:
    """shoulder 1 つぶん。**台帳が組織されている単位**なので、内訳はこれで採る。"""

    naan: str
    shoulder: str
    status: str
    organisation: str
    arks: int
    public: int
    reserved: int


@dataclass
class LedgerStats:
    """**この主体から見た台帳。** 届かないものは 1 件も入っていない。"""

    scope: str                       # system / naan / organisation
    naans: int
    arks: int
    public: int
    reserved: int
    withdrawn: int
    withdrawn_after_publication: int
    shoulders: dict[str, int] = field(default_factory=dict)
    organisations: int = 0
    organisations_active: int = 0
    clients: int = 0
    clients_active: int = 0
    holds: dict[str, int] = field(default_factory=dict)
    minted: dict[str, int] = field(default_factory=dict)
    first_mint: datetime | None = None
    last_mint: datetime | None = None
    by_shoulder: list[ShoulderStat] = field(default_factory=list)


def _reach(p: Principal) -> str:
    if p.is_system:
        return "system"
    return "naan" if p.is_naan_wide else "organisation"


def ledger_stats(
    session: Session, p: Principal, *, naan: str = "", org: str = "", now: datetime | None = None
) -> LedgerStats:
    """**この主体に見えている範囲を数える。**

    `naan` と `org` は一覧と同じ絞り込み（`narrow_arks`）を重ねるだけで、
    **範囲を広げる手段にはならない**——届かない NAAN を指定しても 0 が返る。
    """
    now = now or datetime.now(UTC)
    base = narrow_arks(visible_arks(p), naan=naan, org=org)

    # **公開の別は 1 回の走査で採る。** 2 回数えると、その間に増えた分だけ
    # 合計と内訳が食い違う——**足して合わない統計は、読む人の信頼を失う。**
    counts = dict(
        session.execute(
            base.with_only_columns(Ark.published_at.is_(None), func.count())
            .order_by(None)
            .group_by(Ark.published_at.is_(None))
        ).all()
    )
    reserved = counts.get(True, 0)
    public = counts.get(False, 0)

    span = session.execute(
        base.with_only_columns(func.min(Ark.created_at), func.max(Ark.created_at)).order_by(None)
    ).one()

    minted = {}
    for label, days in WINDOWS:
        minted[label] = session.scalar(
            base.with_only_columns(func.count())
            .order_by(None)
            .where(Ark.created_at >= now - timedelta(days=days))
        ) or 0

    stats = LedgerStats(
        scope=_reach(p),
        naans=_count_naans(session, p),
        arks=public + reserved,
        public=public,
        reserved=reserved,
        withdrawn=0,
        withdrawn_after_publication=0,
        minted=minted,
        first_mint=span[0],
        last_mint=span[1],
    )
    _withdrawn(session, p, stats)
    _shoulders(session, p, stats)
    _people(session, p, stats)
    _holds(session, p, stats)
    return stats


def _count_naans(session: Session, p: Principal) -> int:
    stmt = select(func.count()).select_from(Naan)
    if not p.is_system:
        stmt = stmt.where(Naan.naan == p.naan)
    return session.scalar(stmt) or 0


def _visible_shoulders(p: Principal):
    """**採番に使える範囲と同じ絞り方。** 認可を 2 度書かない。"""
    stmt = select(Shoulder)
    if not p.is_system:
        stmt = stmt.where(Shoulder.naan == p.naan)
    if not p.is_naan_wide:
        if p.shoulder_id is not None:
            stmt = stmt.where(Shoulder.id == p.shoulder_id)
        else:
            stmt = stmt.where(Shoulder.manager_id == p.manager_id)
    return stmt


def _withdrawn(session: Session, p: Principal, out: LedgerStats) -> None:
    """取り下げた名前。**公開後に消したものを分けて数える。**

    予約を引っ込めたのと、世に出した名前を消したのとでは意味がまるで違う
    ——後者はこの体系が守ると言っているものを破った回数である。**見えない
    ところに置いてはいけない数字。**
    """
    stmt = select(WithdrawnName.published_at.is_not(None), func.count()).group_by(
        WithdrawnName.published_at.is_not(None)
    )
    if not p.is_system:
        stmt = stmt.where(WithdrawnName.naan == p.naan)
    if not p.is_naan_wide:
        stmt = stmt.where(
            WithdrawnName.shoulder_id.in_(_visible_shoulders(p).with_only_columns(Shoulder.id))
        )
    rows = dict(session.execute(stmt).all())
    out.withdrawn_after_publication = rows.get(True, 0)
    out.withdrawn = rows.get(True, 0) + rows.get(False, 0)


def _shoulders(session: Session, p: Principal, out: LedgerStats) -> None:
    rows = session.execute(
        _visible_shoulders(p).with_only_columns(Shoulder.status, func.count()).group_by(
            Shoulder.status
        )
    ).all()
    seen = dict(rows)
    # **0 の状態も出す。** 「delegated が 0 件」と「delegated という状態を知らない」は
    # 読む側にとって別のことである。
    out.shoulders = {s.value: seen.get(s.value, 0) for s in ShoulderStatus}

    # 内訳。**shoulder は台帳が組織されている単位**で、数もたかが知れている。
    per = dict(
        session.execute(
            visible_arks(p)
            .with_only_columns(Ark.shoulder_id, func.count())
            .order_by(None)
            .group_by(Ark.shoulder_id)
        ).all()
    )
    pub = dict(
        session.execute(
            visible_arks(p)
            .with_only_columns(Ark.shoulder_id, func.count())
            .order_by(None)
            .where(Ark.published_at.is_not(None))
            .group_by(Ark.shoulder_id)
        ).all()
    )
    shoulders = session.scalars(
        _visible_shoulders(p).order_by(Shoulder.naan, Shoulder.shoulder)
    ).all()
    names = dict(session.execute(select(Manager.id, Manager.name)).all())
    out.by_shoulder = [
        ShoulderStat(
            naan=sh.naan,
            shoulder=sh.shoulder,
            status=sh.status,
            organisation=names.get(sh.manager_id, ""),
            arks=per.get(sh.id, 0),
            public=pub.get(sh.id, 0),
            reserved=per.get(sh.id, 0) - pub.get(sh.id, 0),
        )
        for sh in shoulders
    ]


def _people(session: Session, p: Principal, out: LedgerStats) -> None:
    m = select(Manager.active, func.count()).group_by(Manager.active)
    c = select(Client.active, func.count()).group_by(Client.active)
    if not p.is_system:
        m = m.where(Manager.naan == p.naan)
        c = c.where(Client.naan == p.naan)
    if not p.is_naan_wide:
        m = m.where(Manager.id == p.manager_id)
        c = c.where(Client.manager_id == p.manager_id)
    mr, cr = dict(session.execute(m).all()), dict(session.execute(c).all())
    out.organisations = sum(mr.values())
    out.organisations_active = mr.get(True, 0)
    out.clients = sum(cr.values())
    out.clients_active = cr.get(True, 0)


def _holds(session: Session, p: Principal, out: LedgerStats) -> None:
    """**今かかっている保留だけ。** 期限切れは解決のたびに時計で判定されるので、
    ここでも同じく「今」で見る——バッチで戻していない以上、行は残っている。
    """
    now = datetime.now(UTC)
    out.holds = {
        "ark": session.scalar(
            visible_arks(p)
            .with_only_columns(func.count())
            .order_by(None)
            .where(Ark.hold_until > now)
        ) or 0,
        "shoulder": session.scalar(
            _visible_shoulders(p)
            .with_only_columns(func.count())
            .where(Shoulder.hold_until > now)
        ) or 0,
        "naan": session.scalar(
            select(func.count()).select_from(Naan).where(
                Naan.hold_until > now,
                *([] if p.is_system else [Naan.naan == p.naan]),
            )
        ) or 0,
    }
