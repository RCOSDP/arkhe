"""Local sign-in to the admin interface, for deployments with no identity provider.

Where oidc or proxy is available they are better: identities stay in one place, and
someone leaving is handled entirely on that side. This exists so that an organisation
without one can still run arkhe on its own.

What it guards:

  * nothing is stored in plaintext (Argon2)
  * it does not reveal who exists: an unknown user and a wrong password give the same
    answer, after about the same time
  * it stops guessing: repeated failures lock the account for a while. Offering a login
    page without that leaves it open
  * only a person can have a password; machines do not remember one
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from arkhe.auth.apikey import _expired, _to_principal
from arkhe.auth.errors import AuthError
from arkhe.auth.principal import Principal
from arkhe.db.models import Client, Credential, CredentialKind, Subject

_ph = PasswordHasher()

#: How many failures are allowed and how long the lock lasts. Enough to make guessing
#: impractical without shutting people out for long.
MAX_ATTEMPTS = 5
LOCK_MINUTES = 15
MIN_LENGTH = 12

#: A dummy hash, so that an unknown user costs the same time and timing reveals
#: nothing about who exists.
_DUMMY_HASH = _ph.hash("arkhe-timing-equalizer")


class WeakPassword(ValueError):
    pass


def check_strength(password: str) -> None:
    """Only the length is checked. Demanding symbols and capitals produces strings
    nobody remembers, which end up written down somewhere, as NIST SP 800-63B says."""
    if len(password) < MIN_LENGTH:
        raise WeakPassword(f"the password must be at least {MIN_LENGTH} characters")


def hash_password(password: str) -> str:
    check_strength(password)
    return _ph.hash(password)


def _locked(cred: Credential) -> bool:
    if cred.locked_until is None:
        return False
    until = cred.locked_until
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    return until > datetime.now(UTC)


def authenticate(session: Session, subject: str, password: str) -> Principal:
    """Find the principal for a username and password. No reason is returned."""
    cred = None
    if subject:
        cred = session.scalar(
            select(Credential)
            .join(Client, Credential.client_pk == Client.id)
            .where(
                Client.client_id == subject,
                Credential.kind == CredentialKind.PASSWORD,
                Credential.active.is_(True),
            )
            .options(selectinload(Credential.client).selectinload(Client.manager))
        )

    if cred is None:
        # An unknown user costs the same time. Without this, the speed of the answer
        # says that no such user exists.
        try:
            _ph.verify(_DUMMY_HASH, password or "x")
        except Exception:  # noqa: BLE001 - always fails; spending the time is the point
            pass
        raise AuthError("e.bad_credentials")

    if _locked(cred):
        raise AuthError("e.locked")

    try:
        _ph.verify(cred.hashed, password)
    except (VerifyMismatchError, Exception):  # noqa: B014
        cred.failed_attempts += 1
        if cred.failed_attempts >= MAX_ATTEMPTS:
            cred.locked_until = datetime.now(UTC) + timedelta(minutes=LOCK_MINUTES)
            cred.failed_attempts = 0
        raise AuthError("e.bad_credentials") from None

    client = cred.client
    if client is None or not client.active or _expired(client.expires_at):
        raise AuthError("e.bad_credentials")
    if client.subject_type != Subject.PERSON:
        # A machine should have no password, but the path is closed anyway.
        raise AuthError("e.bad_credentials")
    if _expired(cred.expires_at):
        raise AuthError("e.password_expired")

    cred.failed_attempts = 0
    cred.locked_until = None
    cred.last_used_at = datetime.now(UTC)
    return _to_principal(client, mechanism="password")
