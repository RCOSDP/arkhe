"""What the client does that the API document does not say.

The generated part of a client is not worth testing: it either matches the document or
it does not, and test_contract.py checks that mechanically. What is worth testing is the
three decisions this library makes on the caller's behalf, because each of them is a
decision that could go wrong quietly:

  - a mint carries an idempotency key, and a retry reuses it
  - the 307 to another minter is not followed
  - a refusal arrives as an exception carrying the ARKHE-xxxx code

Everything here runs against a stub, so it is fast and says nothing about whether the
real server behaves this way. tests/e2e/test_python_client.py in the server repository
runs the same client against a real one.
"""

from __future__ import annotations

import json as jsonlib

import httpx
import pytest

from arkhe_client import (
    Arkhe,
    Conflict,
    Delegated,
    Resolver,
    Throttled,
    TransportError,
    Unauthorized,
)


def stub(handler, **kw):
    """An Arkhe pointed at a function instead of a server."""
    http = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://mint.example.org",
        follow_redirects=False,
    )
    return Arkhe("https://mint.example.org", token="t", http=http, **kw)


def minted(request, **extra):
    body = {"ark": "ark:99999/x9tn1qkq2g7", "url": "", "title": "", **extra}
    return httpx.Response(201, json=body)


def sent(request) -> dict:
    return jsonlib.loads(request.content)


# ------------------------------------------------------ the idempotency key


def test_every_mint_carries_a_key():
    """Minting is the one call that cannot be taken back, so a lost answer must not
    leave a number spent with nobody holding it."""
    seen = {}

    def handler(request):
        seen.update(sent(request))
        return minted(request)

    with stub(handler) as arkhe:
        arkhe.mint(url="https://example.org/1")
    assert seen["request_id"], "no request_id was sent"


def test_a_key_the_caller_gives_is_the_one_used():
    """The useful key is the one kept beside the record being minted for. Generated
    afresh on a retry it protects nothing."""
    seen = {}

    def handler(request):
        seen.update(sent(request))
        return minted(request)

    with stub(handler) as arkhe:
        arkhe.mint(url="https://example.org/1", request_id="row-4471")
    assert seen["request_id"] == "row-4471"


def test_a_resend_is_reported_rather_than_hidden():
    """200 means the server returned the ARK it minted the first time. A caller
    counting how many it created has to be able to tell."""
    with stub(lambda r: httpx.Response(200, json={"ark": "ark:99999/x9tn1qkq2g7"})) as arkhe:
        ark = arkhe.mint(url="https://example.org/1")
    assert ark.resent is True


def test_a_lost_answer_is_sent_again_with_the_same_key():
    """This is what the key is for. The connection fails, the client retries, and the
    server either mints once or returns what it minted before."""
    keys, tries = [], []

    def handler(request):
        keys.append(sent(request)["request_id"])
        tries.append(1)
        if len(tries) == 1:
            raise httpx.ConnectError("connection reset")
        return httpx.Response(200, json={"ark": "ark:99999/x9tn1qkq2g7"})

    with stub(handler, retries=1) as arkhe:
        ark = arkhe.mint(url="https://example.org/1")
    assert len(tries) == 2
    assert keys[0] == keys[1], "the retry drew a new key, which protects nothing"
    assert ark.resent is True


def test_a_write_that_cannot_be_repeated_is_not_repeated():
    """Without a key, a retry could act twice. The client stops and says the answer was
    never seen, which is a decision for the caller rather than this library."""
    tries = []

    def handler(request):
        tries.append(1)
        raise httpx.ConnectError("connection reset")

    with stub(handler, retries=3) as arkhe:
        with pytest.raises(TransportError):
            arkhe.update("ark:99999/x9tn1qkq2g7", url="https://example.org/2")
    assert len(tries) == 1


def test_a_batch_with_no_keys_is_not_repeated_either():
    """mint_many puts a key on every row unless it is told not to. Told not to, it
    loses the right to retry with it."""
    tries = []

    def handler(request):
        tries.append(1)
        raise httpx.ConnectError("connection reset")

    with stub(handler, retries=3) as arkhe:
        with pytest.raises(TransportError):
            arkhe.mint_many([{"url": "https://example.org/1"}], request_ids=False)
    assert len(tries) == 1


def test_every_row_of_a_batch_gets_its_own_key():
    """One key for the whole batch would make the server treat every row as the same
    request."""
    seen = {}

    def handler(request):
        seen.update(sent(request))
        return httpx.Response(201, json={"minted": [], "created": 0, "replayed": 0})

    with stub(handler) as arkhe:
        arkhe.mint_many([{"url": "https://example.org/1"}, {"url": "https://example.org/2"}])
    keys = [row["request_id"] for row in seen["data"]]
    assert len(set(keys)) == 2


# --------------------------------------------------------------- delegation


def test_the_pointer_to_another_minter_is_not_followed():
    """Following it would send this organisation's credential to another
    organisation's endpoint: it will not be accepted there, and an ARK minted over there
    is one nobody here knows about."""
    def handler(request):
        return httpx.Response(
            307,
            headers={"Location": "https://mint.partner.example.org/api/mint"},
            json={"code": "ARKHE-1306", "message": "delegated",
                  "detail": {"shoulder": "/z1"}},
        )

    with stub(handler) as arkhe:
        with pytest.raises(Delegated) as caught:
            arkhe.mint(url="https://example.org/1")
    assert caught.value.minter == "https://mint.partner.example.org/api/mint"
    assert caught.value.code == "ARKHE-1306"


def test_a_delegation_with_nowhere_to_call_says_where_to_read():
    """On a closed network there is no endpoint. The server stops at 403 rather than
    pointing a client at a page written for people, and the guidance is in the body."""
    def handler(request):
        return httpx.Response(
            403,
            json={"code": "ARKHE-1309", "message": "minting happens elsewhere",
                  "detail": {"shoulder": "/z1", "about": "https://wiki.example.org/arks"}},
        )

    with stub(handler) as arkhe:
        with pytest.raises(Delegated) as caught:
            arkhe.mint(url="https://example.org/1")
    assert caught.value.minter is None
    assert caught.value.about == "https://wiki.example.org/arks"


# ------------------------------------------------------------- what refusals say


def test_a_refusal_arrives_with_its_code():
    """Wording changes with a translation or a change of tone; the code does not. A
    caller that had to match on the message would break without anything failing
    first."""
    def handler(request):
        return httpx.Response(
            409, json={"code": "ARKHE-1501", "message": "It is published.",
                       "detail": {"ark": "ark:99999/x9tn1qkq2g7"}}
        )

    with stub(handler) as arkhe:
        with pytest.raises(Conflict) as caught:
            arkhe.delete("ark:99999/x9tn1qkq2g7")
    assert caught.value.code == "ARKHE-1501"
    assert caught.value.status == 409
    assert caught.value.detail == {"ark": "ark:99999/x9tn1qkq2g7"}


def test_a_quota_answer_says_when_to_come_back():
    """A batch loader that sleeps for a fixed minute either wastes time or comes back
    too early. When the server says how long, it is handed over."""
    def handler(request):
        return httpx.Response(
            429, headers={"Retry-After": "120"},
            json={"code": "ARKHE-1601", "message": "the daily quota is used up",
                  "detail": {"limit": 1}},
        )

    with stub(handler) as arkhe:
        with pytest.raises(Throttled) as caught:
            arkhe.mint(url="https://example.org/1")
    assert caught.value.retry_after == 120
    assert caught.value.detail == {"limit": 1}


def test_an_answer_that_is_not_json_is_still_reported():
    """What comes back from a proxy in front is often HTML. Dropping it would leave the
    caller with a bare status code."""
    def handler(request):
        return httpx.Response(502, text="<html>bad gateway</html>")

    with stub(handler, retries=0) as arkhe:
        with pytest.raises(Exception) as caught:
            arkhe.mint(url="https://example.org/1")
    assert "bad gateway" in str(caught.value)


# ------------------------------------------------------------------- tokens


def test_a_token_is_fetched_once_and_reused():
    """Every call fetching its own token would cost a round trip each time, and the
    server hashes a secret on each one."""
    fetches, calls = [], []

    def handler(request):
        if request.url.path == "/oauth/token":
            fetches.append(request.content.decode())
            return httpx.Response(200, json={"access_token": "abc", "expires_in": 3600})
        calls.append(request.headers["Authorization"])
        return minted(request)

    http = httpx.Client(transport=httpx.MockTransport(handler),
                        base_url="https://mint.example.org", follow_redirects=False)
    with Arkhe("https://mint.example.org", client_id="ops", client_secret="s",
               http=http) as arkhe:
        arkhe.mint(url="https://example.org/1")
        arkhe.mint(url="https://example.org/2")
    assert len(fetches) == 1
    assert calls == ["Bearer abc", "Bearer abc"]
    assert "grant_type=client_credentials" in fetches[0]


def test_a_token_that_stopped_working_is_replaced_once():
    """A server restart with another key, or a token that expired early, is a 401 the
    caller did nothing to deserve. Nothing was done, so sending it again is safe."""
    tokens = iter(["first", "second"])
    seen = []

    def handler(request):
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": next(tokens),
                                             "expires_in": 3600})
        seen.append(request.headers["Authorization"])
        if len(seen) == 1:
            return httpx.Response(401, json={"code": "ARKHE-1201", "message": "expired"})
        return minted(request)

    http = httpx.Client(transport=httpx.MockTransport(handler),
                        base_url="https://mint.example.org", follow_redirects=False)
    with Arkhe("https://mint.example.org", client_id="ops", client_secret="s",
               http=http) as arkhe:
        arkhe.mint(url="https://example.org/1")
    assert seen == ["Bearer first", "Bearer second"]


def test_a_401_that_survives_a_new_token_is_raised():
    """Otherwise a wrong secret would loop for ever."""
    def handler(request):
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "x", "expires_in": 3600})
        return httpx.Response(401, json={"code": "ARKHE-1202", "message": "no"})

    http = httpx.Client(transport=httpx.MockTransport(handler),
                        base_url="https://mint.example.org", follow_redirects=False)
    with Arkhe("https://mint.example.org", client_id="ops", client_secret="s",
               http=http) as arkhe:
        with pytest.raises(Unauthorized):
            arkhe.mint(url="https://example.org/1")


def test_a_client_needs_something_to_authenticate_with():
    with pytest.raises(ValueError):
        Arkhe("https://mint.example.org")


# ---------------------------------------------------------- what gets sent


def test_patch_sends_only_what_it_was_given():
    """"Not mentioned" and "set to empty" are different instructions. If the client
    filled in the rest, a patch would quietly clear the fields it did not touch."""
    seen = {}

    def handler(request):
        seen.update(sent(request))
        return httpx.Response(200, json={"ark": "ark:99999/x9tn1qkq2g7"})

    with stub(handler) as arkhe:
        arkhe.patch("ark:99999/x9tn1qkq2g7", title="A new title")
    assert seen == {"ark": "ark:99999/x9tn1qkq2g7", "title": "A new title"}


def test_taking_a_name_down_needs_the_confirmation_typed_out():
    """The server compares confirm with the ARK. This client passes on whatever it is
    given and never fills it in: the check exists so that a script walking a list cannot
    take a published name down without a second deliberate act, and filling it in here
    would remove exactly that."""
    seen = {}

    def handler(request):
        seen.update(sent(request))
        return httpx.Response(200, json={"ark": "ark:99999/x9tn1qkq2g7"})

    with stub(handler) as arkhe:
        arkhe.unpublish("ark:99999/x9tn1qkq2g7", reason="wrong record", confirm="")
    assert seen["confirm"] == "", "the client filled the confirmation in by itself"


def test_a_misspelt_field_in_a_batch_is_refused_here():
    """The server ignores what it does not know, so a misspelt title would be noticed
    weeks later, in the ledger."""
    with stub(lambda r: minted(r)) as arkhe:
        with pytest.raises(ValueError) as caught:
            arkhe.mint_many([{"titel": "typo"}])
    assert "titel" in str(caught.value)


def test_timestamps_come_back_as_datetimes():
    def handler(request):
        return httpx.Response(201, json={
            "ark": "ark:99999/x9tn1qkq2g7",
            "created_at": "2026-09-19T01:02:03+00:00",
            "published_at": None,
        })

    with stub(handler) as arkhe:
        ark = arkhe.mint(url="https://example.org/1")
    assert ark.created_at.year == 2026
    assert ark.published is False, "an ARK with no published_at does not resolve yet"


def test_an_unreadable_timestamp_does_not_lose_the_answer():
    """The write happened. Raising while reading a successful answer would be worse
    than handing back what arrived, and .raw still has it."""
    def handler(request):
        return httpx.Response(201, json={"ark": "ark:99999/x9tn1qkq2g7",
                                         "created_at": "some day"})

    with stub(handler) as arkhe:
        ark = arkhe.mint(url="https://example.org/1")
    assert ark.created_at is None
    assert ark.raw["created_at"] == "some day"


# ----------------------------------------------------------------- resolving


def resolver_stub(handler):
    http = httpx.Client(transport=httpx.MockTransport(handler),
                        base_url="https://ark.example.org", follow_redirects=False)
    return Resolver("https://ark.example.org", http=http)


def test_resolution_reports_where_it_goes_without_going_there():
    """The answer to "where does this ARK go" is the location. Following it would
    fetch the object, which is the caller's business."""
    def handler(request):
        assert request.url.path == "/ark:99999/x9tn1qkq2g7"
        return httpx.Response(302, headers={"Location": "https://repo.example.ac.jp/1"})

    with resolver_stub(handler) as resolver:
        found = resolver.resolve("ark:99999/x9tn1qkq2g7")
    assert found.target == "https://repo.example.ac.jp/1"
    assert found


def test_a_description_instead_of_a_redirect_is_not_a_failure():
    """A reserved ARK, one whose redirection is held and a tombstoned one all resolve
    to a description. Treating that as an error would make a held ARK look broken."""
    def handler(request):
        return httpx.Response(200, json={"ark": "ark:99999/x9tn1qkq2g7",
                                         "hold_reason": "the target moved"})

    with resolver_stub(handler) as resolver:
        found = resolver.resolve("ark:99999/x9tn1qkq2g7")
    assert found.target is None
    assert not found
    assert found.description["hold_reason"] == "the target moved"


def test_the_json_inflection_is_asked_for_as_the_specification_writes_it():
    """?json is the query string itself, not a parameter with a value. Sent as
    ?json= the resolver would not recognise it and would redirect instead."""
    seen = {}

    def handler(request):
        seen["query"] = request.url.query.decode()
        return httpx.Response(200, json={"ark": "ark:99999/x9tn1qkq2g7"})

    with resolver_stub(handler) as resolver:
        resolver.describe("ark:99999/x9tn1qkq2g7")
    assert seen["query"] == "json"


def test_the_old_ark_slash_form_is_passed_through_untouched():
    """Both ark: and ark:/ must be answered in perpetuity, and rewriting an identifier
    on the way out is not this library's business."""
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(302, headers={"Location": "https://repo.example.ac.jp/1"})

    with resolver_stub(handler) as resolver:
        resolver.resolve("ark:/99999/e1abc123")
    assert seen["path"] == "/ark:/99999/e1abc123"


def test_a_refusal_with_no_code_keeps_what_it_said():
    """Not every refusal carries a code. The domain raises some as {field: what is
    wrong}, which is the shape the admin screens show beside the field. Reading it as
    "no message" would leave the caller with a bare 400."""
    def handler(request):
        return httpx.Response(400, json={
            "until": "the expiry is beyond the ceiling of 90 days",
            "reason": "a long hold is no different from a permanent one",
        })

    with stub(handler) as arkhe:
        with pytest.raises(Exception) as caught:
            arkhe.hold("ark:99999/x9tn1qkq2g7", until="2099-01-01T00:00:00Z", reason="x")
    assert "ceiling" in str(caught.value)
    assert caught.value.detail["until"].startswith("the expiry")


def test_a_batch_delete_sends_what_it_was_given_and_nothing_more():
    """The batch path is only for names nobody has seen, so there is no confirmation to
    fill in: the server refuses the whole request if one row has ever been public."""
    seen = {}

    def handler(request):
        seen.update(sent(request))
        return httpx.Response(200, json={"withdrawn": ["ark:99999/x9tn1qkq2g7"], "count": 1})

    with stub(handler) as arkhe:
        gone = arkhe.delete_many(["ark:99999/x9tn1qkq2g7"], reason="abandoned")
    assert seen == {"data": ["ark:99999/x9tn1qkq2g7"], "reason": "abandoned"}
    assert gone == ["ark:99999/x9tn1qkq2g7"]
