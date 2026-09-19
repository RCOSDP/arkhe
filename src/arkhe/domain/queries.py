"""Filtering lists. The screens and the CLI both call this.

admin_ops holds what can be done; this holds what can be seen.

Writing the reach in two places means that fixing one leaves rows hidden on the screens
but visible in the CLI, and it is noticed only after something was seen that should not
have been. Search is the same: if the screens look at three fields and the CLI at one,
the same words give different results.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, select

from arkhe.arkspec.naming import (
    ArkParseError,
    ark_key,
    normalize_percent,
    normalize_structural,
    parse_ark,
    strip_hyphens,
)
from arkhe.auth.principal import Principal
from arkhe.db.models import Ark, Manager, Shoulder


def ark_key_from_input(raw: str) -> str:
    """Turn ark:99999/x9tn1qkq2g7, the older ark:/99999/x9tn1qkq2g7, or a bare
    99999/x9tn1qkq2g7 into the key used in the ledger.

    It goes through the same normalisation as resolution. Skipping it here would leave
    someone who sent .../x/ or .../x..v unable to reach the same ARK, and written
    separately in the screens, the CLI and the API, one of them would miss.
    """
    try:
        p = parse_ark(raw if raw.lower().startswith(("ark:", "http")) else f"ark:{raw}")
    except ArkParseError as exc:
        raise ValueError(str(exc)) from exc
    return ark_key(p.naan, strip_hyphens(normalize_structural(normalize_percent(p.name))))


def visible_arks(p: Principal) -> Select:
    """Narrow by reach.

    The system administrator sees everything, a NAAN-level principal sees that NAAN, and
    an organisation sees its own shoulders. The filter and the authorisation are not
    written separately.
    """
    stmt = select(Ark)
    if not p.is_system:
        stmt = stmt.where(Ark.naan == p.naan)
    if not p.is_naan_wide:
        # A principal pinned to a shoulder sees only that one, narrowed the same way
        # as what it may mint into.
        if p.shoulder_id is not None:
            stmt = stmt.where(Ark.shoulder_id == p.shoulder_id)
        else:
            stmt = stmt.where(
                Ark.shoulder_id.in_(
                    select(Shoulder.id).where(Shoulder.manager_id == p.manager_id)
                )
            )
    return stmt


#: The publication states that can be filtered on. The choices on the screens and the
#: CLI arguments both come from here; kept separately, one of them would gain a value
#: the other does not have.
ARK_STATES = ("public", "reserved")


def narrow_arks(
    stmt: Select, *, naan: str = "", org: str = "", q: str = "", state: str = "",
    older_than_days: int = 0,
) -> Select:
    """Add filters. This is not a way to widen the reach.

    They are applied on top of visible_arks, so naming a NAAN or an organisation out of
    reach returns nothing: a filter is never a key to something otherwise invisible.

    naan currently comes only from the CLI, since the screens filter by organisation.
    That is a difference of entrance; both go through this one query.

    state selects published or reserved rows (ARK_STATES). An unknown value is ignored
    rather than refused: answering 400 to a filter would not let anyone do more.

    older_than_days counts from minting. It is mainly for finding reserved ARKs that
    were left behind, used together with --state reserved.
    """
    if naan.strip():
        stmt = stmt.where(Ark.naan == naan.strip())
    if str(org).strip().isdigit():
        stmt = stmt.where(
            Ark.shoulder_id.in_(
                select(Shoulder.id).where(Shoulder.manager_id == int(str(org).strip()))
            )
        )
    if (want := state.strip().lower()) in ARK_STATES:
        # Reserved ARKs accumulate if nothing is done. A number that is neither
        # published nor withdrawn stays in the ledger naming nothing, so it is made
        # visible.
        stmt = stmt.where(
            Ark.published_at.is_(None) if want == "reserved" else Ark.published_at.is_not(None)
        )
    if older_than_days > 0:
        # Filter by age. It exists for reserved ARKs left behind, but it is
        # independent of state: one day someone will want published ARKs minted three
        # years ago and never touched since.
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        stmt = stmt.where(Ark.created_at < cutoff)
    term = q.strip()
    if term:
        # Search the ARK itself, the target and the title. Whoever is searching may
        # have only one of them.
        like = f"%{term}%"
        stmt = stmt.where(Ark.ark.ilike(like) | Ark.url.ilike(like) | Ark.title.ilike(like))
    return stmt


def selectable_orgs(p: Principal) -> Select:
    """The organisations offered as filters: only those within reach."""
    stmt = select(Manager).order_by(Manager.naan, Manager.name)
    if not p.is_system:
        stmt = stmt.where(Manager.naan == p.naan)
    return stmt
