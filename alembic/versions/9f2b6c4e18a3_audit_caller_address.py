"""Keep the caller's address in the audit log

Revision ID: 9f2b6c4e18a3
Revises: 7c1a4f0b3e92
Create Date: 2026-08-29

It is the result of trusting whatever is in front, not evidence. With
ARKHE_TRUSTED_PROXIES at 0 it is the direct peer; with n, it is the nth entry from the
right of X-Forwarded-For.

Existing rows stay empty: what was not recorded at the time is not filled in later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9f2b6c4e18a3"
down_revision: str | Sequence[str] | None = "7c1a4f0b3e92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_event",
        sa.Column("ip", sa.String(length=45), nullable=False, server_default=""),
    )
    op.create_index("ix_audit_event_ip", "audit_event", ["ip"])


def downgrade() -> None:
    op.drop_index("ix_audit_event_ip", table_name="audit_event")
    op.drop_column("audit_event", "ip")
