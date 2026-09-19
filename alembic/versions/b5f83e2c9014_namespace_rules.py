"""Give a namespace its own rules

Revision ID: b5f83e2c9014
Revises: c4e70a91d5b6
Create Date: 2026-08-29

The rule belongs to the NAAN and an organisation records the exception: its settings
may narrow these and never widen them.

The default lives on the NAAN because applying it per organisation does not scale:
setting the same restriction on 800 institutions one at a time is not a workable way to
run anything.

All three default to what happened before, so an existing ledger behaves as it did.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5f83e2c9014"
down_revision: str | Sequence[str] | None = "c4e70a91d5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "naan",
        sa.Column("allowed_auth", sa.String(length=100), nullable=False, server_default=""),
    )
    op.add_column(
        "naan",
        sa.Column(
            "may_self_register", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.add_column(
        "naan",
        sa.Column("max_scopes", sa.String(length=200), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("naan", "max_scopes")
    op.drop_column("naan", "may_self_register")
    op.drop_column("naan", "allowed_auth")
