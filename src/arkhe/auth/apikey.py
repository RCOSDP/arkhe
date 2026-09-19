"""API key authentication, as arklet did it, with everything inside arkhe.

arklet attached a Key to a NAAN and hash-checked Authorization: Bearer <key> against
every row. Two things are different here.

1. A prefix narrows it to one row before hashing. Looping over every key gets linearly
   slower as they accumulate, and Argon2 is deliberately expensive. The prefix is the
   first eight characters of the plaintext and is not a secret: it is not a key on its
   own.
2. A key belongs to a Client, not to a NAAN. arklet could only authorise per NAAN, so
   anyone could mint into another organisation's namespace under the same NAAN (M3).
   The reach belongs to the Client.
"""

from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from arkhe import errors
from arkhe.auth.errors import AuthError
from arkhe.auth.principal import Principal
from arkhe.db.models import Client, Credential, CredentialKind, Subject

_ph = PasswordHasher()

#: The shape of a plaintext key. The arkhe_ prefix makes it recognisable, so it can be
#: grepped for after a leak; secret scanners prefer this shape too.
KEY_PREFIX = "arkhe_"
PREFIX_LEN = 8


def generate_key() -> tuple[str, str, str]:
    """Make a new API key, returning (plaintext, prefix, hash).

    The plaintext exists only here. The caller shows it once and does not store it.
    """
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:PREFIX_LEN], _ph.hash(raw)


def _expired(at: datetime | None) -> bool:
    if at is None:
        return False
    if at.tzinfo is None:  # SQLite drops the time zone
        at = at.replace(tzinfo=UTC)
    return at <= datetime.now(UTC)


def authenticate(session: Session, raw: str) -> Principal:
    """Find the principal for a plaintext key. Every failure is a plain 401.

    A missing key and an expired one are not distinguishable to the caller; if they
    were, valid keys could be found by trying.
    """
    if not raw:
        raise AuthError(errors.NO_CREDENTIALS)

    rows = session.scalars(
        select(Credential)
        .where(
            Credential.prefix == raw[:PREFIX_LEN],
            Credential.kind == CredentialKind.API_KEY.value,
            Credential.active.is_(True),
        )
        .options(selectinload(Credential.client).selectinload(Client.manager))
    ).all()

    for cred in rows:
        try:
            _ph.verify(cred.hashed, raw)
        except (VerifyMismatchError, Exception):  # noqa: B014 - a broken hash is a mismatch
            continue
        if _expired(cred.expires_at):
            continue
        client = cred.client
        if client is None or not client.active or _expired(client.expires_at):
            continue
        # A person cannot authenticate with a credential. Identity is vouched for
        # elsewhere, and a key held here would still work after the account was
        # disabled there.
        if client.subject_type != Subject.MACHINE:
            continue
        # A mechanism the organisation is not allowed to use does not authenticate.
        # Stopping new credentials alone would let keys issued earlier keep working.
        if not _mechanism_allowed(session, client, "apikey"):
            continue
        cred.last_used_at = datetime.now(UTC)
        return _to_principal(client, mechanism="apikey")

    # With no match, spend about as long as a comparison would, so that timing does
    # not reveal whether a key exists.
    hmac.compare_digest(raw, raw)
    raise AuthError(errors.INVALID_CREDENTIALS)


def _mechanism_allowed(session: Session, client: Client, mechanism: str) -> bool:
    """Whether this mechanism may be used to get in.

    The rule belongs to the NAAN and the organisation may narrow it, so the decision is
    made on the combined policy (admin_ops.policy_for). Looking only at the organisation
    would let the namespace default slip.
    """
    from arkhe.db.models import Naan
    from arkhe.domain.admin_ops import policy_for

    allowed = policy_for(session.get(Naan, client.naan), client.manager).allowed_auth
    return not allowed or mechanism in allowed.split()


def _to_principal(client: Client, *, mechanism: str) -> Principal:
    return Principal(
        client_id=client.client_id,
        naan=client.naan,
        authority=client.authority,
        manager_id=client.manager_id,
        shoulder_id=client.shoulder_id,
        scopes=frozenset(client.allowed_scopes.split()),
        mechanism=mechanism,
    )
