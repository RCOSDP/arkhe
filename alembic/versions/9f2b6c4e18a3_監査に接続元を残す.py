"""監査に接続元を残す

Revision ID: 9f2b6c4e18a3
Revises: 7c1a4f0b3e92
Create Date: 2026-08-29

**前段を信じた結果**であって、証拠ではない。`ARKHE_TRUSTED_PROXIES` が 0 なら
直接の接続元そのもの、n なら `X-Forwarded-For` の右から n 番目。

既存の行は空のまま（そのとき記録していないものを、後から埋めない）。
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
