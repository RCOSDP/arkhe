"""未登録の主体を残す

認可サーバのトークンは正しいのに台帳に登録が無かった主体を残す表。
**綴りが 1 文字違うだけで 401 になる**が、弾いた時点で正しい文字列は
`azp` として手元にある——捨てずに残せば、運用者は打ち直さずに登録できる。

`(subject, issuer)` を一意にして行を増やさない。台帳の他の表とは結ばない
——トークンからは**どの組織のものか分からない**し、推測もしない。

Revision ID: b65e77b221ac
Revises: b5f83e2c9014
Create Date: 2026-08-29 13:32:29.588267

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b65e77b221ac'
down_revision: Union[str, Sequence[str], None] = 'b5f83e2c9014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('unknown_subject',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('subject', sa.String(length=255), nullable=False),
    sa.Column('issuer', sa.String(length=500), nullable=False),
    sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
    sa.Column('seen', sa.Integer(), nullable=False),
    sa.Column('ip', sa.String(length=45), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('subject', 'issuer', name='uq_unknown_subject')
    )
    with op.batch_alter_table('unknown_subject', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_unknown_subject_last_seen'), ['last_seen'], unique=False)
        batch_op.create_index(batch_op.f('ix_unknown_subject_subject'), ['subject'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('unknown_subject', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_unknown_subject_subject'))
        batch_op.drop_index(batch_op.f('ix_unknown_subject_last_seen'))

    op.drop_table('unknown_subject')
