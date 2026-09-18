"""台帳の統計。**数えるのはここだけ。**

画面・CLI・API が別々に集計を書くと、**同じ「件数」が場所によって違う**という
いちばん質の悪いずれが起きる。絞り込みを `queries.py` に置いたのと同じ理由で、
数え方もここに 1 つだけ置く。

**到達範囲は `queries.visible_arks` をそのまま通す。** 統計は合計しか返さないが、
**合計は在ることを漏らす**——他組織の ARK が何件あるかは、その組織の規模であり、
こちらが教えてよい事実ではない。認可を書き直さず、一覧と同じ式に重ねる。

## 数え方の費用

**費用は行数に比例する。** 一覧が `COUNT` を避けて「1 件多く取る」で済ませている
のと対照的で——あちらが欲しいのは有無だけ、こちらは数そのものが目的だから、
走査そのものは避けようがない。

**避けようがないなら、回数を減らす。** 公開の別・最初と最後・3 つの窓・保留は
どれも同じ絞り込みへの集計なので、条件つき集計（`FILTER`）で **1 回の走査に
畳んである**。shoulder ごとの内訳も、合計と公開を 1 回で採る。結果として
**大きい `ark` 表を読むのは 2 回だけ**（素朴に書くと 7 回になる）。

畳むのは速さのためだけではない。**別々に数えると、その間に増えた分だけ数どうしが
食い違う**——24h が 7d を上回る、公開が合計を超える、といった見え方になる。
**足して合わない統計は、読む人の信頼を失う。**

数える列は明示してある（`count(ark.ark)`）。実測は 30 万件で約 110 ms
（SQLite、手元）。**呼ぶ側が毎秒叩く口ではない。**
"""

from __future__ import annotations

import hashlib
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

    # **大きい表は 1 回しか読まない。**
    #
    # 公開の別・最初と最後・3 つの窓・保留は、**どれも同じ絞り込みへの集計**である。
    # 別々に数えると `ark` を 5 回走査するうえ、**その間に増えた分だけ数どうしが
    # 食い違う**——24h が 7d を上回る、公開が合計を超える、といった見え方になる。
    # 条件つき集計（`FILTER`）で 1 つのスナップショットから全部出す。
    since = {label: now - timedelta(days=days) for label, days in WINDOWS}
    agg = session.execute(
        base.with_only_columns(
            func.count(Ark.ark).label("total"),
            func.count(Ark.ark).filter(Ark.published_at.is_not(None)).label("public"),
            func.min(Ark.created_at).label("first"),
            func.max(Ark.created_at).label("last"),
            func.count(Ark.ark).filter(Ark.hold_until > now).label("held"),
            *[
                func.count(Ark.ark).filter(Ark.created_at >= since[label]).label(label)
                for label, _ in WINDOWS
            ],
        ).order_by(None)
    ).one()

    stats = LedgerStats(
        scope=_reach(p),
        naans=_count_naans(session, p),
        arks=agg.total,
        public=agg.public,
        reserved=agg.total - agg.public,
        withdrawn=0,
        withdrawn_after_publication=0,
        minted={label: getattr(agg, label) for label, _ in WINDOWS},
        first_mint=agg.first,
        last_mint=agg.last,
    )
    _withdrawn(session, p, stats)
    _shoulders(session, p, stats)
    _people(session, p, stats)
    _holds(session, p, stats, arks_held=agg.held)
    return stats


def _count_naans(session: Session, p: Principal) -> int:
    stmt = select(func.count(Naan.naan)).select_from(Naan)
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
    stmt = select(WithdrawnName.published_at.is_not(None), func.count(WithdrawnName.ark)).group_by(
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
        _visible_shoulders(p).with_only_columns(Shoulder.status, func.count(Shoulder.id)).group_by(
            Shoulder.status
        )
    ).all()
    seen = dict(rows)
    # **0 の状態も出す。** 「delegated が 0 件」と「delegated という状態を知らない」は
    # 読む側にとって別のことである。
    out.shoulders = {s.value: seen.get(s.value, 0) for s in ShoulderStatus}

    # 内訳。**shoulder は台帳が組織されている単位**で、数もたかが知れている。
    # **合計と公開を 1 回の走査で採る。** 2 度に分けると表を 2 度読むうえ、
    # その間に増えた分だけ**公開が合計を上回る**ような内訳が出る。
    # `ix_ark_shoulder_created` が効く形（shoulder_id が先頭）にしてある。
    rows = session.execute(
        visible_arks(p)
        .with_only_columns(
            Ark.shoulder_id,
            func.count(Ark.ark).label("total"),
            func.count(Ark.ark).filter(Ark.published_at.is_not(None)).label("public"),
        )
        .order_by(None)
        .group_by(Ark.shoulder_id)
    ).all()
    per = {r.shoulder_id: r.total for r in rows}
    pub = {r.shoulder_id: r.public for r in rows}
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
    m = select(Manager.active, func.count(Manager.id)).group_by(Manager.active)
    c = select(Client.active, func.count(Client.id)).group_by(Client.active)
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


def _holds(session: Session, p: Principal, out: LedgerStats, *, arks_held: int) -> None:
    """**今かかっている保留だけ。** 期限切れは解決のたびに時計で判定されるので、
    ここでも同じく「今」で見る——バッチで戻していない以上、行は残っている。

    ARK のぶんは `ledger_stats` の 1 回の走査で採ってある（**大きい表をもう一度
    読まない**）。shoulder と NAAN は小さいので、そのまま数える。
    """
    now = datetime.now(UTC)
    out.holds = {
        "ark": arks_held,
        "shoulder": session.scalar(
            _visible_shoulders(p)
            .with_only_columns(func.count(Shoulder.id))
            .where(Shoulder.hold_until > now)
        ) or 0,
        "naan": session.scalar(
            select(func.count(Naan.naan)).select_from(Naan).where(
                Naan.hold_until > now,
                *([] if p.is_system else [Naan.naan == p.naan]),
            )
        ) or 0,
    }


# --------------------------------------------------------------------------
# 復元できたことの確認
# --------------------------------------------------------------------------

#: 指紋に入れる列と、その理由。**「識別子が生きているか」を決めるものだけ**を
#: 入れる——`ark`（名前）、`url`（行き先）、`published_at`（解決するか）。
#:
#: **保留（`hold_until`）は入れない。** 期限で勝手に変わるので、差が出ても
#: 「壊れた」と読めない——**鳴りっぱなしの警報は、誰も見なくなる。**
#: 題名や記述も入れない。失われれば困るが、**識別子が別のものを指すのとは
#: 重さが違う**——混ぜると、重い差と軽い差が同じ 1 つの値に潰れる。
_ARK_COLUMNS = ("ark", "url", "published_at")


@dataclass
class Fingerprint:
    """台帳の指紋。**復元の前後で突き合わせるためだけのもの。**"""

    arks: str
    ark_count: int
    withdrawn: str
    withdrawn_count: int

    def lines(self) -> list[str]:
        return [
            f"arks       {self.arks}  {self.ark_count} rows",
            f"withdrawn  {self.withdrawn}  {self.withdrawn_count} rows",
        ]


def _digest(rows) -> tuple[str, int]:
    """並びを固定して 1 本の値にする。**数えながら流す**（全件を持たない）。"""
    h, n = hashlib.sha256(), 0
    for row in rows:
        h.update("\x1f".join("" if v is None else str(v) for v in row).encode())
        h.update(b"\x1e")
        n += 1
    return h.hexdigest()[:32], n


def ledger_fingerprint(session: Session) -> Fingerprint:
    """**台帳の指紋。復元できたことを、件数ではなく中身で確かめる。**

    件数が合うことは、確かめたことにならない——**件数が同じでも行き先が入れ替わって
    いれば、識別子は全部壊れている**。

    **2 つに分けてある。** 1 つに潰すと「どこが違うか」が消える:

      arks       いま在る名前と、その行き先と、解決するかどうか
      withdrawn  二度と採らない名前——**`NR` を守る仕掛けの片側**

    後者が消えても採番は動き続けるので、**黙って通る**。だから別に数える。

    **DB の方言に依らない。** SQL の `md5(string_agg(...))` ではなく、並びを固定して
    Python で畳む——PostgreSQL でも SQLite でも同じ値が出る。**費用は行数に比例する**
    （全件を流すので、統計より重い）。月次の検証で回すためのものであって、
    繰り返し叩く口ではない。
    """
    arks = _digest(
        session.execute(
            select(*(getattr(Ark, c) for c in _ARK_COLUMNS)).order_by(Ark.ark)
        ).yield_per(1000)
    )
    gone = _digest(
        session.execute(
            select(WithdrawnName.ark, WithdrawnName.published_at).order_by(WithdrawnName.ark)
        ).yield_per(1000)
    )
    return Fingerprint(arks=arks[0], ark_count=arks[1],
                       withdrawn=gone[0], withdrawn_count=gone[1])
