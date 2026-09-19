"""Allow a reserved ARK to be deleted

Revision ID: a7c3e51d9f20
Revises: f4b19d0c62ae
Create Date: 2026-09-16

NR binds names that went out. It does not bind from the moment of minting: giving a
draft a number in advance and then deciding not to publish it, leaving that number in
the ledger naming nothing, is not keeping the promise either.

So ark.published_at is added. null means it has not been published, in which case the
ARK does not resolve and can be deleted.

Every existing row is filled in as published, from created_at. Until now minting and
publishing were the same act, so that is what was true. Leaving them null would stop
every ARK that has been resolving from resolving at all.

withdrawn_name is where withdrawn names are kept. Deleting a row does not return the
name: a reserved string may already be in someone's hands, and pointing it at another
object would be indistinguishable, from outside, from an NR violation. A published name
purged by the RA operator lands here too, told apart by whether published_at is set.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e51d9f20"
down_revision: str | Sequence[str] | None = "f4b19d0c62ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ark", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    # Every ARK that exists is published: they come from the time when minting and
    # publishing were the same act, and leaving this out would stop resolution
    # everywhere.
    op.execute("UPDATE ark SET published_at = created_at WHERE published_at IS NULL")
    op.create_index("ix_ark_published_at", "ark", ["published_at"])

    op.create_table(
        "withdrawn_name",
        sa.Column("ark", sa.String(length=272), nullable=False),
        sa.Column("naan", sa.String(length=16), nullable=False),
        sa.Column("assigned_name", sa.String(length=255), nullable=False),
        sa.Column("shoulder_id", sa.Integer(), nullable=True),
        sa.Column("minted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("minted_by", sa.String(length=255), nullable=False, server_default=""),
        # null: withdrawn before publication. A value: a published name was purged.
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_by", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("reason", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("ip", sa.String(length=45), nullable=False, server_default=""),
        # No foreign key: the row it would reference is gone, and a record should
        # outlive what it is about.
        sa.PrimaryKeyConstraint("ark"),
    )
    op.create_index("ix_withdrawn_name_naan", "withdrawn_name", ["naan"])
    op.create_index("ix_withdrawn_name_shoulder_id", "withdrawn_name", ["shoulder_id"])
    op.create_index("ix_withdrawn_name_withdrawn_at", "withdrawn_name", ["withdrawn_at"])
    op.create_index("ix_withdrawn_name_withdrawn_by", "withdrawn_name", ["withdrawn_by"])


def downgrade() -> None:
    # Reverting does not return the names. The table is dropped, so the record of
    # what was withdrawn goes with it: take a copy first. downgrade is a development
    # tool.
    op.drop_index("ix_withdrawn_name_withdrawn_by", table_name="withdrawn_name")
    op.drop_index("ix_withdrawn_name_withdrawn_at", table_name="withdrawn_name")
    op.drop_index("ix_withdrawn_name_shoulder_id", table_name="withdrawn_name")
    op.drop_index("ix_withdrawn_name_naan", table_name="withdrawn_name")
    op.drop_table("withdrawn_name")
    op.drop_index("ix_ark_published_at", table_name="ark")
    op.drop_column("ark", "published_at")
