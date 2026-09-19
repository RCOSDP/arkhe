"""Signing in to the admin interface with a password.

The unit tests exercise the screens with a substituted principal. What is covered here
is the entrance itself: the password set by `arkhe client passwd`, the session cookie,
the pages behind it, and whether a form on a page really changes the ledger.
"""

from __future__ import annotations

import httpx
import pytest

from tests.e2e.conftest import World

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def signed_in(world: World) -> httpx.Client:
    """Sign in with the password and keep the cookie."""
    client = httpx.Client(base_url=world.minter.url, follow_redirects=False, timeout=30)
    r = client.post("/admin/login",
                    data={"username": world.admin["username"],
                          "password": world.admin["password"]})
    assert r.status_code == 302, r.text
    assert client.cookies, "no cookie was issued"
    yield client
    client.close()


def _login(world: World, username: str, password: str) -> httpx.Response:
    return httpx.post(f"{world.minter.url}/admin/login",
                      data={"username": username, "password": password},
                      follow_redirects=False, timeout=30)


def test_the_pages_are_not_shown_to_anonymous_callers(world: World):
    r = httpx.get(f"{world.minter.url}/admin/", follow_redirects=False, timeout=30)
    assert r.status_code in (302, 303, 401), r.status_code
    if r.status_code in (302, 303):
        assert "/admin/login" in r.headers["location"]


def test_a_wrong_password_does_not_get_in(world: World):
    r = _login(world, world.admin["username"], "wrong")
    assert r.status_code == 401
    assert not r.cookies, "a cookie was issued without signing in"


def test_an_unknown_user_is_refused_the_same_way(world: World):
    """The two refusals must not differ. If they did, the list of users could be found
    by trying names."""
    wrong = _login(world, world.admin["username"], "wrong")
    missing = _login(world, "nobody", "wrong")
    assert missing.status_code == wrong.status_code == 401
    assert missing.text == wrong.text, "the refusals differ, which reveals who exists"


def test_the_pages_render_once_signed_in(signed_in: httpx.Client):
    for path in ("/admin/", "/admin/arks", "/admin/stats", "/admin/audit", "/admin/clients"):
        r = signed_in.get(path)
        assert r.status_code == 200, f"{path}: {r.status_code}"
        assert "<html" in r.text.lower()


def test_a_form_can_withdraw_and_republish(world: World, signed_in: httpx.Client, mint):
    """Check that the form really changes the ledger, by looking at resolution."""
    ark = mint(url="https://example.org/e2e/admin")["ark"]
    assert world.resolve(ark).status_code == 302

    down = signed_in.post(f"/admin/arks/{ark}/unpublish",
                          data={"reason": "withdrawn from the admin interface", "confirm": ark})
    assert down.status_code in (200, 302, 303), down.text
    assert world.resolve(ark).status_code == 404, "withdrawn in the form, still resolving"

    up = signed_in.post(f"/admin/arks/{ark}/publish", data={"ark": ark})
    assert up.status_code in (200, 302, 303), up.text
    assert world.resolve(ark).status_code == 302


def test_one_ark_page_shows_what_was_minted(signed_in: httpx.Client, published):
    r = signed_in.get(f"/admin/arks/{published['ark']}")
    assert r.status_code == 200
    assert published["url"] in r.text


def test_signing_out_ends_the_session(world: World, signed_in: httpx.Client):
    out = signed_in.post("/admin/logout")
    assert out.status_code in (200, 302, 303)
    again = signed_in.get("/admin/")
    assert again.status_code in (302, 303, 401)
