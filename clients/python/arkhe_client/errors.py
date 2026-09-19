"""What the server refuses with, as exceptions that carry the code.

Every API error answers {"code": "ARKHE-xxxx", "message": ..., "detail": {...}}. The
code is the part that does not move: wording changes with a translation or a change of
tone, so a caller that branches on the message will break one day without anything
failing first.

The class says roughly what happened, by status, and .code says exactly which case it
was. Catch ArkheError for "the call did not work", catch Conflict for "it is in the
wrong state", compare .code when one specific case needs its own path.
"""

from __future__ import annotations

from typing import Any


class ArkheError(Exception):
    """The base of everything this client raises.

    status   the HTTP status
    code     "ARKHE-1005", or "" when the answer carried no code (a proxy, say)
    message  the server's English wording. For people, not for branching
    detail   the structured values behind the wording: limit, missing, shoulder...
    """

    def __init__(
        self,
        message: str = "",
        *,
        status: int = 0,
        code: str = "",
        detail: Any = None,
    ):
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(f"{code}: {message}" if code else (message or f"HTTP {status}"))


class BadRequest(ArkheError):
    """400. A value is wrong, or the request cannot be read."""


class Unauthorized(ArkheError):
    """401. The credential is missing, wrong or expired."""


class Forbidden(ArkheError):
    """403. Authenticated, but not allowed to do this here."""


class Delegated(Forbidden):
    """Minting for that shoulder happens somewhere else.

    The server answers 307 with the other minter in Location, and this client does not
    follow it. Following would send this organisation's credential to another
    organisation's endpoint, which will not accept it, and an ARK minted over there is
    one nobody here knows about. Where to go is reported and the decision is left to the
    caller.

    minter  the endpoint to call, from Location. None when there is none to call:
            then the server answers 403 (ARKHE-1309) instead of 307
    about   a page for people, when the delegation names one
    """

    def __init__(self, message: str = "", *, minter: str | None = None,
                 about: str = "", **kw):
        super().__init__(message, **kw)
        self.minter = minter
        self.about = about


class NotFound(ArkheError):
    """404. No such ARK, at least not within reach."""


class Conflict(ArkheError):
    """409. The values and the permissions are right; the row is in another state."""


class Throttled(ArkheError):
    """429. A limit was reached, usually the organisation's daily quota.

    retry_after is the header when the server sent one, in seconds.
    """

    def __init__(self, message: str = "", *, retry_after: float | None = None, **kw):
        super().__init__(message, **kw)
        self.retry_after = retry_after


class ServerError(ArkheError):
    """5xx. Something failed at the other end."""


class TransportError(ArkheError):
    """The request never produced an answer: DNS, connection, TLS or a timeout.

    It is separate from ServerError because it says something different about a write:
    with no answer, whether it happened is unknown. That is the case request_id exists
    for.
    """


#: The two codes this client acts on rather than only reports. Delegation is the one
#: case where the right move is not "raise what came back": where minting happens is
#: something the caller has to decide about, not an error in the request.
DELEGATED = "ARKHE-1306"              # 307, with the other minter in Location
DELEGATED_UNREACHABLE = "ARKHE-1309"  # 403, with no endpoint to call


#: status -> class, for the ones that mean something specific.
_BY_STATUS = {
    400: BadRequest,
    401: Unauthorized,
    403: Forbidden,
    404: NotFound,
    409: Conflict,
    422: BadRequest,   # FastAPI's own validation answer, with a list in detail
    429: Throttled,
}


def from_response(status: int, body: Any, headers=None) -> ArkheError:
    """Build the exception for an answer that was not a success.

    The body is what the server sent. It is normally the {code, message, detail} shape,
    but anything can arrive from in front of the application, so text is kept as the
    message rather than dropped.
    """
    headers = headers or {}
    code, message, detail = "", "", None
    if isinstance(body, dict):
        code = str(body.get("code", ""))
        message = str(body.get("message", ""))
        detail = body.get("detail")
        # The token endpoint follows RFC 6749 and answers {error, error_description}.
        if not message and "error" in body:
            message = str(body.get("error_description") or body["error"])
        if not message and detail is not None:
            message = str(detail)
        if not code and not message:
            # A refusal with no code. The domain raises some of these as {field: what
            # is wrong}, which the admin screens show next to the field. Losing it
            # would leave the caller with a bare 400, so the whole answer is kept and
            # read out.
            detail = body
            message = "; ".join(f"{k}: {v}" for k, v in body.items())
    elif body:
        message = str(body)[:500]

    if status >= 500:
        return ServerError(message, status=status, code=code, detail=detail)
    cls = _BY_STATUS.get(status, ArkheError)
    if cls is Throttled:
        retry = headers.get("retry-after") or headers.get("Retry-After")
        return Throttled(
            message, status=status, code=code, detail=detail,
            retry_after=float(retry) if retry and str(retry).isdigit() else None,
        )
    if code == DELEGATED_UNREACHABLE:
        # Delegated, with no endpoint to call: a closed network, for instance. The
        # server stops at 403 rather than pointing a client at a page meant for people.
        about = detail.get("about", "") if isinstance(detail, dict) else ""
        return Delegated(
            message, status=status, code=code, detail=detail,
            minter=None, about=str(about),
        )
    return cls(message, status=status, code=code, detail=detail)
