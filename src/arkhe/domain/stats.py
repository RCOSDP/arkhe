"""Statistics over the ledger. All counting happens here.

If the screens, the CLI and the API each wrote their own aggregates, the same count
would differ by where it was read, which is the worst kind of drift. For the same reason
the filters live in queries.py, the counting lives here.

The reach comes from queries.visible_arks. Statistics return only totals, but a total
leaks existence: how many ARKs another organisation holds is a measure of its size, and
not ours to tell. The authorisation is not written again; it is the same query the lists
use.

What counting costs

It costs time in proportion to the number of rows. The lists avoid COUNT by fetching one
extra row, because all they need is whether there is more; here the count is the point,
so the scan cannot be avoided.

Since it cannot be avoided, it is done as few times as possible. Published against
reserved, the first and last mint, the three windows and the holds are all aggregates
over the same filter, so they are folded into one scan with conditional aggregation
(FILTER). The per-shoulder breakdown takes its total and its published count in one pass
too. In the end the large ark table is read twice, where the obvious version reads it
seven times.

Folding them is not only about speed. Counted separately, the numbers disagree by
whatever arrived in between: 24 hours exceeding 7 days, or published exceeding the
total. Statistics that do not add up lose the reader's trust.

The column being counted is named (count(ark.ark)). Measured at about 110 ms over
300,000 rows on SQLite here. This is not an endpoint to poll.
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

#: The windows minting is measured over: a day, a week and a month, which are the
#: units that come up when operators talk about it.
WINDOWS = (("24h", 1), ("7d", 7), ("30d", 30))


@dataclass
class ShoulderStat:
    """One shoulder. The ledger is organised by them, so that is how it is broken
    down."""

    naan: str
    shoulder: str
    status: str
    organisation: str
    arks: int
    public: int
    reserved: int


@dataclass
class LedgerStats:
    """The ledger as this principal sees it. Nothing out of reach is included."""

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
    #: The oldest ARK still reserved. A count cannot raise an alarm: ten reserved
    #: yesterday is ordinary, one reserved three years ago is forgotten. A backlog
    #: shows in age, not in number.
    reserved_oldest: datetime | None = None
    by_shoulder: list[ShoulderStat] = field(default_factory=list)


def _utc(dt: datetime | None) -> datetime | None:
    """Every timestamp returned carries a time zone.

    SQLite has no time zone type, so a column declared DateTime(timezone=True) comes
    back naive, while PostgreSQL returns an aware value: the type depends on the engine,
    and subtracting it raises TypeError on one of them. That is what made arkhe stat
    crash.

    Attaching UTC is not a guess: the ledger only ever writes utcnow(), so a naive value
    read back is UTC.
    """
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _reach(p: Principal) -> str:
    if p.is_system:
        return "system"
    return "naan" if p.is_naan_wide else "organisation"


def ledger_stats(
    session: Session, p: Principal, *, naan: str = "", org: str = "", now: datetime | None = None
) -> LedgerStats:
    """Count what this principal can see.

    naan and org apply the same filters the lists use (narrow_arks) and never widen the
    reach: naming a NAAN out of reach returns zero.
    """
    now = now or datetime.now(UTC)
    base = narrow_arks(visible_arks(p), naan=naan, org=org)

    # The large table is read once.
    #
    # Published against reserved, the first and last mint, the three windows and the
    # holds are all aggregates over the same filter. Counted separately they would scan
    # ark five times and disagree by whatever arrived in between: 24 hours exceeding 7
    # days, or published exceeding the total. Conditional aggregation (FILTER) takes
    # them all from one snapshot.
    since = {label: now - timedelta(days=days) for label, days in WINDOWS}
    agg = session.execute(
        base.with_only_columns(
            func.count(Ark.ark).label("total"),
            func.count(Ark.ark).filter(Ark.published_at.is_not(None)).label("public"),
            func.min(Ark.created_at).label("first"),
            func.max(Ark.created_at).label("last"),
            func.count(Ark.ark).filter(Ark.hold_until > now).label("held"),
            func.min(Ark.created_at).filter(Ark.published_at.is_(None)).label("oldest_reserved"),
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
        first_mint=_utc(agg.first),
        last_mint=_utc(agg.last),
        reserved_oldest=_utc(agg.oldest_reserved),
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
    """Narrowed exactly as what may be minted into. The authorisation is not written
    twice."""
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
    """Withdrawn names, counting separately those removed after publication.

    Pulling back a reservation and removing a name that went out into the world mean
    entirely different things: the second is the number of times this scheme broke what
    it promises. That is not a number to keep out of sight.
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
    # States with no rows are still reported. "No delegated shoulders" and "we do not
    # track delegation" are different statements to a reader.
    out.shoulders = {s.value: seen.get(s.value, 0) for s in ShoulderStatus}

    # The breakdown. The ledger is organised by shoulder, and there are not many of
    # them. The total and the published count come from one scan: two scans would read
    # the table twice and could report more published than total, by whatever arrived in
    # between. It is written so that ix_ark_shoulder_created applies, with shoulder_id
    # first.
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
    """Only the holds in force. An expiry is judged against the clock on each
    resolution, so it is judged the same way here: nothing puts the rows back, so they
    are still there.

    The ARK figure comes from the single scan in ledger_stats, so the large table is not
    read again. Shoulders and NAANs are small enough to count directly.
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
# Confirming that a restore worked
# --------------------------------------------------------------------------

#: The columns in the fingerprint, and why. Only what decides whether an identifier is
#: alive: ark (the name), url (the target) and published_at (whether it resolves).
#:
#: Holds (hold_until) are left out. They change by themselves at an expiry, so a
#: difference could not be read as damage, and an alarm that always rings stops being
#: read. Titles and descriptions are left out too: losing them matters, but not as much
#: as an identifier pointing at something else, and mixing them would collapse a serious
#: difference and a small one into one value.
_ARK_COLUMNS = ("ark", "url", "published_at")


@dataclass
class Fingerprint:
    """A fingerprint of the ledger, for comparing before and after a restore."""

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
    """Fold a fixed order into one value, counting as it streams rather than holding
    every row."""
    h, n = hashlib.sha256(), 0
    for row in rows:
        h.update("\x1f".join("" if v is None else str(v) for v in row).encode())
        h.update(b"\x1e")
        n += 1
    return h.hexdigest()[:32], n


def ledger_fingerprint(session: Session) -> Fingerprint:
    """A fingerprint of the ledger, confirming a restore by its contents rather than
    by its row count.

    Matching counts prove nothing: with the same count but swapped targets, every
    identifier is broken.

    There are two values. Collapsed into one, it would no longer say where the
    difference is:

      arks       the names that exist, their targets, and whether they resolve
      withdrawn  the names that are never minted again, which is half of how NR is kept

    Losing the second is silent, because minting keeps working without it, so it is
    counted separately.

    It does not depend on the database. Rather than md5(string_agg(...)) in SQL, the
    order is fixed and the fold happens in Python, so PostgreSQL and SQLite give the
    same value. It costs time in proportion to the number of rows, since every row is
    streamed, which makes it heavier than the statistics. It is for a monthly check, not
    for polling.
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
