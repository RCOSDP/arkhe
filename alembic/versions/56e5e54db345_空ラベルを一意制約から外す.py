"""空ラベルを一意制約から外す

Revision ID: 56e5e54db345
Revises: 85063df8430e
Create Date: 2026-08-28

**空のラベルは「名前を付けていない」であって、名前が衝突しているのではない。**
制約に含めていたため、1 機関にラベル無しの主体を 2 つ置けなかった——
web-api / web-ui / worker のように役割で鍵を分ける普通の構成が通らず、
鍵を共有させる圧力になっていた。

autogenerate は index の `where` 節を比較しないので、手で書いている。
"""

from collections.abc import Sequence

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
        postgresql_where="active AND label <> ''",
        sqlite_where="active AND label <> ''",
    )


def downgrade() -> None:
    # 戻す前に、空ラベルの重複を潰せない——**消してよいかは運用が決める**ので、
    # ここで黙って落とさない。重複があれば index の作成が失敗して気づく。
    op.drop_index(_NAME, table_name="client")
    op.create_index(
        _NAME,
        "client",
        ["manager_id", "label"],
        unique=True,
        postgresql_where="active",
        sqlite_where="active",
    )
