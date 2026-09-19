"""Settings that lock things down, checked from outside.

ARKHE_ALLOWED_HOSTS was declared as a setting and written up in the guide, but nothing
read it. The unit tests assemble the app themselves, so a middleware that create_app
forgets to install is invisible to them. It only shows up once the app is built.
"""

from __future__ import annotations

import httpx
import pytest

from tests.e2e.conftest import serve, stop

pytestmark = pytest.mark.e2e

HOST = "ark.example.test"


@pytest.fixture(scope="module")
def guarded(world, tmp_path_factory):
    """One resolver with ARKHE_ALLOWED_HOSTS set."""
    logs = tmp_path_factory.mktemp("e2e-hardening")
    env = {**world.env, "ARKHE_RESOLVER": "1",
           "ARKHE_READ_DATABASE_URL": world.env["ARKHE_DATABASE_URL"],
           "ARKHE_ALLOWED_HOSTS": f"{HOST},127.0.0.1"}
    server = serve(env, logs / "guarded.log", "guarded resolver")
    yield server
    stop(server)


def test_an_allowed_host_gets_through(guarded, published):
    r = httpx.get(f"{guarded.url}/{published['ark']}",
                  headers={"Host": HOST}, follow_redirects=False, timeout=30)
    assert r.status_code == 302


def test_a_host_that_was_not_allowed_is_refused(guarded, published):
    """This setting did nothing until 0.9.2. If this goes back to 302, it is dead
    again."""
    r = httpx.get(f"{guarded.url}/{published['ark']}",
                  headers={"Host": "evil.example"}, follow_redirects=False, timeout=30)
    assert r.status_code == 400, f"the Host header was not checked: {r.status_code}"


@pytest.fixture(scope="module")
def closed(world, tmp_path_factory):
    """A resolver for a closed network, which resolves unpublished ARKs in its own
    namespace (ARKHE_RESOLVE_UNPUBLISHED)."""
    logs = tmp_path_factory.mktemp("e2e-closed")
    env = {**world.env, "ARKHE_RESOLVER": "1",
           "ARKHE_READ_DATABASE_URL": world.env["ARKHE_DATABASE_URL"],
           "ARKHE_RESOLVE_UNPUBLISHED": "true"}
    server = serve(env, logs / "closed.log", "closed resolver")
    yield server
    stop(server)


def test_a_closed_resolver_resolves_the_unpublished(world, closed, mint):
    """If ARKs minted inside a closed network cannot be resolved there, handing out
    identifiers for closed objects is pointless. The public resolver still answers 404
    for the same row."""
    target = "https://closed.example.org/object"
    ark = mint(url=target, reserve=True)["ark"]

    inside = httpx.get(f"{closed.url}/{ark}", follow_redirects=False, timeout=30)
    assert inside.status_code == 302
    assert inside.headers["location"] == target

    assert world.resolve(ark).status_code == 404, "the public resolver served a reserved ARK"
