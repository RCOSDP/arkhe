"""The resolver client: asking where an ARK goes, and what it says about itself.

The resolver is a separate service from the minter, and a public one: it takes no
credential, because resolving an identifier is something anyone may do. That is why it
is a separate class here too — mixing the two would suggest a token is needed to look
something up.

Redirects are not followed. The answer to "where does this ARK go" is the location
itself, and following it would fetch the object, which is the caller's business and not
this library's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .errors import TransportError, from_response

__all__ = ["Resolution", "Resolver"]


@dataclass(frozen=True)
class Resolution:
    """What the resolver answered.

    target       where it redirects, or None when it did not redirect. That is not a
                 failure: a reserved ARK, one whose redirection is held, and a
                 tombstoned one all resolve to a description instead
    description  the description, when one came back
    status       the HTTP status, kept because a redirect to another resolver looks the
                 same as a redirect to the object
    """

    ark: str
    target: str | None = None
    description: dict | None = None
    status: int = 0

    def __bool__(self) -> bool:
        return self.target is not None


class Resolver:
    """A connection to one arkhe resolver.

        with Resolver("https://ark.example.org") as r:
            print(r.resolve("ark:99999/x9abcd").target)

    It works as a context manager and holds a connection pool, so keep one and reuse it.
    """

    def __init__(self, base_url: str, *, timeout: float = 10.0,
                 http: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self._http = http or httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            # The answer is the location, not what is at it.
            follow_redirects=False,
        )

    def resolve(self, ark: str) -> Resolution:
        """Ask where an ARK goes.

        A redirect gives .target. A 200 means the resolver answered with a description
        instead, and .description holds it. An ARK this resolver knows nothing about
        raises NotFound.

        The target can be another resolver: an ARK under a NAAN this ledger does not
        hold is handed on rather than refused, which is how a name keeps working when it
        moves.
        """
        resp = self._get(_path(ark))
        if resp.is_redirect:
            return Resolution(ark, target=resp.headers.get("location"),
                              status=resp.status_code)
        body = _read(resp)
        return Resolution(
            ark,
            description=body if isinstance(body, dict) else None,
            status=resp.status_code,
        )

    def describe(self, ark: str) -> dict:
        """Ask the ARK about itself, with ?json: the machine-readable inflection.

        This never redirects. It is the call to use to find out whether something is
        published, held or tombstoned, rather than where it points.
        """
        body = _read(self._get(_path(ark) + "?json"))
        return body if isinstance(body, dict) else {"raw": body}

    def statement(self, ark: str) -> str:
        """The persistence statement, with ??: what this ledger promises about the
        name.

        It comes back as ERC/ANVL text, which is what ARKs have always returned here.
        """
        body = _read(self._get(_path(ark) + "??"))
        return body if isinstance(body, str) else str(body)

    def inventory(self) -> dict:
        """/.well-known/ark: which NAANs this resolver holds and what it will do with
        the rest.

        Asked as JSON. Without an Accept header the same URL answers the plain-text form
        the specification defines, which is what a person with curl gets.
        """
        body = _read(self._get("/.well-known/ark", accept="application/json"))
        return body if isinstance(body, dict) else {"raw": body}

    def exists(self, ark: str) -> bool:
        """Whether this resolver has the ARK. It answers False for one it does not, and
        for one it would only hand on to another resolver it answers True, because it
        did answer."""
        from .errors import NotFound

        try:
            self.resolve(ark)
        except NotFound:
            return False
        return True

    # ---------------------------------------------------------------- sending

    def _get(self, path: str, *, accept: str = "application/json") -> httpx.Response:
        try:
            resp = self._http.get(path, headers={"Accept": accept})
        except httpx.HTTPError as exc:
            raise TransportError(str(exc)) from exc
        if resp.status_code >= 400:
            raise from_response(resp.status_code, _read(resp), resp.headers)
        return resp

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Resolver:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<Resolver {self.base_url}>"


def _path(ark: str) -> str:
    """The path for an ARK, in the form it arrived in.

    Nothing is encoded or decoded here. A percent encoding inside a name is part of the
    identifier — %2F is not a separator — and decoding it would ask for a different ARK.
    Both ark: and the old ark:/ are passed through as they are, because the resolver
    must answer both in perpetuity.
    """
    return "/" + ark.lstrip("/")


def _read(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text
