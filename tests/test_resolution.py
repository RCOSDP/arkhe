"""The resolution flow (P3).

The first half tests the decision logic on its own, against a fake repository. The
second half works at the HTTP level. Together they cover what arklet's views_tests.py
covered in 41 tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from arkhe.domain.resolution import (
    ArkRepository,
    Inflection,
    Outcome,
    base_name,
    expand_redirect,
    resolve,
)

# ==========================================================================
# The decision logic, against a fake repository
# ==========================================================================


@dataclass
class FakeArk:
    url: str = ""
    commitment: str = ""


@dataclass
class FakeNaan:
    is_authoritative: bool = True
    redirect: str = ""
    na_policy: str = ""


@dataclass
class FakeShoulder:
    redirect: str = ""


@dataclass
class FakeRepo(ArkRepository):
    arks: dict = field(default_factory=dict)
    naans: dict = field(default_factory=dict)
    shoulders: dict = field(default_factory=dict)

    def get_ark(self, key):
        return self.arks.get(key)

    def get_arks(self, keys):
        return {k: self.arks[k] for k in keys if k in self.arks}

    def get_naan(self, naan):
        return self.naans.get(naan)

    def get_shoulder(self, naan, shoulder):
        return self.shoulders.get((naan, shoulder))


#: A name whose check digit is correct. It is an ARK arklet actually minted
#: (ark:/99999/kb1d191j10ds), so it doubles as a check that the port agrees.
GOOD = "kb1d191j10ds"


def _repo(**kw):
    base = FakeRepo(naans={"99999": FakeNaan(is_authoritative=True)})
    for k, v in kw.items():
        getattr(base, k).update(v)
    return base


def test_check_digit_fixture_is_actually_valid():
    """Pin down the assumption the tests below depend on."""
    from arkhe.arkspec.betanumeric import verify_ark_check_digit

    assert verify_ark_check_digit("99999", GOOD)


# --- Exact match -----------------------------------------------------------


def test_exact_match_redirects():
    r = resolve(_repo(arks={f"99999/{GOOD}": FakeArk(url="https://x.example/1")}), "99999", GOOD)
    assert (r.outcome, r.status, r.location) == (Outcome.REDIRECT, 302, "https://x.example/1")


def test_d6_ark_without_url_is_described_not_redirected():
    """D6: with no target, do not redirect to a bare suffix.

    For a physical object this is the usual answer: the description is the answer.
    """
    r = resolve(_repo(arks={f"99999/{GOOD}": FakeArk(url="")}), "99999", GOOD)
    assert r.outcome is Outcome.DESCRIBE
    assert r.status == 200


def test_a2_hyphens_are_ignored_on_lookup():
    r = resolve(_repo(arks={f"99999/{GOOD}": FakeArk(url="https://x/")}), "99999", "kb1d-191j-10ds")
    assert r.outcome is Outcome.REDIRECT


# --- D5 / B3  inheriting from an ancestor ----------------------------------


def test_d5_longest_ancestor_wins():
    """arklet matched the shortest ancestor, because order_by(Length) ascends, so an
    item inside a collection resolved to the collection."""
    repo = _repo(
        arks={
            f"99999/{GOOD}": FakeArk(url="https://plate/"),
            f"99999/{GOOD}/a/1": FakeArk(url="https://cold/A1"),
        }
    )
    r = resolve(repo, "99999", f"{GOOD}/a/1/0/0")
    assert r.location == "https://cold/A1/0/0"
    assert r.inherited_from == f"99999/{GOOD}/a/1"


def test_passthrough_appends_the_suffix():
    repo = _repo(arks={f"99999/{GOOD}": FakeArk(url="https://repo/scan.nxs")})
    r = resolve(repo, "99999", f"{GOOD}/entry/instrument/detector")
    assert r.location == "https://repo/scan.nxs/entry/instrument/detector"
    assert r.suffix == "/entry/instrument/detector"


def test_b3_variant_separator_is_scanned():
    repo = _repo(arks={f"99999/{GOOD}": FakeArk(url="https://repo/run.mzMLb")})
    r = resolve(repo, "99999", f"{GOOD}.mzml")
    assert r.location == "https://repo/run.mzMLb.mzml"


def test_c5_inflection_survives_passthrough():
    """C5: return the ancestor's metadata under the name that was asked for
    (FAIR A2)."""
    repo = _repo(arks={f"99999/{GOOD}": FakeArk(url="https://repo/scan.nxs")})
    r = resolve(repo, "99999", f"{GOOD}/entry", Inflection.JSON)
    assert r.outcome is Outcome.DESCRIBE
    assert r.status == 200
    assert r.requested == f"99999/{GOOD}/entry"
    assert r.inherited_from == f"99999/{GOOD}"


def test_d6_passthrough_to_urlless_ancestor_describes():
    repo = _repo(arks={f"99999/{GOOD}": FakeArk(url="")})
    r = resolve(repo, "99999", f"{GOOD}/entry")
    assert r.outcome is Outcome.DESCRIBE  # never redirect to a bare suffix


# --- D1  check digits ------------------------------------------------------


def test_d1_mistranscribed_name_is_reported_as_such():
    r = resolve(_repo(), "99999", GOOD[:-1] + ("b" if GOOD[-1] != "b" else "c"))
    assert r.outcome is Outcome.NOT_FOUND
    assert "mistranscribed" in r.reason


def test_d1_is_not_applied_to_other_peoples_naans():
    """Another NAAN does not necessarily use check digits at all."""
    repo = FakeRepo(naans={"12345": FakeNaan(is_authoritative=False, redirect="https://other/")})
    r = resolve(repo, "12345", "anything-at-all")
    assert r.outcome is Outcome.FORWARD


# --- D3  an unknown name under our own NAAN is 404 -------------------------


def test_d3_authoritative_naan_returns_404_not_a_redirect():
    """A deployed arklet redirected to itself here, which looped forever."""
    r = resolve(_repo(), "99999", GOOD)
    assert r.outcome is Outcome.NOT_FOUND
    assert r.status == 404
    assert r.location == ""


# --- D2  an unknown NAAN goes to n2t ---------------------------------------


def test_d2_unknown_naan_is_forwarded_to_the_global_resolver():
    r = resolve(FakeRepo(), "12345", "abcde")
    assert r.outcome is Outcome.FORWARD
    # 2.2: forward in the new form as well; n2t accepts both.
    assert r.location == "https://n2t.net/ark:12345/abcde"


def test_d2_a_naan_with_a_terminal_letter_is_forwarded_rather_than_refused():
    """Same proposal as test_n3_a_naan_with_a_terminal_letter_reads_as_its_own_naan.

    Until it is registered here, ark:12345c/987 is simply a NAAN we do not hold, and an
    unregistered NAAN is handed on rather than refused. That is the safe default while
    the proposal is being discussed: the ARK keeps working through n2t, and nothing in
    this ledger has to guess what the letter means.
    """
    r = resolve(FakeRepo(), "12345c", "987")
    assert r.outcome is Outcome.FORWARD
    assert r.location == "https://n2t.net/ark:12345c/987"


def test_d2_metadata_for_an_unknown_naan_is_404_not_a_forward():
    r = resolve(FakeRepo(), "12345", "abcde", Inflection.JSON)
    assert r.outcome is Outcome.NOT_FOUND


# --- T8  delegating resolution per shoulder --------------------------------


def test_t8_shoulder_redirect_delegates_unregistered_names():
    repo = _repo(
        shoulders={("99999", "/kb1"): FakeShoulder(redirect="https://vocab.example/ark:$id")}
    )
    r = resolve(repo, "99999", GOOD)
    assert r.outcome is Outcome.REDIRECT
    assert r.location == f"https://vocab.example/ark:99999/{GOOD}"


def test_registered_ark_wins_over_shoulder_redirect():
    """Delegation applies only to names in this shoulder that are not registered
    yet."""
    repo = _repo(
        arks={f"99999/{GOOD}": FakeArk(url="https://mine/")},
        shoulders={("99999", "/kb1"): FakeShoulder(redirect="https://elsewhere/$id")},
    )
    assert resolve(repo, "99999", GOOD).location == "https://mine/"


@pytest.mark.parametrize(
    "template,expected_status,expected",
    [
        ("https://x.example/ark:$id", 302, "https://x.example/ark:99999/kb1abc"),
        ("https://x.example/${blade}", 302, "https://x.example/abc"),
        ("303 https://x.example/ark:$id", 303, "https://x.example/ark:99999/kb1abc"),
        ("301 https://x.example/${blade}", 301, "https://x.example/abc"),
    ],
)
def test_redirect_template_expansion(template, expected_status, expected):
    assert expand_redirect(template, "99999", "kb1abc") == (expected_status, expected)


# --- N4 / base name --------------------------------------------------------


def test_n4_double_slash_is_collapsed_before_lookup():
    repo = _repo(arks={f"99999/{GOOD}": FakeArk(url="https://repo/x")})
    r = resolve(repo, "99999", f"{GOOD}//entry")
    assert r.location == "https://repo/x/entry"


def test_base_name_stops_at_the_first_structural_character():
    assert base_name("kb1abc/entry") == "kb1abc"
    assert base_name("kb1abc.mzml") == "kb1abc"
    assert base_name("kb1abc") == "kb1abc"
    assert base_name("kb1..abc") == "kb1..abc"  # not a structural character here


# ==========================================================================
# At the HTTP level
# ==========================================================================



# ------------------------------------------- What may be stored as a target


@pytest.mark.parametrize(
    "url,ok,why",
    [
        ("https://example.org/1", True, "https"),
        ("", True, "empty is valid: an object with no target is a central use"),
        # An ARK can name a physical object or another identifier. The target is a
        # URI, not necessarily an HTTP URL.
        ("urn:isbn:0451450523", True, "a URN is a valid target"),
        ("doi:10.1234/x", True, "another identifier scheme is fine"),
        ("ark:/99999/x9abc", True, "another ARK is fine"),
        ("mailto:curator@example.ac.jp", True, "a contact address is fine"),
        # Only what is dangerous for a browser to interpret is refused
        ("javascript:alert(1)", False, "it appears on a public page"),
        ("JaVaScRiPt:alert(1)", False, "mixed case too; urlsplit normalises it"),
        ("  javascript:alert(1)", False, "leading whitespace too"),
        ("java\tscript:alert(1)", False, "a tab in the middle too"),
        ("data:text/html,<b>x", False, "data: as well"),
    ],
)
def test_what_may_be_registered_as_a_target(url, ok, why):
    """Registration is not narrowed: what an ARK can name must stay open.

    Only schemes that are dangerous for a browser to interpret are refused, and they can
    be listed because urlsplit absorbs the spelling variations.
    """
    from arkhe.domain.resolution import is_registrable

    assert is_registrable(url) is ok, why


@pytest.mark.parametrize(
    "url,ok,why",
    [
        ("https://example.org/1", True, "a browser can open it"),
        ("http://example.org/1", True, "a browser can open it"),
        ("urn:isbn:0451450523", False, "valid but not openable, so describe it"),
        ("doi:10.1234/x", False, "the same"),
        ("", False, "no target, so describe it"),
        ("javascript:alert(1)", False, "it cannot be registered either, but check"),
    ],
)
def test_what_may_be_redirected_to(url, ok, why):
    """Being registrable and being safe to send a browser to are different things.

    A urn: is a valid target that a browser cannot open, so it is described rather than
    followed. That is not a restriction; it is what ?info has always been for.
    """
    from arkhe.domain.resolution import is_followable

    assert is_followable(url) is ok, why


# ------------------------------- Listing delegations so they can be watched


def test_delegated_resolution_appears_in_well_known(db, world, as_principal, root):
    """What monitoring should watch first cannot be watched if it is not listed.

    If a minter dies, only minting stops; if a redirect dies, every ARK in that shoulder
    stops resolving. The consequences are the other way round from what was listed,
    which used to be only minter and about.
    """
    sh = world["sh_a"]
    sh.redirect = "https://resolver.partner.example.org/ark:/${blade}"
    db.commit()

    body = as_principal(root).get(
        "/.well-known/ark", headers={"Accept": "application/json"}
    ).json()
    listed = {s["shoulder"]: s for s in body["delegated_shoulders"]}
    key = f"{sh.naan}{sh.shoulder}"
    assert key in listed, "a shoulder with delegated resolution is missing from the list"
    assert listed[key]["redirect"] == sh.redirect
    assert listed[key]["status"] == sh.status


def test_a_shoulder_that_mints_here_but_resolves_elsewhere_is_listed_too(
    db, world, as_principal, root
):
    """redirect can be set independently of status.

    Listing only the delegated ones drops any shoulder that still mints here while
    resolving elsewhere, and nobody would notice if that target died.
    """
    sh = world["sh_a"]
    assert sh.status == "active", "this check is only meaningful on an active shoulder"
    sh.redirect = "https://elsewhere.example.org/${blade}"
    db.commit()

    body = as_principal(root).get(
        "/.well-known/ark", headers={"Accept": "application/json"}
    ).json()
    assert f"{sh.naan}{sh.shoulder}" in {s["shoulder"] for s in body["delegated_shoulders"]}
