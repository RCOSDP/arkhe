"""Keep the history of an ARK's target

Revision ID: c4e70a91d5b6
Revises: 9f2b6c4e18a3
Create Date: 2026-08-29

Without it, where something used to point cannot be recovered. A scheme that declares
NR and says an identifier does not change has to be able to show what changed, when, and
who changed it; otherwise nobody outside can verify the promise.

It is kept separately from the audit log. The audit log keeps only operations at NAAN
level and above, while minting and repointing are done by organisations, so it would
miss the changes that matter.

Existing ARKs have no history. What was not recorded at the time cannot be invented
afterwards.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e70a91d5b6"
down_revision: str | Sequence[str] | None = "9f2b6c4e18a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ark_change",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ark", sa.String(length=200), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("before_url", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("after_url", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("by", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("ip", sa.String(length=45), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["ark"], ["ark.ark"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ark_change_ark", "ark_change", ["ark"])
    op.create_index("ix_ark_change_at", "ark_change", ["at"])
    op.create_index("ix_ark_change_by", "ark_change", ["by"])


def downgrade() -> None:
    op.drop_table("ark_change")
