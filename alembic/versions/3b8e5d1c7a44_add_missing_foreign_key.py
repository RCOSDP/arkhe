"""Add the foreign key that was declared but never created

Revision ID: 3b8e5d1c7a44
Revises: 56e5e54db345
Create Date: 2026-08-29

The initial schema declared manager.default_shoulder_id to shoulder.id inside
create_table with use_alter=True. use_alter tells SQLAlchemy how to order CREATE TABLE
statements; with Alembic's op.create_table it does not become a later ALTER, so this
foreign key existed in no database at all. alembic check was pointing at it.

The practical effect is that ondelete="SET NULL" does nothing. A shoulder cannot be
deleted (before_delete refuses), so nothing has gone wrong in practice, but while the
models and the schema disagree, every autogenerate reports this and hides a real
difference behind it.

A dangling reference would prevent the key being created, so any are cleared first.

SQLite has no ALTER for adding a constraint, so it goes through batch mode, which
rebuilds the table and copies the rows. On PostgreSQL it stays a plain ALTER:
batch_alter_table chooses by dialect, so the migration is not split in two.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3b8e5d1c7a44"
down_revision: str | Sequence[str] | None = "56e5e54db345"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "fk_manager_default_shoulder"


def upgrade() -> None:
    op.execute(
        "UPDATE manager SET default_shoulder_id = NULL "
        "WHERE default_shoulder_id IS NOT NULL "
        "AND default_shoulder_id NOT IN (SELECT id FROM shoulder)"
    )
    with op.batch_alter_table("manager") as batch_op:
        batch_op.create_foreign_key(
            NAME, "shoulder", ["default_shoulder_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("manager") as batch_op:
        batch_op.drop_constraint(NAME, type_="foreignkey")
