"""採番の口と人向けの案内を分ける

Revision ID: e8c3a5f27b91
Revises: d2a7f4b81c63
Create Date: 2026-09-07

`shoulder.minter` は 2 か所で**機械可読の契約**として出ている——`/.well-known/ark`
と、委譲された shoulder に mint 要求が来たときの `307 Location`。どちらも
「ここを叩けば採番できる」と言う。

ところが閉域へ委譲した shoulder では、その口が**外から到達できない**。内部ホスト名を
書けば構成が漏れるうえ誰も使えないので、文書は「代わりに人向けの説明ページを書け」と
案内していた——**それは契約を嘘にする**。307 を受けたクライアントは、人向けの
ページへ `POST` しにいく。受け取った側に、API とページを見分ける手段は無い。

`about` を足して分ける。

  minter  機械が叩ける採番の口。**無いなら空にする**
  about   人が読む案内。「採番は外で行っている。事情はここ」

委譲には最低どちらか 1 つが要る（`set_shoulder_status`）。`minter` があれば従来どおり
307、無ければ **403 と本文の案内**（`ARKHE-1309`）を返す——**その分岐は元から
`app.py` に在ったが、委譲に minter を必須にしていたので一度も通らなかった**。
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
    # **既存の値は動かさない。** どの `minter` が実は説明ページだったかは、
    # 台帳からは判別できない——運用者が見て分けるほかない。

    # 「委譲には行き先が要る」は残す。**行き先が 2 種類になっただけ**である。
    op.drop_constraint("delegated_shoulder_needs_a_minter", "shoulder", type_="check")
    op.create_check_constraint(
        "delegated_shoulder_needs_a_destination",
        "shoulder",
        "status <> 'delegated' OR minter <> '' OR about <> ''",
    )


def downgrade() -> None:
    # **`about` だけで委譲している行があれば、ここで落ちる。** 戻すと「行き先の
    # 無い委譲」になるので、黙って通してはいけない。
    op.drop_constraint("delegated_shoulder_needs_a_destination", "shoulder", type_="check")
    op.create_check_constraint(
        "delegated_shoulder_needs_a_minter",
        "shoulder",
        "status <> 'delegated' OR minter <> ''",
    )
    op.drop_column("shoulder", "about")
