"""The minter client: everything under /api, plus getting a token.

Three things here are not a translation of the OpenAPI document, and they are the
reason this exists rather than a generated stub:

  1. request_id. Minting is the one call that cannot be undone, so a lost answer must
     not leave a number spent with nobody holding it. Every mint carries an idempotency
     key, generated here when the caller does not supply one, and a retry sends the same
     key: the server returns the ARK it minted the first time (F4). Ark.resent says which
     happened.

  2. The 307 to another minter is not followed. httpx would follow it happily and send
     this organisation's credential to another organisation's endpoint. See Delegated.

  3. Refusals arrive as typed exceptions carrying the ARKHE-xxxx code, so callers branch
     on the code and never on the wording.

Nothing is retried that would act twice if it arrived twice. A GET can always be sent
again, and so can a write that carries a request_id; anything else fails with
TransportError and leaves the decision to the caller, who knows whether repeating it is
safe.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

from .errors import (
    DELEGATED,
    Delegated,
    TransportError,
    Unauthorized,
    from_response,
)
from .models import FIELDS, Ark, BulkMint, Withdrawn

__all__ = ["Arkhe"]

#: The keys a row of a batch may carry: the metadata, plus what each call adds.
_MINT_KEYS = frozenset(FIELDS) | {"shoulder", "reserve", "request_id"}
_IMPORT_KEYS = frozenset(FIELDS) | {"ark"}
_UPDATE_KEYS = frozenset(FIELDS) | {"ark"}

#: Answers that mean "try again", as opposed to "this request is wrong". A 500 is not
#: here: it usually means the same request will fail the same way, and repeating it is
#: unlikely to help.
_RETRY_STATUS = frozenset({502, 503, 504})

#: How long before a token expires it is replaced, in seconds. A token that is valid
#: when checked and expired when it arrives is a 401 the caller did nothing to deserve.
_EARLY = 30.0


def _fields(**kw) -> dict:
    """Drop what was not given, so that "not mentioned" and "set to empty" stay
    different things on a PATCH."""
    return {k: v for k, v in kw.items() if v is not None}


def _rows(rows, allowed: frozenset[str], what: str) -> list[dict]:
    """Check a batch before sending it.

    An unknown key would be dropped in silence by the server, and a misspelt title is
    exactly the sort of thing that is noticed weeks later, in the ledger. It is refused
    here instead.
    """
    out = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise TypeError(f"{what}[{i}] is {type(row).__name__}, not a dict")
        unknown = set(row) - allowed
        if unknown:
            raise ValueError(
                f"{what}[{i}] has fields this API does not take: "
                f"{', '.join(sorted(unknown))}"
            )
        out.append({k: v for k, v in row.items() if v is not None})
    return out


class Arkhe:
    """A connection to one arkhe minter.

    Give it a token, or a client id and secret to exchange for one:

        Arkhe("https://mint.example.org", token="...")
        Arkhe("https://mint.example.org", client_id="ops", client_secret="...")

    An API key is sent as the token; there is no separate mode for it, because the
    server accepts either as a bearer credential. With a client id and secret the token
    is fetched from /oauth/token on first use and replaced before it expires.

    It holds a connection pool, so keep one and reuse it. It works as a context manager
    and closing it closes the pool.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str = "",
        client_id: str = "",
        client_secret: str = "",
        scope: str = "",
        timeout: float = 10.0,
        retries: int = 2,
        http: httpx.Client | None = None,
    ):
        if not token and not client_id:
            raise ValueError("pass token=, or client_id= and client_secret=")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._retries = max(0, retries)
        #: When the fetched token stops being usable. 0 means there is none, or it was
        #: handed to us and we cannot know.
        self._expires_at = 0.0
        self._http = http or httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            # Never follow a redirect. /api/mint answers 307 when the shoulder is
            # delegated, and following it would post these credentials to someone
            # else's minter.
            follow_redirects=False,
            headers={"User-Agent": _user_agent()},
        )

    # ------------------------------------------------------------- the calls

    def mint(
        self,
        *,
        url: str | None = None,
        title: str | None = None,
        type: str | None = None,
        identifier: str | None = None,
        format: str | None = None,
        relation: str | None = None,
        source: str | None = None,
        commitment: str | None = None,
        metadata: str | None = None,
        who: str | None = None,
        when: str | None = None,
        shoulder: str | None = None,
        reserve: bool = False,
        request_id: str | None = None,
    ) -> Ark:
        """Mint one ARK. Needs ark:mint.

        The shoulder is the organisation's default unless one is named, and naming one
        can only narrow what the credential already reaches.

        With reserve=True the ARK exists but does not resolve, and can still be deleted.
        Without it, the ARK is published at once and from then on it stays.

        A request_id is generated unless one is given, so that a lost answer and a retry
        cannot mint twice. When the server recognises it, the ARK it minted the first
        time comes back and result.resent is True.
        """
        body = _fields(
            url=url, title=title, type=type, identifier=identifier, format=format,
            relation=relation, source=source, commitment=commitment, metadata=metadata,
            who=who, when=when, shoulder=shoulder,
        )
        body["reserve"] = reserve
        body["request_id"] = request_id or new_request_id()
        status, data = self._call("POST", "/api/mint", json=body, repeatable=True)
        return Ark.of(data, resent=status == 200)

    def mint_bulk(self, rows, *, request_ids: bool = True) -> BulkMint:
        """Mint a batch. Needs ark:mint.

        Each row takes what mint() takes. Rows already minted under the same request_id
        are returned rather than minted again, so an interrupted batch can simply be
        sent again: what got through is not minted twice.

        A request_id is put on every row that has none, which is what makes that true.
        Pass request_ids=False to send the rows exactly as they are.
        """
        data = _rows(rows, _MINT_KEYS, "rows")
        if request_ids:
            for row in data:
                row.setdefault("request_id", new_request_id())
        keyed = all(row.get("request_id") for row in data)
        _, out = self._call("POST", "/api/mint/bulk", json={"data": data},
                            repeatable=keyed)
        return BulkMint.of(out)

    def register(
        self,
        ark: str,
        qualifier: str,
        *,
        url: str | None = None,
        title: str | None = None,
        type: str | None = None,
        identifier: str | None = None,
        format: str | None = None,
        relation: str | None = None,
        source: str | None = None,
        commitment: str | None = None,
        metadata: str | None = None,
        who: str | None = None,
        when: str | None = None,
    ) -> Ark:
        """Register a qualified name under an ARK that already exists. Needs ark:mint.

        The qualifier begins with / for a part or . for a variant, and must point inside
        the base name. Nothing is minted: the number is the one already held.
        """
        body = _fields(
            url=url, title=title, type=type, identifier=identifier, format=format,
            relation=relation, source=source, commitment=commitment, metadata=metadata,
            who=who, when=when,
        )
        body |= {"ark": ark, "qualifier": qualifier}
        _, data = self._call("POST", "/api/register", json=body)
        return Ark.of(data)

    def import_ark(
        self,
        ark: str,
        *,
        url: str | None = None,
        title: str | None = None,
        type: str | None = None,
        identifier: str | None = None,
        format: str | None = None,
        relation: str | None = None,
        source: str | None = None,
        commitment: str | None = None,
        metadata: str | None = None,
        who: str | None = None,
        when: str | None = None,
    ) -> Ark:
        """Take in an ARK that was minted elsewhere, keeping its name. Needs ark:import.

        This is for a migration: names already handed out keep working. The name must
        sit under a shoulder this credential reaches, and one that is already in the
        ledger is refused rather than overwritten.
        """
        body = _fields(
            url=url, title=title, type=type, identifier=identifier, format=format,
            relation=relation, source=source, commitment=commitment, metadata=metadata,
            who=who, when=when,
        )
        body["ark"] = ark
        _, data = self._call("POST", "/api/import", json=body)
        return Ark.of(data)

    def import_bulk(self, rows) -> tuple[list[Ark], int]:
        """Take in a batch. Needs ark:import. Returns the rows and how many there were.

        Each row takes what import_ark() takes, with the ARK under "ark". Nothing is
        minted here, so there is no request_id: an ARK that is already in the ledger is
        refused, which makes a repeat visible rather than silent.
        """
        data = _rows(rows, _IMPORT_KEYS, "rows")
        _, out = self._call("POST", "/api/import/bulk", json={"data": data})
        return [Ark.of(x) for x in out.get("imported", [])], int(out.get("count", 0))

    def update(
        self,
        ark: str,
        *,
        url: str | None = None,
        title: str | None = None,
        type: str | None = None,
        identifier: str | None = None,
        format: str | None = None,
        relation: str | None = None,
        source: str | None = None,
        commitment: str | None = None,
        metadata: str | None = None,
        who: str | None = None,
        when: str | None = None,
    ) -> Ark:
        """Replace what an ARK says. Needs ark:update.

        This is a PUT: what is not passed is cleared. To change one field and leave the
        rest alone, use patch().
        """
        body = _fields(
            url=url, title=title, type=type, identifier=identifier, format=format,
            relation=relation, source=source, commitment=commitment, metadata=metadata,
            who=who, when=when,
        )
        body["ark"] = ark
        _, data = self._call("PUT", "/api/update", json=body)
        return Ark.of(data)

    def patch(
        self,
        ark: str,
        *,
        url: str | None = None,
        title: str | None = None,
        type: str | None = None,
        identifier: str | None = None,
        format: str | None = None,
        relation: str | None = None,
        source: str | None = None,
        commitment: str | None = None,
        metadata: str | None = None,
        who: str | None = None,
        when: str | None = None,
    ) -> Ark:
        """Change only the fields passed, leaving the rest as they are. Needs
        ark:update."""
        body = _fields(
            url=url, title=title, type=type, identifier=identifier, format=format,
            relation=relation, source=source, commitment=commitment, metadata=metadata,
            who=who, when=when,
        )
        body["ark"] = ark
        _, data = self._call("PATCH", "/api/update", json=body)
        return Ark.of(data)

    def update_bulk(self, rows) -> int:
        """Replace a batch, and return how many rows changed. Needs ark:update.

        Like update(), each row replaces: what a row leaves out is cleared. Every ARK
        must be within reach, or nothing is written.
        """
        data = _rows(rows, _UPDATE_KEYS, "rows")
        _, out = self._call("PUT", "/api/update/bulk", json={"data": data})
        return int(out.get("updated", 0))

    def publish(self, ark: str) -> Ark:
        """Publish a reserved ARK, so that it starts resolving. Needs ark:update.

        It can be taken down again with unpublish(), but the first publication is
        recorded for good: from then on the name has been out in the world, and deleting
        it takes purge().
        """
        _, data = self._call("POST", "/api/publish", json={"ark": ark})
        return Ark.of(data)

    def unpublish(self, ark: str, *, reason: str, confirm: str) -> Ark:
        """Stop an ARK resolving. It is not deleted. Needs ark:unpublish.

        confirm must be the ARK again. The server compares it, and this client passes
        on whatever it is given rather than filling it in: the point of the check is
        that a script walking a list cannot take a published name down without a second
        deliberate act, and filling it in here would remove exactly that.
        """
        _, data = self._call(
            "POST", "/api/unpublish",
            json={"ark": ark, "reason": reason, "confirm": confirm},
        )
        return Ark.of(data)

    def delete(self, ark: str, *, reason: str = "", confirm: str = "") -> Withdrawn:
        """Delete an ARK that is not published. Needs ark:delete.

        While it is published this answers 409: take it down first, or use purge(). If
        the name was ever published, a reason and confirm (the ARK again) are required.
        """
        _, data = self._call(
            "POST", "/api/delete",
            json={"ark": ark, "reason": reason, "confirm": confirm},
        )
        return Withdrawn.of(data)

    def delete_bulk(self, arks, *, reason: str = "") -> list[str]:
        """Delete a batch of ARKs that were never published. Needs ark:delete.

        Reserving in bulk is one request, so throwing an abandoned batch away is one
        too. The cheapness is bounded by what is being lost: **one row that is
        published, or that has ever been published, fails the whole request**, and that
        name goes through delete() on its own, with a reason and the ARK typed again.

        Nothing is deleted in part, and every name is still kept and never assigned
        again. Returns the ARKs that are gone, in the order sent.
        """
        _, out = self._call(
            "POST", "/api/delete/bulk", json={"data": list(arks), "reason": reason}
        )
        return list(out.get("withdrawn", []))

    def purge(self, ark: str, *, reason: str, confirm: str) -> Withdrawn:
        """Withdraw and delete a published ARK in one step. Needs ark:purge.

        This is the one operation that breaks the promise the identifier makes, and it
        has its own scope for that reason. Prefer tombstone(), which says the object is
        gone and keeps the name resolving to that statement.
        """
        _, data = self._call(
            "POST", "/api/purge",
            json={"ark": ark, "reason": reason, "confirm": confirm},
        )
        return Withdrawn.of(data)

    def tombstone(self, ark: str, *, url: str = "", commitment: str | None = None) -> Ark:
        """Declare that the object is gone. Needs ark:tombstone.

        The ARK is not deleted and keeps resolving; with no url it resolves to the
        statement itself. This is what to reach for when something has been withdrawn:
        a name that went out keeps answering, and says what happened.
        """
        body = _fields(commitment=commitment)
        body |= {"ark": ark, "url": url}
        _, data = self._call("PUT", "/api/tombstone", json=body)
        return Ark.of(data)

    def hold(self, ark: str, *, until: str, reason: str) -> Ark:
        """Hold redirection until a moment, and say why. Needs ark:hold.

        Resolution does not stop: the description comes back instead of the redirect.
        It is for a delegate that is down or a target handed out by mistake — stop
        quickly without touching the identifier. until is ISO 8601.
        """
        _, data = self._call(
            "PUT", "/api/hold", json={"ark": ark, "until": until, "reason": reason}
        )
        return Ark.of(data)

    def release_hold(self, ark: str) -> Ark:
        """Let redirection resume before the hold would have expired. Needs
        ark:hold."""
        _, data = self._call("PUT", "/api/hold/release", json={"ark": ark})
        return Ark.of(data)

    def query(self, arks) -> list[Ark]:
        """Look up several ARKs at once. Needs ark:read.

        Only what this credential reaches comes back, and an ARK that is not there is
        simply absent from the answer, so the result can be shorter than the input.
        """
        _, out = self._call("POST", "/api/query", json={"data": list(arks)})
        return [Ark.of(x) for x in out.get("data", [])]

    def stats(self, *, naan: str = "", org: str = "") -> dict:
        """Count the ledger, within reach. Needs ark:read.

        This one returns the document as it arrives. It is a report read as a whole
        rather than an object to act on, and naming something out of reach returns zeros
        rather than refusing.
        """
        params = {k: v for k, v in (("naan", naan), ("org", org)) if v}
        _, data = self._call("GET", "/api/stats", params=params, repeatable=True)
        return data

    # ------------------------------------------------------------- the token

    def token(self) -> str:
        """The bearer token in use, fetching one if that is how this client was set up.

        A token handed to the constructor is returned as it is: when it expires only its
        holder can replace it.
        """
        if self._token and (not self._expires_at or time.monotonic() < self._expires_at - _EARLY):
            return self._token
        if not self._client_id:
            return self._token
        return self._fetch_token()

    def _fetch_token(self) -> str:
        """Exchange the client id and secret at /oauth/token (client_credentials)."""
        form = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._scope:
            form["scope"] = self._scope
        try:
            resp = self._http.post("/oauth/token", data=form)
        except httpx.HTTPError as exc:
            raise TransportError(str(exc)) from exc
        body = _read(resp)
        if resp.status_code != 200:
            raise from_response(resp.status_code, body, resp.headers)
        if not isinstance(body, dict) or not body.get("access_token"):
            raise Unauthorized("the token endpoint returned no access_token",
                               status=resp.status_code, detail=body)
        self._token = str(body["access_token"])
        self._expires_at = time.monotonic() + float(body.get("expires_in", 0) or 0)
        return self._token

    # --------------------------------------------------------- sending it off

    def _call(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        repeatable: bool = False,
    ) -> tuple[int, Any]:
        """Send one request, and return (status, body).

        repeatable says whether sending this again can do the work twice. A GET cannot,
        and neither can a mint carrying a request_id, so those are retried when the
        connection fails or the answer says the far end is temporarily unable. Anything
        else is handed back as TransportError with nothing retried, because "it may or
        may not have happened" is a decision for the caller.
        """
        budget = self._retries if repeatable else 0
        refreshed = False
        while True:
            try:
                resp = self._http.request(
                    method, path, json=json, params=params,
                    headers={"Authorization": f"Bearer {self.token()}"},
                )
            except httpx.HTTPError as exc:
                if budget:
                    budget -= 1
                    time.sleep(_backoff(self._retries - budget - 1))
                    continue
                raise TransportError(str(exc)) from exc

            body = _read(resp)
            if resp.status_code == 307:
                raise _delegated(resp, body)
            if resp.status_code == 401 and self._client_id and not refreshed:
                # The token ran out, or the server restarted with another key. Nothing
                # was done, so fetching a new one and sending it again is safe whatever
                # the call was; this does not come out of the retry budget.
                refreshed = True
                self._expires_at = 0.0
                self._token = ""
                continue
            if resp.status_code in _RETRY_STATUS and budget:
                budget -= 1
                time.sleep(_backoff(self._retries - budget - 1))
                continue
            if resp.status_code >= 400:
                raise from_response(resp.status_code, body, resp.headers)
            return resp.status_code, body

    # ------------------------------------------------------------- lifecycle

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Arkhe:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __repr__(self) -> str:
        who = self._client_id or "token"
        return f"<Arkhe {self.base_url} as {who}>"


def new_request_id() -> str:
    """An idempotency key. Anything unique per intended mint will do; this is a uuid4.

    It is worth keeping one of these with the record being minted for. Generated afresh
    on a retry it protects nothing, because the server has no way to see that the two
    requests meant the same thing.
    """
    return uuid.uuid4().hex


def _delegated(resp: httpx.Response, body: Any) -> Delegated:
    """Turn the 307 into an exception that says where to go.

    Not followed, deliberately. The other minter belongs to another organisation and
    will want its own credential; sending this one there hands it over and fails anyway.
    """
    detail = body.get("detail") if isinstance(body, dict) else None
    message = body.get("message", "") if isinstance(body, dict) else ""
    code = body.get("code", DELEGATED) if isinstance(body, dict) else DELEGATED
    return Delegated(
        message or "minting for that shoulder is delegated",
        status=307, code=str(code), detail=detail,
        minter=resp.headers.get("location"),
        about=str(detail.get("about", "")) if isinstance(detail, dict) else "",
    )


def _read(resp: httpx.Response) -> Any:
    """The body as JSON, or as text when it is not JSON.

    What comes back from a load balancer or a proxy in front is often HTML, and losing
    it would leave the caller with a bare status code.
    """
    try:
        return resp.json()
    except ValueError:
        return resp.text


def _backoff(attempt: int) -> float:
    """Wait a little longer each time: 0.2s, 0.4s, 0.8s..."""
    return 0.2 * (2 ** attempt)


def _user_agent() -> str:
    from . import __version__

    return f"arkhe-client/{__version__} python-httpx/{httpx.__version__}"
