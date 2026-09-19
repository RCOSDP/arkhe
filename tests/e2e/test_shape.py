"""How the assembled system is shaped: the split of roles, and whether it starts.

Three problems were found by this shape and by nothing else:

  * uvicorn arkhe.app:app does not start, because the app is a factory
  * /readyz probed a database the resolver does not read
  * that the resolver has no minting route cannot be seen without building the app
"""

from __future__ import annotations

import json

import httpx
import pytest

from tests.e2e.conftest import World

pytestmark = pytest.mark.e2e


def test_mints_an_ark(world: World, published):
    assert published["ark"].startswith(f"ark:{world.naan}/{world.shoulder.lstrip('/')}")
    assert published["published_at"]


def test_resolver_resolves_it(world: World, published):
    r = world.resolve(published["ark"])
    assert r.status_code == 302
    assert r.headers["location"] == published["url"]


def test_resolver_has_no_minting_route(world: World):
    r = httpx.post(
        f"{world.resolver.url}/api/mint",
        headers={"Authorization": f"Bearer {world.keys['ops']}"},
        json={"url": "https://example.org/x"}, timeout=30,
    )
    assert r.status_code == 404, "the resolver accepted a mint, so the roles are not split"


def test_resolver_has_no_admin_interface(world: World):
    assert httpx.get(f"{world.resolver.url}/admin/", timeout=30).status_code == 404
    # The minter has one. It needs authentication, so what matters here is only that
    # the route exists.
    assert httpx.get(
        f"{world.minter.url}/admin/", follow_redirects=False, timeout=30
    ).status_code != 404


def test_minter_has_no_resolution_route(world: World, published):
    r = httpx.get(
        f"{world.minter.url}/{published['ark']}", follow_redirects=False, timeout=30
    )
    assert r.status_code == 404


def test_readyz_probes_the_database_the_role_reads(world: World):
    """The resolver's write URL points nowhere, so a 200 here means it probed the read
    side. Until 0.11.0 it probed the primary, and kept answering Ready while the replica
    was down."""
    for server in (world.minter, world.resolver):
        assert httpx.get(f"{server.url}/healthz", timeout=30).status_code == 200
        assert httpx.get(f"{server.url}/readyz", timeout=30).status_code == 200


def test_well_known_is_plain_text_by_default_and_json_on_request(world: World):
    plain = httpx.get(f"{world.resolver.url}/.well-known/ark", timeout=30)
    assert plain.status_code == 200
    assert plain.text.strip().endswith("/")

    data = httpx.get(
        f"{world.resolver.url}/.well-known/ark",
        headers={"Accept": "application/json"}, timeout=30,
    )
    assert data.status_code == 200
    json.loads(data.text)


def test_delegated_namespaces_appear_in_well_known(world: World):
    """This list is also what to watch from outside: if an entry disappears, that
    namespace stops working."""
    body = httpx.get(
        f"{world.resolver.url}/.well-known/ark",
        headers={"Accept": "application/json"}, timeout=30,
    ).json()
    assert world.delegated_naan in json.dumps(body, ensure_ascii=False)


def test_the_ledger_can_be_counted(world: World, published):
    r = world.api("get", "/api/stats")
    assert r.status_code == 200, r.text
    assert r.json()["arks"] >= 1


def test_cli_and_api_agree_on_the_count(world: World, published):
    """The screens, the CLI and the API all go through domain.stats. This checks that
    from outside."""
    api = world.api("get", "/api/stats").json()["arks"]
    out = world.cli("stat")
    assert str(api) in out, out


def test_a_fingerprint_can_be_taken(world: World, published):
    """Verifying a restore relies on this command, so check that it works."""
    out = world.cli("fingerprint")
    assert out.strip()
