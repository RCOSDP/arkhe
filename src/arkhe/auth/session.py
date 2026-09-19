"""Sessions for the admin interface: one signed cookie and nothing else.

There is no session table on the server. Having one would need a shared store, which
does not fit running the resolver, the minter and the admin interface as separate
processes. The cookie holds only the principal and an expiry; the reach is read from the
Client table on each request, so a merger or a revoked credential takes effect from the
next one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

COOKIE = "arkhe_session"
ALGORITHM = "HS256"


def issue(subject: str, *, secret: str, ttl: int, extra: dict | None = None) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl)).timestamp()),
            **(extra or {}),
        },
        secret,
        algorithm=ALGORITHM,
    )


def read(token: str, *, secret: str) -> dict | None:
    """Return None for anything broken or expired; the caller sends them to sign in."""
    try:
        return jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "iat", "sub"]}
        )
    except jwt.PyJWTError:
        return None


def set_cookie(response, token: str, *, ttl: int, secure: bool) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=ttl,
        httponly=True,       # not readable from JavaScript
        samesite="lax",      # not sent when another site links here (CSRF)
        secure=secure,       # only sent over HTTPS
        path="/admin",       # never sent to the API: the two are kept apart
    )


def clear_cookie(response) -> None:
    response.delete_cookie(COOKIE, path="/admin")
