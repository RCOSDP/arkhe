"""Accept the lengths the specification requires

Revision ID: d2a7f4b81c63
Revises: a3f1c9e2d570
Create Date: 2026-09-07

Two minimums that draft-kunze-ark-42 requires of receiving implementations were below
what the columns allowed.

  §2.3  "For received ARKs, implementations must support a minimum NAAN length
        of **16 octets**."                      naan allowed 10
  §3.1  "implementations must support a minimum length of **255 octets** for the
        string composed of the Base Name plus Qualifier."
                                                 assigned_name allowed 100

The 10 for a NAAN had a reason, but not one that applies to this implementation.
arklet passed NAANs through int() and had to guard the conversion by length, and that
constant was carried over. N2 settles that arkhe keeps and compares a NAAN as a string
and never makes it an integer, so that ark:/099999/... and ark:/99999/... stay different,
which leaves no conversion to guard.

ark (<naan>/<name>) follows from both minimums: 16 + 1 + 255 = 272. The columns that
reference it, mint_receipt.ark and ark_change.ark, and audit_event.target, which holds
ARKs, are widened to match. Widening only some of them would make which values fit
depend on the route.

On PostgreSQL this widens a varchar, which rewrites no table and rebuilds no index: it
is a change to metadata alone.

On SQLite nothing happens. That database ignores varchar lengths, so there is no reason
to risk rebuilding tables with primary and foreign keys in batch mode.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2a7f4b81c63"
down_revision: str | Sequence[str] | None = "a3f1c9e2d570"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (table, column, from, to). Every table holding a NAAN is listed: with a referencing
#: column left narrow, an organisation or an ARK using a wider NAAN could not be
#: created.
_WIDENED = [
    ("naan", "naan", 10, 16),
    ("manager", "naan", 10, 16),
    ("shoulder", "naan", 10, 16),
    ("ark", "naan", 10, 16),
    ("client", "naan", 10, 16),
    ("ark", "ark", 200, 272),
    ("ark", "assigned_name", 100, 255),
    ("mint_receipt", "ark", 200, 272),
    ("ark_change", "ark", 200, 272),
    ("audit_event", "target", 200, 272),
]


def _resize(pairs) -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    for table, column, old, new in pairs:
        op.alter_column(
            table,
            column,
            existing_type=sa.String(length=old),
            type_=sa.String(length=new),
            existing_nullable=False,
        )


def upgrade() -> None:
    _resize(_WIDENED)


def downgrade() -> None:
    # Narrowing would truncate whatever no longer fits. If any ARK was minted after
    # the widening, PostgreSQL refuses and stops, which beats breaking identifiers
    # silently.
    _resize([(t, c, new, old) for t, c, old, new in reversed(_WIDENED)])
