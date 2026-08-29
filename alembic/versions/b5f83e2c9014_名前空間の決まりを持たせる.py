"""名前空間の決まりを持たせる

Revision ID: b5f83e2c9014
Revises: c4e70a91d5b6
Create Date: 2026-08-29

**原則は NAAN、例外は組織。** 組織ごとの設定はここから狭めるだけで、広げられない。

既定を NAAN 側に置くのは、**組織が増えると 1 つずつ掛けるのが現実的でなくなる**
から。800 機関に同じ制限を入れて回る運用は成立しない。

3 つとも既定は「これまでどおり」——既存の台帳の挙動は変わらない。
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
