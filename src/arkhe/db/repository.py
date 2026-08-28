"""`domain.resolution.ArkRepository` の SQLAlchemy 実装。

解決の決定ロジックは DB を知らない。ここが唯一の接点で、**問い合わせは 4 つだけ**。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from arkhe.db.models import Ark, Naan, Shoulder
from arkhe.domain.resolution import ArkRepository


class SqlArkRepository(ArkRepository):
    def __init__(self, session: Session):
        self.session = session

    def get_ark(self, key: str):
        return self.session.get(Ark, key)

    def get_arks(self, keys: list[str]) -> dict:
        # SC1: **DB で関数ソートしない。** 候補は高々 name 長ぶんなので 1 回の
        # IN で引き、順位づけはアプリ側（`gen_prefixes` の長い順）で行う。
        rows = self.session.scalars(select(Ark).where(Ark.ark.in_(keys))).all()
        return {a.ark: a for a in rows}

    def get_naan(self, naan: str):
        return self.session.get(Naan, naan)

    def get_shoulder(self, naan: str, shoulder: str):
        return self.session.scalar(
            select(Shoulder).where(Shoulder.naan == naan, Shoulder.shoulder == shoulder)
        )
