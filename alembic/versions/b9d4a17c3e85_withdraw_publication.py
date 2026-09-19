"""Allow a publication to be withdrawn

Revision ID: b9d4a17c3e85
Revises: a7c3e51d9f20
Create Date: 2026-09-18

In 0.3.0 published_at was one-way: from the moment something was published there was no
way back. That was reversed because the decision to take something down belongs to the
organisation that holds the object. Whoever notices that something should never have been
published is the depositor rather than the RA, and until a request travels to the RA and
back, it stays out.

published_at now means "published right now" and goes back and forth, so
first_published_at is added: when it was first published. That one is one-way and is
never cleared. A name that went out into the world does not become one that never did,
because someone may have cited it in the meantime and there is no way to know from here.

This column decides how much ceremony an operation takes. Withdrawing a reservation that
was never published is light; a name that was published requires a reason and the ARK
typed again. The weight follows the name's history rather than the caller's tier, because
what matters is what is being lost, not who is deleting it.

Existing published rows copy published_at across. Publication could not be undone until
now, so every row with a published_at is in fact still published, and that is when it
was first published.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9d4a17c3e85"
down_revision: str | Sequence[str] | None = "a7c3e51d9f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ark", sa.Column("first_published_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Publication could not be undone until now, so a row with a published_at was
    # first published at that moment. Leaving this out would make every existing
    # published ARK count as never published, deletable with no reason and no
    # confirmation.
    op.execute(
        "UPDATE ark SET first_published_at = published_at WHERE published_at IS NOT NULL"
    )


def downgrade() -> None:
    # Reverting loses the fact that something was published. What is published now can
    # be recovered from published_at, but what has been withdrawn cannot: the earlier
    # schema has no column for that state, since 0.3.0 had no withdrawal.
    op.drop_column("ark", "first_published_at")
