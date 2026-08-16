"""`ArkRepository` の Django 実装。決定ロジックと ORM の境目。"""

from __future__ import annotations

from .models import Ark, Naan, Shoulder
from .resolution import ArkRepository


class DjangoArkRepository(ArkRepository):
    def get_ark(self, key: str):
        return Ark.objects.filter(pk=key).first()

    def get_arks(self, keys: list[str]) -> dict:
        # SC1: 1 回の IN で引き、順位付けはアプリ側でやる（DB で関数ソートしない）。
        return {a.pk: a for a in Ark.objects.filter(pk__in=keys)}

    def get_naan(self, naan: str):
        return Naan.objects.filter(pk=naan).first()

    def get_shoulder(self, naan: str, shoulder: str):
        return Shoulder.objects.filter(naan_id=naan, shoulder=shoulder).first()
