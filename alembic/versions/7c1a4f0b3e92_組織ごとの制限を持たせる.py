"""組織ごとの制限を持たせる

Revision ID: 7c1a4f0b3e92
Revises: 3b8e5d1c7a44
Create Date: 2026-08-29

名前空間を配る側が、配られた側に**何を任せ、何を制限するか**を宣言できる
ようにする。3 つとも既定は「これまでどおり」——既存の台帳の挙動は変わらない。

  allowed_auth       入り方の制限（空 = 構成の既定に従う）
  may_self_register  組織の管理者が自分で利用者を登録してよいか（既定 true）
  max_scopes         その組織の利用者に与えられる scope の上限（空 = 制限なし）

autogenerate が毎回 `fk_manager_default_shoulder` を足そうとしていたのは、
それが**本当に無かった**から。別の移行（3b8e5d1c7a44）で先に直してある。
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
