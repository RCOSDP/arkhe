"""The whole life of an ARK: reserved, published, withdrawn, republished, deleted.

The unit tests cover each step on its own. What this covers is the gaps between steps:
whether what the minter wrote is visible to the resolver in another process.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.e2e

TARGET = "https://example.org/e2e/lifecycle"


def test_a_resend_of_one_request_id_mints_nothing_new(world, published):
    """F4: a lost response must not leave dead numbers behind."""
    r = world.api("post", "/api/mint",
                  json={"url": published["url"], "request_id": "e2e-shared"})
    assert r.status_code == 200, r.text
    assert r.json()["ark"] == published["ark"]


def test_a_reserved_ark_resolves_only_once_published(world, mint):
    """A reserved ARK is treated like a name that was never registered, so ?info does
    not show it either."""
    ark = mint(url=TARGET, reserve=True)["ark"]
    assert ark
    assert world.resolve(ark).status_code == 404
    assert world.resolve(ark, "?info").status_code == 404

    r = world.api("post", "/api/publish", json={"ark": ark})
    assert r.status_code == 200, r.text
    assert world.resolve(ark).headers["location"] == TARGET


def test_withdrawing_stops_resolution_and_publishing_again_restores_it(world, mint):
    """Publication can be reversed. The name is never reassigned, so an old reference
    keeps getting 404 rather than a different object."""
    ark = mint(url=TARGET)["ark"]
    assert world.resolve(ark).status_code == 302

    r = world.api("post", "/api/unpublish",
                  json={"ark": ark, "reason": "withdrawn by the e2e suite", "confirm": ark})
    assert r.status_code == 200, r.text
    assert world.resolve(ark).status_code == 404

    assert world.api("post", "/api/publish", json={"ark": ark}).status_code == 200
    assert world.resolve(ark).status_code == 302


def test_an_ark_never_published_can_be_deleted_without_a_reason(world, mint):
    """Only the unpublished can go this way. The name is kept in WithdrawnName and is
    never assigned again."""
    ark = mint(url=TARGET, reserve=True)["ark"]
    r = world.api("post", "/api/delete", json={"ark": ark})
    assert r.status_code in (200, 204), r.text
    assert world.resolve(ark).status_code == 404
    # Check from the read side that it is really gone
    q = world.api("post", "/api/query", json={"data": [ark]})
    assert q.json()["data"] == []


def test_an_ark_once_published_needs_a_reason_and_a_confirmation(world, mint):
    """Having been published is permanent. Even after withdrawal, deleting it takes a
    reason and the ARK typed again."""
    ark = mint(url=TARGET)["ark"]
    world.api("post", "/api/unpublish",
              json={"ark": ark, "reason": "withdrawn before deleting", "confirm": ark})

    bare = world.api("post", "/api/delete", json={"ark": ark})
    assert bare.status_code in (400, 409, 422), bare.text

    ok = world.api("post", "/api/delete",
                   json={"ark": ark, "reason": "deleted by the e2e suite", "confirm": ark})
    assert ok.status_code in (200, 204), ok.text


def test_a_published_ark_cannot_be_deleted_before_withdrawal(world, mint):
    ark = mint(url=TARGET)["ark"]
    r = world.api("post", "/api/delete",
                  json={"ark": ark, "reason": "delete it", "confirm": ark})
    assert r.status_code == 409, r.text
    assert world.resolve(ark).status_code == 302  # it still resolves


def test_resolution_follows_a_changed_target(world, mint):
    """What the minter writes has to be visible to the resolver process."""
    ark = mint(url=TARGET)["ark"]
    moved = "https://example.org/e2e/moved"
    r = world.api("put", "/api/update", json={"ark": ark, "url": moved})
    assert r.status_code == 200, r.text
    assert world.resolve(ark).headers["location"] == moved


def test_everything_minted_in_bulk_resolves(world):
    """Bulk minting divides one authentication over many rows. Check that every row it
    minted can really be looked up."""
    r = world.api("post", "/api/mint/bulk", json={"data": [
        {"url": f"https://example.org/e2e/bulk/{i}"} for i in range(5)
    ]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created"] == 5
    for i, row in enumerate(body["minted"]):
        got = world.resolve(row["ark"])
        assert got.status_code == 302
        assert got.headers["location"] == f"https://example.org/e2e/bulk/{i}"


def test_an_explicit_qualifier_beats_the_inherited_one(world, mint):
    """B4: a qualifier inherits by default, but one part can be registered elsewhere."""
    base = mint(url=TARGET)["ark"]
    special = "https://example.org/e2e/elsewhere"
    r = world.api("post", "/api/register",
                  json={"ark": base, "qualifier": "/part1", "url": special})
    assert r.status_code == 201, r.text
    assert world.resolve(base, "/part1").headers["location"] == special
    # A sibling that was not registered still inherits
    assert world.resolve(base, "/part2").headers["location"].endswith("/part2")


def test_a_hold_stops_redirection_and_keeps_describing(world, mint):
    """404 would be untrue, because the identifier exists, and 503 makes it look broken.
    A hold answers 200 with a description instead."""
    ark = mint(url=TARGET)["ark"]
    until = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    r = world.api("put", "/api/hold",
                  json={"ark": ark, "until": until, "reason": "held by the e2e suite"})
    assert r.status_code == 200, r.text

    held = world.resolve(ark)
    assert held.status_code == 200
    assert "held by the e2e suite" in held.text  # the reason is published

    assert world.api("put", "/api/hold/release", json={"ark": ark}).status_code == 200
    assert world.resolve(ark).status_code == 302


def test_a_tombstone_keeps_the_identifier_and_drops_reachability(world, mint):
    """With NR declared, the identifier cannot be removed. Only the target can."""
    ark = mint(url=TARGET)["ark"]
    r = world.api("put", "/api/tombstone", json={"ark": ark, "url": ""})
    assert r.status_code == 200, r.text

    gone = world.resolve(ark)
    assert gone.status_code == 200          # not 404: the name still exists
    assert world.api("post", "/api/query", json={"data": [ark]}).json()["data"]
