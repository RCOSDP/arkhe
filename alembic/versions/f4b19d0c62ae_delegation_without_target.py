"""Stop requiring a target for a delegation

Revision ID: f4b19d0c62ae
Revises: e8c3a5f27b91
Create Date: 2026-09-07

Delegating records in the ledger that we no longer mint in this namespace. It does not
announce where minting happens.

From the first version there was a CHECK, status <> 'delegated' OR minter <> '', and it
pushed internal host names and pages for people into minter: delegating to a closed
network leaves nothing that can be announced, while the constraint demanded something,
and the guide even suggested writing an explanatory page instead. Adding about
(e8c3a5f27b91) did not remove the pressure while one of the two was still required, so
the constraint goes.

A mint request against a delegation with no target answers 403 ARKHE-1309, saying only
that we do not mint here. Any guidance appears in detail.about.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4b19d0c62ae"
down_revision: str | Sequence[str] | None = "e8c3a5f27b91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite has no ALTER for dropping a constraint, so it goes through batch mode,
    # which rebuilds the table.
    with op.batch_alter_table("shoulder") as batch_op:
        batch_op.drop_constraint("delegated_shoulder_needs_a_destination", type_="check")


def downgrade() -> None:
    # If a delegation with no target already exists, this fails. Fill them in before
    # reverting.
    with op.batch_alter_table("shoulder") as batch_op:
        batch_op.create_check_constraint(
            "delegated_shoulder_needs_a_destination",
            "status <> 'delegated' OR minter <> '' OR about <> ''",
        )
