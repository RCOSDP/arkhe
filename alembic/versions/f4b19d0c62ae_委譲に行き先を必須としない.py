"""委譲に行き先を必須としない

Revision ID: f4b19d0c62ae
Revises: e8c3a5f27b91
Create Date: 2026-09-07

**委譲とは「この名前空間ではもう採番しない」と台帳に刻むこと**であって、
「どこで採るかを外に公示すること」ではない。

初版から `status <> 'delegated' OR minter <> ''` という CHECK を置いていたが、
これが**内部ホスト名や人向けのページを `minter` に押し込ませていた**——閉域へ
委譲すると公示できる行き先が存在しないのに、制約を満たすには何かを入れるほか
なく、文書も「代わりに説明ページを書け」と案内していた。`about` を足しても
（`e8c3a5f27b91`）**「どちらか必須」のままでは同じ圧力が残る**ので、制約ごと外す。

行き先が無い委譲への採番要求は `403 ARKHE-1309`——「ここでは採番しない」とだけ
答える。案内があれば `detail.about` に載る。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4b19d0c62ae"
down_revision: str | Sequence[str] | None = "e8c3a5f27b91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("delegated_shoulder_needs_a_destination", "shoulder", type_="check")


def downgrade() -> None:
    # **行き先の無い委譲が既にあれば、ここで落ちる。** 戻すなら先に埋めること。
    op.create_check_constraint(
        "delegated_shoulder_needs_a_destination",
        "shoulder",
        "status <> 'delegated' OR minter <> '' OR about <> ''",
    )
