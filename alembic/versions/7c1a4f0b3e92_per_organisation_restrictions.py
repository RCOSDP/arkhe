"""Give each organisation its own restrictions

Revision ID: 7c1a4f0b3e92
Revises: 3b8e5d1c7a44
Create Date: 2026-08-29

This lets the side handing out a namespace state what the other side is trusted with
and what is limited. All three default to what happened before, so an existing ledger
behaves as it did.

  allowed_auth       how principals may get in (empty: follow the deployment default)
  may_self_register  whether the organisation may register principals (default true)
  max_scopes         the ceiling on the scopes its principals may hold (empty: none)

autogenerate kept trying to add fk_manager_default_shoulder because it really was
missing. Another migration (3b8e5d1c7a44) fixes that first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c1a4f0b3e92"
down_revision: str | Sequence[str] | None = "3b8e5d1c7a44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "manager",
        sa.Column("allowed_auth", sa.String(length=100), nullable=False, server_default=""),
    )
    op.add_column(
        "manager",
        sa.Column(
            "may_self_register", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.add_column(
        "manager",
        sa.Column("max_scopes", sa.String(length=200), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("manager", "max_scopes")
    op.drop_column("manager", "may_self_register")
    op.drop_column("manager", "allowed_auth")
