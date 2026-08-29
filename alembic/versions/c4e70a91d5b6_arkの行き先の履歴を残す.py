"""ARK の行き先の履歴を残す

Revision ID: c4e70a91d5b6
Revises: 9f2b6c4e18a3
Create Date: 2026-08-29

これが無いと、**以前どこを指していたかを復元できない**。`NR` を宣言する体系で
「この識別子は変わらない」と言うなら、変えたのは何でいつ誰が変えたのかを
示せなければならない——さもないと、約束を検証する手段が利用者の側に無い。

監査ログとは別に持つ。監査は NAAN 単位以上の操作しか残さないが、採番も
付け替えも組織が行うので、監査だけでは肝心の変更が落ちる。

**既存の ARK には履歴が無い。** そのとき記録していなかったものを、後から
作り出すことはできない。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e70a91d5b6"
down_revision: str | Sequence[str] | None = "9f2b6c4e18a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ark_change",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ark", sa.String(length=200), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("before_url", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("after_url", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("by", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("ip", sa.String(length=45), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["ark"], ["ark.ark"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ark_change_ark", "ark_change", ["ark"])
    op.create_index("ix_ark_change_at", "ark_change", ["at"])
    op.create_index("ix_ark_change_by", "ark_change", ["by"])


def downgrade() -> None:
    op.drop_table("ark_change")
