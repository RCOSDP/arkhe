"""The result of authentication. Whatever the mechanism, authorisation is decided on
this one type.

An API key, a token we issued and an external OIDC token differ only in how identity was
established. The question afterwards, whether this principal may touch this shoulder, is
the same. Keeping them apart would add a branch to authorisation for every mechanism,
and one of them would end up wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from arkhe.db.models import Authority


@dataclass(frozen=True)
class Principal:
    """An authenticated principal.

    The reach, naan, manager, shoulder and scopes, comes from the registration and never
    from a token request or a request body, which is what prevents privilege escalation.
    """

    client_id: str
    naan: str
    authority: str = Authority.MANAGER.value
    manager_id: int | None = None
    #: Pins the principal to one shoulder. None means any shoulder the organisation
    #: holds.
    shoulder_id: int | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)
    #: Which mechanism authenticated it, kept in the audit log.
    mechanism: str = ""

    #: The caller's address, filled in only at the request layer. It is carried for
    #: the audit log and never used to decide authorisation: an address can be forged,
    #: and it changes when the route does.
    ip: str = ""

    @property
    def is_system(self) -> bool:
        """The RA operator, who reaches every NAAN."""
        return self.authority == Authority.SYSTEM

    @property
    def is_naan_wide(self) -> bool:
        """Reaches everything under the NAAN, including the system administrator."""
        return self.authority in (Authority.SYSTEM, Authority.NAAN)

    #: Kept for compatibility: authority=naan is also used for break-glass.
    @property
    def is_break_glass(self) -> bool:
        return self.is_naan_wide

    def reaches_naan(self, naan: str) -> bool:
        """Whether it reaches that NAAN. Decided here and nowhere else."""
        return self.is_system or self.naan == naan

    def has(self, scope: str) -> bool:
        return scope in self.scopes
