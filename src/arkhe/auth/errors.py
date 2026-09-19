"""Authentication and authorisation failures, kept away from HTTP so that they can be
tested without it."""

from __future__ import annotations

from arkhe import errors
from arkhe.errors import ApiError


class AuthError(ApiError):
    """401: the credentials are missing, wrong or expired."""

    status = 401

    def __init__(self, detail=None, *, challenge: str = "Bearer", **fmt):
        super().__init__(detail if detail is not None else errors.INVALID_CREDENTIALS,
                         challenge=challenge, **fmt)


class UnregisteredSubject(AuthError):
    """The token from the authorisation server is valid, but the principal is not in
    the ledger.

    It is distinguished from AuthError because only here is the record worth keeping.
    The signature has been verified, so subject is what the authorisation server wrote
    and an operator can copy it when registering. A misspelt client_id is the most
    common way this setup gets stuck.
    """

    def __init__(self, subject: str, issuer: str = ""):
        self.subject = subject
        self.issuer = issuer
        super().__init__(f"subject {subject} is not registered with this resolver")


class Forbidden(ApiError):
    """403: authenticated, but out of reach of this operation or namespace."""

    status = 403


class InsufficientScope(Forbidden):
    """403 insufficient_scope, naming the missing scope so the client can fix it."""

    def __init__(self, required: str):
        self.required = required
        super().__init__(errors.INSUFFICIENT_SCOPE, scope=required)
