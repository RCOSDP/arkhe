"""Take the empty label out of the unique constraint

Revision ID: 56e5e54db345
Revises: 85063df8430e
Create Date: 2026-08-28

An empty label means unnamed, not a name collision. Including it in the constraint
stopped one organisation having two unlabelled principals, which ruled out an ordinary
split by role, web-api, web-ui and worker, and pushed people towards sharing one
credential.

autogenerate does not compare the where clause of an index, so this is written by hand.

The where clause is passed through sa.text(). A plain string works on PostgreSQL, but
the SQLite dialect hands the expression straight to the compiler and fails with
AttributeError, which was invisible while only PostgreSQL was being checked.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "56e5e54db345"
down_revision: str | Sequence[str] | None = "85063df8430e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "uniq_active_label_per_manager"


def upgrade() -> None:
    op.drop_index(_NAME, table_name="client")
    op.create_index(
        _NAME,
        "client",
        ["manager_id", "label"],
        unique=True,
        postgresql_where=sa.text("active AND label <> ''"),
        sqlite_where=sa.text("active AND label <> ''"),
    )


def downgrade() -> None:
    # Duplicate empty labels cannot be resolved before reverting: whether a row may
    # be deleted is an operational decision, so nothing is removed silently here. With
    # duplicates present, creating the index fails and that is how anyone finds out.
    op.drop_index(_NAME, table_name="client")
    op.create_index(
        _NAME,
        "client",
        ["manager_id", "label"],
        unique=True,
        postgresql_where=sa.text("active"),
        sqlite_where=sa.text("active"),
    )
