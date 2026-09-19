"""The core of authorisation. The shoulder comes from the principal, never from the
request.

That one point settles both crossing organisational boundaries (R1) and routing between
many organisations. arklet took {naan, shoulder} from the request body and authorised
only per NAAN, so a misconfiguration or a forged field let anyone mint into another
organisation's namespace.

Whatever the mechanism, apikey, oauth2 or oidc, the decision is made here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from arkhe import errors
from arkhe.auth.errors import Forbidden, InsufficientScope
from arkhe.auth.principal import Principal
from arkhe.db.models import (
    Ark,
    ArkChange,
    AuditEvent,
    Manager,
    Naan,
    Shoulder,
    ShoulderStatus,
    UnknownSubject,
)
from arkhe.errors import ApiError


class NotFound(ApiError):
    status = 404


class Invalid(ApiError):
    status = 400


class Conflict(ApiError):
    """The values and the permissions are right, but the row is not in that state.

    It is neither 400 nor 403 because sending it again may not help, and yet nothing was
    sent wrongly. Deleting an ARK that has been published, or deleting a name before its
    parts, arrives here.
    """

    status = 409


class Throttled(ApiError):
    status = 429


class ShoulderDelegated(Forbidden):
    """Minting happens at an outside minter, not here. The answer says where.

    Nothing is proxied. Proxying would mean tracking who consumed the namespace in two
    places, and a lost response could leave an ARK naming nothing on either side. An ARK
    declares NR, so that cannot be taken back.
    """

    def __init__(self, shoulder: Shoulder):
        self.minter = shoulder.minter
        if shoulder.minter:
            # There is an endpoint a machine can call. Point at it with 307 rather
            # than calling on its behalf.
            super().__init__(
                errors.SHOULDER_DELEGATED,
                shoulder=shoulder.shoulder,
                minter=shoulder.minter,
                note=shoulder.note,
            )
        else:
            # There is no endpoint, on a closed network for instance. A 307 to a page
            # for people would make clients POST to that page, so it stops with 403 and
            # puts the guidance in the body. about is included when there is one; a
            # delegation without one is valid, and then the answer is simply that we do
            # not mint here.
            extra = {"about": shoulder.about} if shoulder.about else {}
            super().__init__(
                errors.SHOULDER_DELEGATED_UNREACHABLE,
                shoulder=shoulder.shoulder,
                note=shoulder.note,
                **extra,
            )


#: The scopes arkhe actually checks; this is the whole vocabulary. The choices on the
#: screens and the client scopes registered at an authorisation server follow it. Spread
#: across several places, a scope could be registrable without being checked anywhere.
SCOPES = (
    "ark:mint", "ark:update", "ark:read", "ark:tombstone", "ark:hold", "ark:import",
    "ark:delete", "ark:unpublish", "ark:purge",
)


def require_scope(principal: Principal, scope: str) -> None:
    if not principal.has(scope):
        raise InsufficientScope(scope)


def shoulder_for(session: Session, principal: Principal, requested: str | None) -> Shoulder:
    """Decide which shoulder this principal mints into.

    The shoulder in the request is optional. Omitted, the organisation's
    default_shoulder is used; named, it is only checked against the principal's reach
    and never widens it.
    """
    if principal.is_naan_wide:
        # A NAAN-level principal (or the system administrator, over every NAAN) may
        # use any of them, but has to name one: with no default, nobody mints into
        # another organisation's shoulder by accident.
        if not requested:
            raise Invalid(errors.SHOULDER_REQUIRED, authority=principal.authority)
        stmt = select(Shoulder).where(Shoulder.shoulder == requested)
        if not principal.is_system:
            stmt = stmt.where(Shoulder.naan == principal.naan)
        found = session.scalars(stmt).all()
        if not found:
            raise Invalid(errors.SHOULDER_UNKNOWN, shoulder=requested)
        if len(found) > 1:
            # The system administrator reaches every NAAN, so the same shoulder
            # string can exist under several. None of them is chosen for you.
            raise Invalid(
                errors.SHOULDER_AMBIGUOUS,
                shoulder=requested,
                naans=sorted(x.naan for x in found),
            )
        return found[0]

    if principal.manager_id is None:
        raise Forbidden(errors.NO_ORGANISATION)
    manager = session.get(Manager, principal.manager_id)
    if manager is None or not manager.active:
        raise Forbidden(errors.NO_ORGANISATION)

    # A principal pinned to a shoulder uses only that one. Several principals sharing
    # a shoulder is ordinary; what they do not share is a credential.
    if principal.shoulder_id is not None:
        fixed = session.get(Shoulder, principal.shoulder_id)
        if fixed is None:
            raise Forbidden(errors.NO_ORGANISATION, shoulder_id=principal.shoulder_id)
        if requested and requested != fixed.shoulder:
            raise Forbidden(errors.OUT_OF_REACH, target=requested)
        return fixed

    if not requested:
        if manager.default_shoulder_id is None:
            raise Invalid(errors.NO_DEFAULT_SHOULDER)
        return session.get(Shoulder, manager.default_shoulder_id)

    found = session.scalar(
        select(Shoulder).where(
            Shoulder.naan == principal.naan,
            Shoulder.shoulder == requested,
            Shoulder.manager_id == manager.id,
        )
    )
    if found is None:
        # Naming another organisation's shoulder is refused the same way as one that
        # does not exist, so nothing reveals which is which.
        raise Forbidden(errors.OUT_OF_REACH, target=requested)
    return found


def assert_reaches_shoulder(session: Session, principal: Principal, shoulder: Shoulder) -> None:
    """Whether this principal may act on a shoulder that has already been identified.

    shoulder_for chooses a shoulder from a name; this authorises one that has been
    chosen. The decision is the same, with a wider authority covering a narrower one:

      system   every NAAN and every shoulder
      naan     every shoulder under that NAAN
      manager  the organisation's own shoulders
      pinned   that one shoulder

    They are separate because import_minted derives the shoulder from the name. The way
    shoulder_for searches, by shoulder string across every NAAN, is ambiguous when the
    same spelling exists under several. An import carries the ARK, which carries the
    NAAN, so it can look the shoulder up unambiguously and then authorise it.
    """
    if not principal.reaches_naan(shoulder.naan):
        raise Forbidden(errors.OUT_OF_REACH, target=shoulder.naan)
    if principal.is_naan_wide:
        return
    if principal.shoulder_id is not None:
        if principal.shoulder_id != shoulder.id:
            raise Forbidden(errors.OUT_OF_REACH, target=shoulder.shoulder)
        return
    if principal.manager_id is None or shoulder.manager_id != principal.manager_id:
        # Refused without revealing whether it exists, as in shoulder_for.
        raise Forbidden(errors.OUT_OF_REACH, target=shoulder.shoulder)


def assert_naan_is_ours(session: Session, naan: str) -> None:
    """Whether this ledger is authoritative for that NAAN.

    An import declares that we take on the record for this name, so it must not happen
    for a NAAN we only forward: that would claim to hold someone else's namespace. It is
    separate from the principal's reach, and both are required.
    """
    row = session.get(Naan, naan)
    if row is None or not row.is_authoritative:
        raise Forbidden(errors.IMPORT_NAAN_NOT_AUTHORITATIVE, naan=naan)


def assert_shoulder_mintable(shoulder: Shoulder) -> None:
    """A reserved, delegated or retired shoulder does not mint."""
    if shoulder.status == ShoulderStatus.ACTIVE:
        return
    if shoulder.status == ShoulderStatus.DELEGATED:
        raise ShoulderDelegated(shoulder)
    raise Forbidden(
        errors.SHOULDER_NOT_MINTABLE,
        shoulder=shoulder.shoulder,
        status=shoulder.status,
        note=shoulder.note,
    )


def assert_may_touch(session: Session, principal: Principal, ark: Ark) -> None:
    """Whether an existing ARK may be touched.

    M3: arklet's update did not look at the shoulder at all, so the target of any ARK
    under the same NAAN could be rewritten. That is worse than minting: it is taking
    over a persistent identifier.
    """
    if not principal.reaches_naan(ark.naan):
        raise Forbidden(errors.OUT_OF_REACH, target=ark.ark, reason="another NAAN")
    if principal.is_naan_wide:
        return
    shoulder = ark.shoulder or session.get(Shoulder, ark.shoulder_id)
    if principal.manager_id is None or shoulder.manager_id != principal.manager_id:
        raise Forbidden(errors.OUT_OF_REACH, target=ark.ark)


def visible_arks(session: Session, principal: Principal, keys: list[str]):
    """M4: reads are bounded by reach too."""
    stmt = select(Ark).where(Ark.ark.in_(keys)).options(selectinload(Ark.shoulder))
    if not principal.is_system:
        stmt = stmt.where(Ark.naan == principal.naan)
    if not principal.is_naan_wide:
        stmt = stmt.join(Shoulder, Ark.shoulder_id == Shoulder.id).where(
            Shoulder.manager_id == principal.manager_id
        )
    return session.scalars(stmt).all()


def fetch_for_update(session: Session, principal: Principal, keys: list[str]) -> dict[str, Ark]:
    """M5: match rows by ARK through a dictionary.

    arklet zipped an unordered queryset with the input, which could write one row's
    values onto a different ARK, and silently truncated when the counts did not match.

    One row missing or out of reach fails the whole request; nothing is applied in
    part.
    """
    found = {a.ark: a for a in visible_arks(session, principal, keys)}
    missing = [k for k in keys if k not in found]
    if missing:
        raise NotFound(errors.ARK_NOT_FOUND, missing=missing[:20], count=len(missing))
    return found


def assert_within_quota(session: Session, principal: Principal, count: int = 1) -> None:
    """R3: the daily minting quota, per organisation. It stops one of them running
    away.

    A null Manager.quota_per_day means no limit. A break-glass principal has no
    organisation and is therefore exempt: it must not stop while an incident is being
    handled.
    """
    if principal.manager_id is None:
        return
    manager = session.get(Manager, principal.manager_id)
    if manager is None or manager.quota_per_day is None:
        return
    since = datetime.now(UTC) - timedelta(days=1)
    used = session.scalar(
        # Name the column being counted rather than using count(*), as domain.stats
        # does, so that an index can answer it.
        select(func.count(Ark.ark))
        .select_from(Ark)
        .join(Shoulder, Ark.shoulder_id == Shoulder.id)
        .where(Shoulder.manager_id == manager.id, Ark.created_at >= since)
    )
    if used + count > manager.quota_per_day:
        raise Throttled(
            errors.QUOTA_EXCEEDED, quota=manager.quota_per_day, used=used, requested=count
        )


def record_sign_in(
    session: Session,
    *,
    action: str,
    client_id: str,
    authority: str = "",
    ip: str = "",
    mechanism: str = "",
    ok: bool = True,
    **detail,
) -> None:
    """Record people arriving and leaving, whoever they are.

    audit() keeps only operations at NAAN level and above; these are kept for everyone.
    Who signed in and when is needed later as much as what they did, and a failed
    sign-in is the record people want to read first.

    Failures where the principal cannot be identified, an unknown username or a wrong
    password, are recorded too, but not with everything that was typed: the log should
    not become a list of usernames, so what remains is that an attempt under that name
    failed.
    """
    session.add(
        AuditEvent(
            client_id=client_id,
            authority=authority,
            action=action,
            target="",
            ip=ip,
            detail={**detail, "mechanism": mechanism, "ok": ok},
        )
    )


def record_unknown_subject(
    session: Session, *, subject: str, issuer: str = "", ip: str = ""
) -> None:
    """Record a principal that arrived from the authorisation server without a
    registration, without adding a row per attempt.

    A misspelt client_id is the most common way a deployment with an authorisation
    server gets stuck. At the moment of refusal the exact string is in hand, since azp
    passed signature verification, so keeping it lets an operator register without
    retyping.

    The count matters because one attempt is a typo while many mean something is
    configured and running, which says how urgent it is. The table cannot grow without
    limit: it is bounded by the number of clients that exist at the authorisation
    server.

    Nothing has to delete rows once they are registered. The list re-reads only what is
    unregistered, so registering removes it.
    """
    row = session.scalar(
        select(UnknownSubject).where(
            UnknownSubject.subject == subject, UnknownSubject.issuer == issuer
        )
    )
    if row is None:
        session.add(UnknownSubject(subject=subject, issuer=issuer, ip=ip))
        return
    row.last_seen = datetime.now(UTC)
    row.seen += 1
    row.ip = ip or row.ip


def record_change(
    session: Session, principal: Principal, ark: Ark, *, action: str, before_url: str
) -> None:
    """Record that an ARK's target changed, whoever changed it.

    Unlike audit(), this is not thinned out by reach: minting and repointing are done by
    organisations, so thinning would drop the changes that matter. A scheme that declares
    NR and says an identifier does not change has to be able to show what changed, when,
    and who did it.
    """
    if before_url == ark.url and action == "update":
        return  # nothing to record when the target did not change
    session.add(
        ArkChange(
            ark=ark.ark,
            action=action,
            before_url=before_url,
            after_url=ark.url,
            by=principal.client_id,
            ip=principal.ip,
        )
    )


def audit(session: Session, principal: Principal, action: str, target: str = "", **detail) -> None:
    """R2: every operation that reaches NAAN level or above is recorded.

    The wider the reach, the more it matters that who did what can be traced afterwards.
    The system administrator reaches every NAAN, so it is included.
    """
    if not principal.is_naan_wide:
        return
    session.add(
        AuditEvent(
            client_id=principal.client_id,
            authority=principal.authority,
            action=action,
            target=target,
            ip=principal.ip,
            detail={**detail, "mechanism": principal.mechanism},
        )
    )
