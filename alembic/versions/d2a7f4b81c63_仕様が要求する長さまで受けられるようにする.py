"""仕様が要求する長さまで受けられるようにする

Revision ID: d2a7f4b81c63
Revises: a3f1c9e2d570
Create Date: 2026-09-07

draft-kunze-ark-42 が**受け取る実装に義務づけている 2 つの下限**を、列の幅が
割っていた。

  §2.3  "For received ARKs, implementations must support a minimum NAAN length
        of **16 octets**."                      → `naan` は 10 だった
  §3.1  "implementations must support a minimum length of **255 octets** for the
        string composed of the Base Name plus Qualifier."
                                                 → `assigned_name` は 100 だった

**NAAN の 10 には理由があったが、この実装には当てはまらない理由だった。** 原典の
arklet は NAAN を `int()` に通すので変換前に長さで守る必要があり、その定数を
そのまま持ってきていた。arkhe は N2 で「NAAN は文字列として保持・比較する。
整数化してはならない」と決めている（`ark:/099999/…` と `ark:/99999/…` は別物と
するため）ので、守るべき変換がそもそも無い。

`ark`（`<naan>/<name>`）は両方の下限から 16 + 1 + 255 = 272 で決まる。これを
参照する `mint_receipt.ark` `ark_change.ark`、および ARK を入れる
`audit_event.target` も揃える——**片方だけ広げると、入る値と入らない値が経路に
よって変わる。**

PostgreSQL では varchar の**拡大**なのでテーブルの書き換えも索引の作り直しも
起きない（メタデータだけの変更）。

**SQLite では何もしない。** varchar の長さを見ない DB で、PK と外部キーを
持つ表を batch mode で作り直す危険を冒す意味が無い。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2a7f4b81c63"
down_revision: str | Sequence[str] | None = "a3f1c9e2d570"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (表, 列, 変更前, 変更後)。**NAAN を持つ表は全部挙げる**——参照する側が
#: 狭いままだと、広げた NAAN を持つ組織や ARK を作れない。
_WIDENED = [
    ("naan", "naan", 10, 16),
    ("manager", "naan", 10, 16),
    ("shoulder", "naan", 10, 16),
    ("ark", "naan", 10, 16),
    ("client", "naan", 10, 16),
    ("ark", "ark", 200, 272),
    ("ark", "assigned_name", 100, 255),
    ("mint_receipt", "ark", 200, 272),
    ("ark_change", "ark", 200, 272),
    ("audit_event", "target", 200, 272),
]


def _resize(pairs) -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    for table, column, old, new in pairs:
        op.alter_column(
            table,
            column,
            existing_type=sa.String(length=old),
            type_=sa.String(length=new),
            existing_nullable=False,
        )


def upgrade() -> None:
    _resize(_WIDENED)


def downgrade() -> None:
    # **縮めると入りきらない値が切り落とされる。** 広げてから採番した ARK が
    # あるなら、PostgreSQL は落として止まる——黙って識別子を壊すよりよい。
    _resize([(t, c, new, old) for t, c, old, new in reversed(_WIDENED)])
