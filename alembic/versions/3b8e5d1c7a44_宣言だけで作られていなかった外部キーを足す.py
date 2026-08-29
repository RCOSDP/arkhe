"""宣言だけで作られていなかった外部キーを足す

Revision ID: 3b8e5d1c7a44
Revises: 56e5e54db345
Create Date: 2026-08-29

初期スキーマは `manager.default_shoulder_id → shoulder.id` を
`create_table` の中で `use_alter=True` 付きで宣言していた。**`use_alter` は
SQLAlchemy が CREATE TABLE の順番を解くための指示で、Alembic の
`op.create_table` では後追いの ALTER にならない**——結果、この外部キーは
どのデータベースにも作られていなかった（`alembic check` がそれを指していた）。

実害は `ondelete="SET NULL"` が効かないこと。shoulder は
`before_delete` で消せないようにしてあるので現実の事故は起きていないが、
**モデルの宣言と実際のスキーマがずれたまま**では、以後の autogenerate が
毎回これを検出し、本当のずれを覆い隠す。

宙に浮いた参照があると外部キーを張れないので、先に掃除する（あれば）。
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
    op.create_foreign_key(
        NAME, "manager", "shoulder", ["default_shoulder_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint(NAME, "manager", type_="foreignkey")
