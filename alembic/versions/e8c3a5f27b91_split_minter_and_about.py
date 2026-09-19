"""Separate the minting endpoint from the guidance for people

Revision ID: e8c3a5f27b91
Revises: d2a7f4b81c63
Create Date: 2026-09-07

shoulder.minter appears in two places as a machine-readable contract: in
/.well-known/ark, and in the Location of the 307 answered when a mint request arrives for
a delegated shoulder. Both say that calling this mints something.

For a shoulder delegated to a closed network, that endpoint cannot be reached from
outside. An internal host name would leak the layout and work for nobody, so the guide
suggested writing a page for people instead, which makes the contract untrue: a client
that receives a 307 POSTs to that page, and nothing tells it apart from an API.

about is added, and the two are separated.

  minter  an endpoint a machine can call. Leave it empty when there is none
  about   guidance for people: minting happens elsewhere, and here is the explanation

A delegation needs at least one of them (set_shoulder_status). With a minter the answer
is 307 as before; without one it is 403 with the guidance in the body (ARKHE-1309). That
branch was already in app.py and had never been reached, because a delegation required a
minter.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8c3a5f27b91"
down_revision: str | Sequence[str] | None = "d2a7f4b81c63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shoulder",
        sa.Column("about", sa.String(length=500), nullable=False, server_default=""),
    )
    # Existing values are left alone. Which minter is really an explanatory page
    # cannot be told from the ledger; an operator has to look and decide.

    # A delegation still needs a target; there are simply two kinds of target now.
    # SQLite has no ALTER for replacing a constraint, so it goes through batch mode,
    # which rebuilds the table.
    # On PostgreSQL it stays a plain ALTER.
    with op.batch_alter_table("shoulder") as batch_op:
        batch_op.drop_constraint("delegated_shoulder_needs_a_minter", type_="check")
        batch_op.create_check_constraint(
            "delegated_shoulder_needs_a_destination",
            "status <> 'delegated' OR minter <> '' OR about <> ''",
        )


def downgrade() -> None:
    # If any row delegates with about alone, this fails. Reverting would leave a
    # delegation with no target, which must not pass silently.
    with op.batch_alter_table("shoulder") as batch_op:
        batch_op.drop_constraint("delegated_shoulder_needs_a_destination", type_="check")
        batch_op.create_check_constraint(
            "delegated_shoulder_needs_a_minter",
            "status <> 'delegated' OR minter <> ''",
        )
        batch_op.drop_column("about")
