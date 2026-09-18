"""公開を取り下げられるようにする

Revision ID: b9d4a17c3e85
Revises: a7c3e51d9f20
Create Date: 2026-09-18

0.3.0 では `published_at` は一方通行だった——公開した瞬間から戻せない。覆したのは、
**取り下げの判断が対象を持っている組織のところにある**からである。公開しては
ならなかったものに気づくのは RA ではなく預けた側で、そこから RA に上げて戻って
くるまで**出たままになる**。

`published_at` は「今この瞬間 公開しているか」になり、行ったり来たりする。
そこで **`first_published_at`（初めて公開した時刻）を足す。こちらが片道**で、
一度立てたら二度と倒さない——外に出た名前は、引っ込めても「出ていなかったこと」
にはならない。その間に誰かが引用しているかもしれず、こちらからは知りようがない。

この列が決めるのは**儀式の重さ**である。一度も出していない予約の取り下げは軽く、
**一度でも出した名前は理由と打ち直しを要求する**。重さを主体の位ではなく名前の
履歴に結びつけたのは、**危ないのは「誰が消すか」ではなく「何が消えるか」**だから。

**既存の公開済みの行は、`published_at` をそのまま写す。** 今まで公開は取り消せ
なかったので、`published_at` が入っている行はすべて「今も公開中で、その時刻に
初めて公開した」が実態である。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9d4a17c3e85"
down_revision: str | Sequence[str] | None = "a7c3e51d9f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ark", sa.Column("first_published_at", sa.DateTime(timezone=True), nullable=True)
    )
    # **今まで公開は取り消せなかった。** だから `published_at` が入っている行は、
    # そのまま「初めて公開した時刻」でもある。埋め忘れると、**既存の公開済み ARK が
    # 「一度も出していない」ことになり、理由も打ち直しも無しに消せてしまう。**
    op.execute(
        "UPDATE ark SET first_published_at = published_at WHERE published_at IS NOT NULL"
    )


def downgrade() -> None:
    # **下げると「一度出した」事実が消える。** 今 公開中のものは `published_at` から
    # 復元できるが、**取り下げ済みのものは復元できない**——下げた先には、その状態を
    # 表す列が無いからである（0.3.0 では取り下げが存在しない）。
    op.drop_column("ark", "first_published_at")
