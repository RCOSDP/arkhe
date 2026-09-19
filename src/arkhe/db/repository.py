"""The SQLAlchemy implementation of domain.resolution.ArkRepository.

The resolution logic knows nothing about the database. This is the only point of
contact, and it makes four queries.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from arkhe.db.models import Ark, Naan, Shoulder
from arkhe.domain.resolution import ArkRepository

#: A hold is looked for on the ARK, then the shoulder, then the NAAN. Following those
#: relationships lazily would add two queries per resolution, so they ride along on the
#: same one. Resolution is the busiest path and the one aimed at a read replica, so it
#: is kept light.
_WITH_HOLD_CHAIN = joinedload(Ark.shoulder).joinedload(Shoulder.naan_obj)


class SqlArkRepository(ArkRepository):
    """What resolution reads through.

    unpublished says whether this resolver serves reserved ARKs
    (ARKHE_RESOLVE_UNPUBLISHED). A resolver on a closed network does: if ARKs minted
    inside it do not resolve there, handing them out is pointless. A public resolver
    does not.
    """

    def __init__(self, session: Session, *, unpublished: bool = False):
        self.session = session
        self.unpublished = unpublished

    def _visible(self, stmt):
        """Whether reserved rows are dropped. The filter lives in one place: if the
        two queries disagreed, a row could be hidden from an exact match and still be
        found as an ancestor."""
        return stmt if self.unpublished else stmt.where(Ark.published_at.is_not(None))

    def get_ark(self, key: str):
        # A public resolver does not read reserved rows. The decision logic refuses
        # them too, but they are dropped here as well: this is the busiest path, aimed
        # at a read replica, so nothing unnecessary is carried.
        return self.session.scalar(
            self._visible(select(Ark).where(Ark.ark == key)).options(_WITH_HOLD_CHAIN)
        )

    def get_arks(self, keys: list[str]) -> dict:
        # SC1: no sorting by a function in the database. There are at most as many
        # candidates as the name is long, so they are fetched with one IN and ordered
        # here, longest first, by gen_prefixes.
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
