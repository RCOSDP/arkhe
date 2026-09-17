"""公開前の ARK を消せるようにする

Revision ID: a7c3e51d9f20
Revises: f4b19d0c62ae
Create Date: 2026-09-16

**NR が縛るのは、外へ出した名前である。** 採番した瞬間から縛られるわけではない
——下書きの対象に先に番号を振り、公開をやめたときに、その番号が誰も指さないまま
台帳に残り続けるのは、約束を守っていることにはならない。

そこで `ark.published_at` を足す。null は「まだ公開していない」で、その ARK は
解決せず、取り下げれば消せる。

**既存の行はすべて公開済みとして埋める**（`created_at` を入れる）。今まで採番は
公開と同じ意味だったので、それが実態である。null のままにすると、**今まで解決
していた ARK が一斉に解決しなくなる**。

`withdrawn_name` は取り下げた名前の置き場。行を消しても名前は返さない
——予約した文字列は既に人の手に渡っていることがあり、別の対象に振り直せば
外からは NR 違反と見分けがつかない。**公開した名前を RA の運用者が破棄した
場合もここに入る**（`published_at` が入っているかで見分ける）。
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
    # **今まで在る ARK は公開済み。** 採番と公開が同じ意味だった時代のものなので、
    # ここを埋め忘れると解決が一斉に止まる。
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
        # null は公開前の取り下げ、値があれば**公開した名前の破棄**。
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_by", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("reason", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("ip", sa.String(length=45), nullable=False, server_default=""),
        # **外部キーを持たない。** 参照先の行はもう無いし、記録は対象より長く残る。
        sa.PrimaryKeyConstraint("ark"),
    )
    op.create_index("ix_withdrawn_name_naan", "withdrawn_name", ["naan"])
    op.create_index("ix_withdrawn_name_shoulder_id", "withdrawn_name", ["shoulder_id"])
    op.create_index("ix_withdrawn_name_withdrawn_at", "withdrawn_name", ["withdrawn_at"])
    op.create_index("ix_withdrawn_name_withdrawn_by", "withdrawn_name", ["withdrawn_by"])


def downgrade() -> None:
    # **下げても名前は返さない。** 表ごと落とすので、取り下げた名前の記録は
    # 消える——下げる前に控えを取ること（`downgrade` は開発時の道具である）。
    op.drop_index("ix_withdrawn_name_withdrawn_by", table_name="withdrawn_name")
    op.drop_index("ix_withdrawn_name_withdrawn_at", table_name="withdrawn_name")
    op.drop_index("ix_withdrawn_name_shoulder_id", table_name="withdrawn_name")
    op.drop_index("ix_withdrawn_name_naan", table_name="withdrawn_name")
    op.drop_table("withdrawn_name")
    op.drop_index("ix_ark_published_at", table_name="ark")
    op.drop_column("ark", "published_at")
