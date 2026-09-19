"""The Python client, against a real minter and a real resolver.

clients/python/tests checks what the client decides on its own, against a stub. This
checks the thing those tests cannot: that what it decides matches what the server
actually does. A stub agrees with whatever it was written to agree with, and a client
that is right about an imagined server is worth nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from arkhe_client import (
    Arkhe,
    BadRequest,
    Conflict,
    Delegated,
    Forbidden,
    NotFound,
    Resolver,
    new_request_id,
)

from .conftest import World

pytestmark = pytest.mark.e2e

TARGET = "https://example.org/e2e/python-client"


@pytest.fixture
def arkhe(world: World):
    """A client holding the API key that reaches everything."""
    with Arkhe(world.minter.url, token=world.keys["ops"]) as client:
        yield client


@pytest.fixture
def resolver(world: World):
    with Resolver(world.resolver.url) as client:
        yield client


def test_what_the_client_mints_is_what_the_resolver_hands_back(arkhe, resolver):
    """The whole point, end to end and across two processes."""
    ark = arkhe.mint(url=TARGET, title="Minted by the Python client")
    assert ark.ark.startswith("ark:")
    assert ark.published, "a mint without reserve is published at once"
    assert resolver.resolve(ark.ark).target == TARGET


def test_a_resend_gets_the_first_ark_back(arkhe):
    """F4, from a caller's side: the key is what makes a retry safe, and resent is how
    the caller can tell one from a new mint."""
    key = new_request_id()
    first = arkhe.mint(url=TARGET, request_id=key)
    again = arkhe.mint(url=TARGET, request_id=key)
    assert again.ark == first.ark
    assert first.resent is False
    assert again.resent is True


def test_a_batch_sent_twice_mints_once(arkhe):
    """An interrupted batch can simply be sent again."""
    rows = [{"url": f"{TARGET}/batch/{i}", "request_id": new_request_id()} for i in range(3)]
    first = arkhe.mint_many(rows, request_ids=False)
    again = arkhe.mint_many(rows, request_ids=False)
    assert first.created == 3
    assert again.created == 0 and again.replayed == 3
    assert [a.ark for a in again] == [a.ark for a in first]


def test_the_pointer_to_another_minter_is_reported_not_followed(world: World, arkhe):
    """The server answers 307 with the other minter in Location. Following it would
    send this organisation's credential to another organisation's endpoint."""
    with pytest.raises(Delegated) as caught:
        arkhe.mint(url=TARGET, shoulder=world.delegated_shoulder)
    assert caught.value.minter == world.delegate_minter
    assert caught.value.code == "ARKHE-1306"


def test_a_refusal_arrives_with_the_code_the_server_sent(world: World):
    """Scopes are not a hierarchy. A credential that may mint may not read, and the
    client hands back the code rather than the wording."""
    with Arkhe(world.minter.url, token=world.keys["mint_only"]) as client:
        with pytest.raises(Forbidden) as caught:
            client.stats()
    assert caught.value.code == "ARKHE-1301"
    assert caught.value.status == 403


def test_a_client_secret_is_exchanged_for_a_token(world: World):
    """The other way in: client_credentials at arkhe's own token endpoint, with no
    authorisation server anywhere."""
    with Arkhe(
        world.minter.url,
        client_id=world.seed["clients"]["secret"],
        client_secret=world.keys["secret"],
        scope="ark:mint",
    ) as client:
        ark = client.mint(url=f"{TARGET}/with-a-token")
        assert ark.ark
        assert client.token(), "no token was kept"


def test_the_whole_life_of_an_ark_through_the_client(arkhe, resolver):
    """Reserved, published, held, released, withdrawn, gone. Each step is checked at
    the resolver, because that is where it shows."""
    ark = arkhe.mint(url=TARGET, title="A life", reserve=True).ark

    with pytest.raises(NotFound):
        resolver.resolve(ark)

    assert arkhe.publish(ark).published
    assert resolver.resolve(ark).target == TARGET

    soon = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    held = arkhe.hold(ark, until=soon, reason="the target moved")
    assert held.held
    stopped = resolver.resolve(ark)
    assert stopped.target is None, "a hold stops the redirect but not the resolution"

    assert not arkhe.release_hold(ark).held
    assert resolver.resolve(ark).target == TARGET

    arkhe.unpublish(ark, reason="the e2e suite is done with it", confirm=ark)
    with pytest.raises(NotFound):
        resolver.resolve(ark)

    gone = arkhe.delete(ark, reason="the e2e suite is done with it", confirm=ark)
    assert gone.ark == ark


def test_a_refusal_with_no_code_still_says_what_was_wrong(arkhe):
    """Not every refusal carries a code. The domain raises some as {field: what is
    wrong}, the shape the admin screens show beside the field, and a client that only
    looked for a code would turn that into a bare 400."""
    ark = arkhe.mint(url=TARGET, reserve=True).ark
    far = (datetime.now(UTC) + timedelta(days=4000)).isoformat()
    with pytest.raises(BadRequest) as caught:
        arkhe.hold(ark, until=far, reason="too long to be temporary")
    assert "ceiling" in str(caught.value)
    assert "until" in caught.value.detail


def test_a_batch_of_reservations_goes_away_in_one_call(arkhe, resolver):
    """The client side of the same thing: reserve a batch for review, throw it away."""
    arks = [arkhe.mint(url=f"{TARGET}/bulk-delete/{i}", reserve=True).ark for i in range(3)]
    gone = arkhe.delete_many(arks, reason="the review was abandoned")
    assert gone == arks
    for ark in arks:
        with pytest.raises(NotFound):
            resolver.resolve(ark)


def test_a_batch_that_holds_a_published_ark_is_refused(arkhe):
    """One published row fails the whole request, and the client hands back the code
    rather than the wording."""
    spare = arkhe.mint(url=f"{TARGET}/keep", reserve=True).ark
    public = arkhe.mint(url=f"{TARGET}/out").ark
    with pytest.raises(Conflict) as caught:
        arkhe.delete_many([spare, public])
    assert caught.value.code in ("ARKHE-1501", "ARKHE-1504")
    assert arkhe.query([spare]), "the batch was applied in part"


def test_patching_changes_one_field_and_leaves_the_rest(arkhe):
    """The difference between PUT and PATCH, against the real server: what a patch does
    not mention keeps its value."""
    ark = arkhe.mint(url=TARGET, title="Before", who="An author").ark
    after = arkhe.patch(ark, title="After")
    assert after.title == "After"
    assert after.who == "An author"
    assert after.url == TARGET


def test_replacing_clears_what_it_leaves_out(arkhe):
    """The same call the other way round, so that nobody reaches for update() when
    they meant patch()."""
    ark = arkhe.mint(url=TARGET, title="Before", who="An author").ark
    after = arkhe.update(ark, url=TARGET, title="After")
    assert after.title == "After"
    assert after.who == "", "update replaces; what it leaves out is cleared"


def test_several_arks_can_be_looked_up_at_once(arkhe):
    """query returns only what is within reach, so a shorter answer than the question
    is normal."""
    made = [arkhe.mint(url=f"{TARGET}/q/{i}").ark for i in range(2)]
    found = {a.ark for a in arkhe.query([*made, "ark:99999/nothing-here"])}
    assert found == set(made)


def test_the_resolver_can_be_asked_about_a_name(arkhe, resolver):
    """?json is the machine-readable inflection, and it never redirects."""
    ark = arkhe.mint(url=TARGET, title="Described").ark
    described = resolver.describe(ark)
    assert described.get("ark", "").endswith(ark.removeprefix("ark:"))
    assert resolver.exists(ark)


def test_the_resolver_says_what_it_holds(world: World, resolver):
    """/.well-known/ark, asked as JSON: the inventory, which needs no credential."""
    inventory = resolver.inventory()
    assert world.naan in str(inventory)


def test_the_ledger_can_be_counted_through_the_client(arkhe):
    counted = arkhe.stats()
    assert counted["arks"] >= 1
