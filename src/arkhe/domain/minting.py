"""Minting, built so that an existing ARK is never silently overwritten (E1).

The worst flaw in arklet was that a primary key collision turned into an UPDATE and
silently rewrote where an existing ARK pointed. The Django version prevented it with
create(), which uses force_insert internally. In SQLAlchemy, session.add() is always an
INSERT, which gives the same property, while merge() would turn into an UPDATE. The
guard is that no other layer creates an Ark.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from arkhe.arkspec.betanumeric import (
    check_digit_base,
    generate_noid,
    noid_check_digit,
    verify_ark_check_digit,
)
from arkhe.arkspec.naming import (
    MAX_NAME_LENGTH,
    ark_key,
    compact_ark,
    normalize_percent,
    normalize_structural,
    strip_hyphens,
)
from arkhe.db.models import Ark, Shoulder, ShoulderStatus, WithdrawnName, utcnow

MINT_COLLISION_RETRIES = 10
NOID_LENGTH = 8


class AlreadyRegistered(Exception):
    """B4: the qualified ARK already exists. Return it rather than overwrite it."""


class QualifierForm(ValueError):
    """The qualifier begins with neither / nor .."""


class QualifierOutsideBase(ValueError):
    """The qualifier does not point inside the base name."""

    def __init__(self, qualifier: str):
        self.qualifier = qualifier
        super().__init__(f"qualifier does not point inside the base: {qualifier!r}")


class Withdrawn(ValueError):
    """A name withdrawn before publication. It is never minted again; see
    WithdrawnName."""

    def __init__(self, ark: str):
        self.ark = ark
        super().__init__(f"{ark} was withdrawn before publication and is never re-used")


class NameTooLong(ValueError):
    """The name is longer than can be indexed. Up to the 255 the specification
    requires is accepted."""

    def __init__(self, length: int, limit: int):
        self.length, self.limit = length, limit
        super().__init__(f"name is {length} octets, limit is {limit}")


def mint(
    session: Session, *, shoulder: Shoulder, created_by: str = "", reserve: bool = False,
    **fields
) -> tuple[Ark, int]:
    """Mint one ARK, retrying on a collision. Returns (Ark, number of collisions).

    A collision is counted and retried rather than swallowed. The count is returned so
    that a namespace filling up can be noticed: a rising rate means the names need
    another character.

    With reserve=True it is minted as reserved: it does not resolve and can still be
    deleted (Ark.published_at). By default it is published as it is minted, as before.
    """
    collisions = 0
    for _ in range(MINT_COLLISION_RETRIES):
        noid = generate_noid(NOID_LENGTH)
        stem = f"{shoulder.shoulder.lstrip('/')}{noid}"
        digit = noid_check_digit(check_digit_base(shoulder.naan, stem))
        name = f"{stem}{digit}"
        key = ark_key(shoulder.naan, name)
        # A withdrawn name is never handed out again. Its row is gone, so an INSERT
        # cannot refuse it; it is checked here and counted as a collision.
        if session.get(WithdrawnName, key) is not None:
            collisions += 1
            continue
        ark = Ark(
            ark=key,
            naan=shoulder.naan,
            shoulder_id=shoulder.id,
            assigned_name=name,
            created_by=created_by,
            updated_by=created_by,
            published_at=None if reserve else (now := utcnow()),
            # When it is published, mark that it has been, at the same moment.
            # Without this, an ARK published as it was minted would count as never
            # published, and could be deleted with no reason and no confirmation.
            first_published_at=None if reserve else now,
            **fields,
        )
        try:
            with session.begin_nested():  # a savepoint: a collision does not take
                                          # the outer transaction with it
                session.add(ark)
                session.flush()
        except IntegrityError:
            collisions += 1
            continue
        if collisions:
            _report_collisions(shoulder, collisions)
        return ark, collisions
    _report_collisions(shoulder, collisions, gave_up=True)
    raise RuntimeError(f"gave up minting after {collisions} collision(s)")


#: Logged from the domain layer. observability is not imported: it pulls in FastAPI,
#: which would mean a layer that should not know about HTTP knowing about it. Matching
#: the shape (extra={"fields": ...}) is enough to join the same stream.
_log = logging.getLogger("arkhe")


def _report_collisions(shoulder: Shoulder, collisions: int, *, gave_up: bool = False) -> None:
    """Record that a collision happened. Counting them and throwing the count away
    would be pointless.

    A collision is the only sign that a namespace is filling up. One does no harm, since
    minting retries, but a rising rate means the names need another character, and
    nobody sees that unless it is recorded.

    Nothing is logged when there were none. A line per mint would soon stop being read;
    what is worth logging is the times it happens.
    """
    _log.warning(
        "mint_collision",
        extra={"fields": {
            "naan": shoulder.naan,
            "shoulder": shoulder.shoulder,
            "collisions": collisions,
            "gave_up": gave_up,
        }},
    )


class NotDelegated(Exception):
    """An import was attempted into a shoulder that is not delegated."""

    def __init__(self, shoulder: str, status: str):
        self.shoulder, self.status = shoulder, status
        super().__init__(f"shoulder {shoulder} is {status}, not delegated")


class BadCheckDigit(ValueError):
    """The check digit of the name being imported does not match."""


class OutsideShoulder(ValueError):
    """The name being imported is not inside that shoulder."""

    def __init__(self, name: str, naan: str):
        self.name, self.naan = name, naan
        super().__init__(f"{name} is outside the shoulder of {naan}")


def check_importable(session: Session, shoulder: Shoulder, name: str) -> str:
    """Whether this name may be imported. Every check that can happen before writing
    is collected here.

    A bulk import can promise that one bad row creates nothing because every check but
    the collision needs no write; only a collision is known to the INSERT. Returns the
    normalised name.
    """
    if shoulder.status != ShoulderStatus.DELEGATED:
        raise NotDelegated(shoulder.shoulder, shoulder.status)
    name = strip_hyphens(normalize_structural(normalize_percent(name)))
    if len(name) > MAX_NAME_LENGTH:
        raise NameTooLong(len(name), MAX_NAME_LENGTH)
    if not name.startswith(shoulder.shoulder.lstrip("/")):
        raise OutsideShoulder(name, shoulder.naan)
    # N7: the digit is computed over the base name. Qualifiers are register's job.
    if not verify_ark_check_digit(shoulder.naan, name):
        raise BadCheckDigit(name)
    # A withdrawn name is not accepted. Even minted elsewhere, a string this ledger
    # once withdrawn before publication would be attached to a different object.
    key = ark_key(shoulder.naan, name)
    if session.get(WithdrawnName, key) is not None:
        raise Withdrawn(compact_ark(key))
    return name


def import_minted(
    session: Session, *, shoulder: Shoulder, name: str, created_by: str = "", **fields
) -> Ark:
    """Bring a name minted elsewhere into this ledger.

    There is one difference from mint: the caller brings the name. That difference is
    large. Everything mint guaranteed structurally, no collision, a correct check digit,
    inside our own namespace, becomes a check in this function, which is why it has its
    own scope rather than ark:mint.

    It exists so that an ARK minted on a closed network can later be published
    (federation.md, C-2 to C-1). Without it, a name handed out while closed could not be
    published as it stands and another would have to be minted, which breaks the very
    point of giving closed objects the same kind of identifier.

    There are three checks, and none of them may be loosened:

    1. The shoulder is delegated. Accepting outside names into a namespace we mint from
       ourselves could collide with our own minting. Names minted elsewhere exist
       precisely because the namespace was delegated.
    2. The name is inside that shoulder. This must not become a way to write outside
       what was delegated.
    3. The check digit matches. It is the only way to trust a name from outside (N7:
       computed over the base name, excluding any qualifier).

    A collision is refused by a single INSERT, as in mint (E1). An existing name is
    never overwritten silently.
    """
    name = check_importable(session, shoulder, name)

    ark = Ark(
        ark=ark_key(shoulder.naan, name),
        naan=shoulder.naan,
        shoulder_id=shoulder.id,
        assigned_name=name,
        created_by=created_by,
        updated_by=created_by,
        # An imported name is published. This takes on a name that was minted
        # elsewhere and is already in circulation, so there is nothing to be gained by
        # holding it back here.
        published_at=(imported_at := utcnow()),
        first_published_at=imported_at,
        **fields,
    )
    try:
        with session.begin_nested():
            session.add(ark)
            session.flush()
    except IntegrityError as exc:
        raise AlreadyRegistered(compact_ark(ark_key(shoulder.naan, name))) from exc
    return ark


def register_qualified(
    session: Session, *, base: Ark, qualifier: str, created_by: str = "", **fields
) -> Ark:
    """B4: register a row for an existing ARK with a qualifier attached.

    This is not minting with the NOID left out. A qualifier is not a new name but a part
    reference to an existing one, so no check digit is computed for it (N7: the digit is
    computed over the base compact name and excludes qualifiers).

    It exists to override what inheritance would do. By default a qualifier is appended
    to the ancestor's URL as a continuation; this registers one point explicitly, for
    "this subtree lives in another store" or "this converted form is somewhere else".

    The shoulder is inherited from the base. It must not be possible to attach one to a
    different shoulder, because a qualifier lives inside the base's namespace.
    """
    if not qualifier.startswith(("/", ".")):
        raise QualifierForm("a qualifier must begin with '/' or '.'")
    # A4: a qualifier can carry percent encoding too (%2F is a slash that is not a
    # separator). It goes through the same normalisation as resolution; otherwise a row
    # could be registered and then never resolve.
    name = strip_hyphens(normalize_structural(normalize_percent(base.assigned_name + qualifier)))
    if name == base.assigned_name or not name.startswith(base.assigned_name):
        raise QualifierOutsideBase(qualifier)
    if len(name) > MAX_NAME_LENGTH:
        # Not failed with a database error. 3.1 requires receiving implementations to
        # support 255 octets, which is what we index, and it warns whoever makes longer
        # names that a receiving implementation may not index them.
        raise NameTooLong(len(name), MAX_NAME_LENGTH)
    ark = Ark(
        ark=ark_key(base.naan, name),
        naan=base.naan,
        shoulder_id=base.shoulder_id,
        assigned_name=name,
        created_by=created_by,
        updated_by=created_by,
        # Publication is inherited from the base. A part reference never goes out
        # before its base, and withdrawing a reserved base leaves no orphan behind.
        published_at=base.published_at,
        first_published_at=base.first_published_at,
        **fields,
    )
    try:
        with session.begin_nested():
            session.add(ark)
            session.flush()
    except IntegrityError as exc:
        # E1: nothing existing is overwritten silently. Changing it is update's job.
        raise AlreadyRegistered(
            f"{compact_ark(ark_key(base.naan, name))} is already registered"
        ) from exc
    return ark
