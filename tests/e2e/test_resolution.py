"""Resolution, driven over plain HTTP against the resolver.

The rules themselves are covered by the unit tests. What this adds is whether they still
hold through the real path: an ASGI server, real headers and real URL handling. Percent
encoding and letter case are the first things an intermediate layer gets wrong.
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import GLOBAL_RESOLVER, UNKNOWN_NAAN, World

pytestmark = pytest.mark.e2e


def test_a_qualifier_is_inherited_from_its_ancestor(world: World, published):
    """A1: an unregistered qualifier is appended to the ancestor's target."""
    r = world.resolve(published["ark"], "/page1")
    assert r.status_code == 302
    assert r.headers["location"].startswith(published["url"])
    assert r.headers["location"].endswith("/page1")


def test_the_ark_label_is_case_insensitive(world: World, published):
    """2.5.1: the ark: label ignores case. The name itself does not."""
    upper = published["ark"].replace("ark:", "ARK:", 1)
    assert world.resolve(upper).status_code == 302


def test_hyphens_inside_a_name_are_ignored(world: World, published):
    """2.5.2: hyphens help people copy a name; they are not part of it."""
    name = published["ark"].split("/", 1)[1]
    hyphenated = f"ark:{world.naan}/{name[:3]}-{name[3:]}"
    r = world.resolve(hyphenated)
    assert r.status_code == 302
    assert r.headers["location"] == published["url"]


def test_info_needs_no_credentials(world: World, published):
    r = world.resolve(published["ark"], "?info")
    assert r.status_code == 200
    assert published["ark"].split(":")[1] in r.text
    assert published["url"] in r.text


def test_double_question_mark_also_describes(world: World, published):
    """C4: ?? asks about the identifier instead of following it."""
    r = world.resolve(published["ark"], "??")
    assert r.status_code == 200


def test_the_public_page_runs_no_script(world: World, published):
    """?info is public and needs no credentials, and whoever minted the ARK chooses the
    text on it. The CSP therefore blocks scripts: without it, anyone who can mint could
    put a script on a public page."""
    r = world.resolve(published["ark"], "?info")
    csp = r.headers.get("content-security-policy", "")
    assert "script-src 'none'" in csp, csp
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_an_unknown_name_is_404(world: World):
    """D3: for a NAAN we are authoritative for, an unknown name really is absent."""
    assert world.resolve(f"ark:{world.naan}/e1zzzzzzzzz").status_code == 404


def test_a_delegated_naan_goes_to_its_delegate(world: World):
    """D2: a NAAN whose resolution is delegated is forwarded. No row is held here."""
    r = world.resolve(f"ark:{world.delegated_naan}/anything")
    assert r.status_code == 302
    assert r.headers["location"].startswith(world.delegate)


def test_an_unknown_naan_goes_to_the_global_resolver(world: World):
    """D2: an unknown NAAN is outside what this ledger knows, so hand it to n2t rather
    than answer 404."""
    r = world.resolve(f"ark:{UNKNOWN_NAAN}/whatever")
    assert r.status_code == 302
    assert r.headers["location"].startswith(GLOBAL_RESOLVER)


def test_a_malformed_ark_is_refused(world: World):
    """Something that is not shaped like a NAAN cannot even be read."""
    assert world.resolve("ark:/").status_code in (400, 404)
