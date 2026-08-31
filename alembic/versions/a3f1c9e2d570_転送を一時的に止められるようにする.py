"""転送を一時的に止められるようにする

`naan` / `shoulder` / `ark` の 3 つに、同じ 3 列を足す。**行き先は消さない**
——止めるのは転送だけで、期限が切れれば元の行き先に戻る。tombstone（対象が
失われた、恒久）とは別物で、こちらは可逆である。

`hold_until` に索引を張るのは、**今かかっている保留を並べる**ための問い合わせ
（`admin_ops.held`）が `hold_until > now` で引くから。掛かっている行は普通ごく
少数なので、索引が効く形にしておく。

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
            # 既存行に空文字を入れてから NOT NULL にする（server_default は残さない
            # ——既定値をスキーマに埋めると、モデル側の既定と二重管理になる）。
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
