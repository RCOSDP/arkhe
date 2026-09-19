"""Authentication and reach, with real credentials.

The unit tests substitute authentication and look only at authorisation. This looks at
the part that is not substituted: whether the key the CLI printed opens the door,
whether a stopped principal really stops, and whether a token from client_credentials
works.
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import World

pytestmark = pytest.mark.e2e


def test_no_key_no_minting(world: World):
    r = world.api("post", "/api/mint", key=None, json={"url": "https://example.org/x"})
    assert r.status_code == 401


def test_a_made_up_key_does_not_open_the_door(world: World):
    r = world.api("post", "/api/mint", key="arkhe_" + "z" * 43,
                  json={"url": "https://example.org/x"})
    assert r.status_code == 401


def test_anything_outside_the_scope_is_refused(world: World, published):
    """Scopes are not a hierarchy: holding ark:mint says nothing about reading."""
    r = world.api("get", "/api/stats", key="mint_only")
    assert r.status_code == 403, r.text
    upd = world.api("put", "/api/update", key="mint_only",
                    json={"ark": published["ark"], "url": "https://example.org/nope"})
    assert upd.status_code == 403
    # The scope it does hold still works
    assert world.api("post", "/api/mint", key="mint_only",
                     json={"url": "https://example.org/e2e/mint-only"}).status_code == 201


def test_another_organisation_is_out_of_reach(world: World, published):
    """M4: reads are bounded by reach as well. arklet did no authorisation at all."""
    seen = world.api("post", "/api/query", key="other", json={"data": [published["ark"]]})
    assert seen.status_code == 200
    assert seen.json()["data"] == [], "another organisation's row was readable"

    wrote = world.api("put", "/api/update", key="other",
                      json={"ark": published["ark"], "url": "https://evil.example/x"})
    assert wrote.status_code in (403, 404), wrote.text
    # The target did not move
    assert world.resolve(published["ark"]).headers["location"] == published["url"]


def test_a_stopped_principal_is_locked_out(world: World):
    """Where authentication is delegated, stopping the principal is the only lever: we
    hold no credential to revoke."""
    assert world.api("post", "/api/mint", key="stop",
                     json={"url": "https://example.org/e2e/before-stop"}).status_code == 201
    world.cli("client", "disable", world.seed["clients"]["stop"])
    after = world.api("post", "/api/mint", key="stop",
                      json={"url": "https://example.org/e2e/after-stop"})
    assert after.status_code in (401, 403), after.text


def test_minting_stops_at_the_daily_quota(world: World):
    """R3: the quota stops one organisation from running away. This organisation is
    capped at one ARK a day."""
    first = world.api("post", "/api/mint", key="quota",
                      json={"url": "https://example.org/e2e/quota-1"})
    assert first.status_code == 201, first.text
    second = world.api("post", "/api/mint", key="quota",
                       json={"url": "https://example.org/e2e/quota-2"})
    assert second.status_code in (403, 429), second.text


def test_a_client_credentials_token_can_mint(world: World):
    """RFC 6749 section 4.4, with the credentials in the body."""
    got = world.api("post", "/oauth/token", key=None, data={
        "grant_type": "client_credentials",
        "client_id": world.seed["clients"]["secret"],
        "client_secret": world.keys["secret"],
        "scope": "ark:mint",
    })
    assert got.status_code == 200, got.text
    token = got.json()["access_token"]

    r = world.api("post", "/api/mint", key=token,
                  json={"url": "https://example.org/e2e/by-token"})
    assert r.status_code == 201, r.text
    assert r.json()["ark"].startswith(f"ark:{world.naan}/")


def test_asking_for_an_unregistered_scope_is_refused(world: World):
    """A request cannot widen the reach; that would be privilege escalation. RFC 6749
    section 5.2 calls it invalid_scope, and the scope is not trimmed silently: a client
    that believes it holds a permission would only find out much later."""
    got = world.api("post", "/oauth/token", key=None, data={
        "grant_type": "client_credentials",
        "client_id": world.seed["clients"]["secret"],
        "client_secret": world.keys["secret"],
        "scope": "ark:purge",
    })
    assert got.status_code == 400, got.text
    assert got.json()["error"] == "invalid_scope", got.text


def test_an_unknown_grant_type_is_refused(world: World):
    got = world.api("post", "/oauth/token", key=None, data={
        "grant_type": "password",
        "client_id": world.seed["clients"]["secret"],
        "client_secret": world.keys["secret"],
    })
    assert got.status_code == 400
    assert got.json()["error"]
