"""`domain.resolution.ArkRepository` の SQLAlchemy 実装。

解決の決定ロジックは DB を知らない。ここが唯一の接点で、**問い合わせは 4 つだけ**。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from arkhe.db.models import Ark, Naan, Shoulder
from arkhe.domain.resolution import ArkRepository

#: 保留（hold）の判定は ARK → shoulder → NAAN の順に見る。**関係を遅延で辿ると
#: 解決 1 回につき問い合わせが 2 本増える**ので、同じ 1 本に載せてしまう。
#: 解決はいちばん回る経路で、しかも読み取りレプリカに向く——ここを軽く保つ。
_WITH_HOLD_CHAIN = joinedload(Ark.shoulder).joinedload(Shoulder.naan_obj)


class SqlArkRepository(ArkRepository):
    """解決が引く窓口。

    `unpublished` は**このリゾルバが公開前の ARK も引くか**
    （`ARKHE_RESOLVE_UNPUBLISHED`）。閉域のリゾルバは引く——閉じた網の中で
    採番した ARK を、その網のリゾルバが解決できなければ配る意味が無い。
    公開のリゾルバは引かない。
    """

    def __init__(self, session: Session, *, unpublished: bool = False):
        self.session = session
        self.unpublished = unpublished

    def _visible(self, stmt):
        """公開前を落とすかどうか。**絞りを 1 か所に置く**——2 つの問い合わせで
        条件がずれると、完全一致では出ないのに祖先としては出る、が起きる。"""
        return stmt if self.unpublished else stmt.where(Ark.published_at.is_not(None))

    def get_ark(self, key: str):
        # **公開前の行は引かない**（公開のリゾルバでは）。決定ロジック側も
        # 弾くが、載せない時点で落としておく——読み取りレプリカに向いた
        # いちばん回る経路なので、要らない行は運ばない。
        return self.session.scalar(
            self._visible(select(Ark).where(Ark.ark == key)).options(_WITH_HOLD_CHAIN)
        )

    def get_arks(self, keys: list[str]) -> dict:
        # SC1: **DB で関数ソートしない。** 候補は高々 name 長ぶんなので 1 回の
        # IN で引き、順位づけはアプリ側（`gen_prefixes` の長い順）で行う。
        rows = self.session.scalars(
            self._visible(select(Ark).where(Ark.ark.in_(keys))).options(_WITH_HOLD_CHAIN)
        ).all()
        return {a.ark: a for a in rows}

    def get_naan(self, naan: str):
        return self.session.get(Naan, naan)

    def get_shoulder(self, naan: str, shoulder: str):
        return self.session.scalar(
            select(Shoulder).where(Shoulder.naan == naan, Shoulder.shoulder == shoulder)
        )
