"""Allow redirection to be held for a while

The same three columns are added to naan, shoulder and ark. The target is not
discarded: only redirection stops, and when the hold expires the original target comes
back. It is not a tombstone, which says an object is gone and is permanent; this is
reversible.

hold_until is indexed because listing the holds in force (admin_ops.held) queries
hold_until > now, and the number of held rows is normally tiny, so an index applies
well.

Revision ID: a3f1c9e2d570
Revises: b65e77b221ac
Create Date: 2026-08-31 05:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f1c9e2d570'
down_revision: Union[str, Sequence[str], None] = 'b65e77b221ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("naan", "shoulder", "ark")


def upgrade() -> None:
    """Upgrade schema."""
    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("hold_until", sa.DateTime(timezone=True), nullable=True)
            )
            # Fill existing rows with an empty string, then make it NOT NULL. No
            # server_default is left behind: a default in the schema would be a second
            # copy of the default in the models.
            batch_op.add_column(
                sa.Column(
                    "hold_reason", sa.String(length=500), nullable=False, server_default=""
                )
            )
            batch_op.add_column(
                sa.Column(
                    "hold_by", sa.String(length=255), nullable=False, server_default=""
                )
            )
            batch_op.create_index(
                batch_op.f(f"ix_{table}_hold_until"), ["hold_until"], unique=False
            )
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column("hold_reason", server_default=None)
            batch_op.alter_column("hold_by", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(batch_op.f(f"ix_{table}_hold_until"))
            batch_op.drop_column("hold_by")
            batch_op.drop_column("hold_reason")
            batch_op.drop_column("hold_until")
