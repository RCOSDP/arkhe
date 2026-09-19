"""Holding redirection.

A hold stops redirection, not resolution. That is the one thing to check here; the rest
follows from it. Does the description keep being returned, does the hold expire on its
own, does the narrower reason win, and can a principal that must not hold something be
stopped from doing so.

The first half is the decision logic, without a database. The second half uses HTTP and
the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from arkhe.auth.errors import Forbidden
from arkhe.db.models import Ark, ArkChange, Authority, Naan, Shoulder
from arkhe.domain import admin_ops as ops
from arkhe.domain.authz import Invalid
from arkhe.domain.minting import mint
from arkhe.domain.resolution import ArkRepository, Inflection, Outcome, resolve

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=3)
EARLIER = NOW - timedelta(days=1)


# ======================================================== The decision logic


@dataclass
class FakeNaan:
    is_authoritative: bool = True
    redirect: str = ""
    hold_until: datetime | None = None
    hold_reason: str = ""


@dataclass
class FakeShoulder:
    redirect: str = ""
    hold_until: datetime | None = None
    hold_reason: str = ""
    naan_obj: FakeNaan | None = None


@dataclass
class FakeArk:
    url: str = "https://example.ac.jp/thing"
    commitment: str = ""
    hold_until: datetime | None = None
    hold_reason: str = ""
    shoulder: FakeShoulder | None = None


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


def _repo(ark: FakeArk) -> FakeRepo:
    return FakeRepo(arks={"99999/x9abc": ark}, naans={"99999": FakeNaan()})


def test_a_held_ark_is_described_not_redirected():
    """Neither 404 nor 503: the identifier exists, we just do not give out the
    target."""
    res = resolve(
        _repo(FakeArk(hold_until=LATER, hold_reason="being migrated")), "99999", "x9abc", now=NOW
    )
    assert res.outcome is Outcome.DESCRIBE
    assert res.status == 200
    assert res.hold.reason == "being migrated"
    assert res.hold.scope == "ark"


def test_an_expired_hold_does_nothing():
    """Nothing has to be remembered afterwards: the clock is read on each
    resolution, rather than a job putting things back."""
    res = resolve(_repo(FakeArk(hold_until=EARLIER)), "99999", "x9abc", now=NOW)
    assert res.outcome is Outcome.REDIRECT


def test_a_held_ark_still_answers_metadata_requests():
    """?info and ?? are not stopped; that would withdraw the promise of
    persistence."""
    res = resolve(
        _repo(FakeArk(hold_until=LATER)), "99999", "x9abc", Inflection.POLICY, now=NOW
    )
    assert res.outcome is Outcome.DESCRIBE
    assert res.hold is not None


def test_a_hold_on_a_shoulder_applies_to_its_arks():
    ark = FakeArk(shoulder=FakeShoulder(hold_until=LATER, hold_reason="the delegate is down"))
    res = resolve(_repo(ark), "99999", "x9abc", now=NOW)
    assert res.outcome is Outcome.DESCRIBE
    assert res.hold.scope == "shoulder"


def test_a_hold_on_a_naan_applies_to_everything_under_it():
    ark = FakeArk(shoulder=FakeShoulder(naan_obj=FakeNaan(hold_until=LATER)))
    res = resolve(_repo(ark), "99999", "x9abc", now=NOW)
    assert res.hold.scope == "naan"


def test_the_narrower_reason_is_returned():
    """The reason for holding one ARK is more specific than the reason for holding a
    whole namespace."""
    ark = FakeArk(
        hold_until=LATER,
        hold_reason="this one ARK",
        shoulder=FakeShoulder(hold_until=LATER, hold_reason="the whole namespace"),
    )
    res = resolve(_repo(ark), "99999", "x9abc", now=NOW)
    assert res.hold.scope == "ark"
    assert res.hold.reason == "this one ARK"


#: A name whose check digit is correct, the same one test_resolution.py uses. The
#: delegation path runs after the check digit is verified, so this one has to be valid.
GOOD = "kb1d191j10ds"


def test_a_delegated_namespace_can_be_held_too():
    """It works with no row in the ledger. This is the only way to stop a delegate
    from above."""
    repo = FakeRepo(
        naans={"99999": FakeNaan()},
        shoulders={
            ("99999", "/kb1"): FakeShoulder(
                redirect="https://sub.example.ac.jp/ark:/$id",
                hold_until=LATER,
                hold_reason="the delegate is down",
            )
        },
    )
    res = resolve(repo, "99999", GOOD, now=NOW)
    assert res.outcome is Outcome.HELD
    assert res.status == 200
    assert res.hold.reason == "the delegate is down"


def test_a_delegation_that_is_not_held_goes_through():
    repo = FakeRepo(
        naans={"99999": FakeNaan()},
        shoulders={("99999", "/kb1"): FakeShoulder(redirect="https://sub.example.ac.jp/$id")},
    )
    assert resolve(repo, "99999", GOOD, now=NOW).outcome is Outcome.REDIRECT


def test_forwarding_to_another_naan_can_be_held():
    repo = FakeRepo(
        naans={
            "12345": FakeNaan(
                is_authoritative=False, redirect="https://other.example", hold_until=LATER
            )
        }
    )
    assert resolve(repo, "12345", "abc", now=NOW).outcome is Outcome.HELD


def test_a_naive_datetime_still_counts_as_a_hold():
    """SQLite drops the time zone. Raising here would keep redirecting something that
    was meant to be held."""
    naive = LATER.replace(tzinfo=None)
    res = resolve(_repo(FakeArk(hold_until=naive)), "99999", "x9abc", now=NOW)
    assert res.outcome is Outcome.DESCRIBE


# ============================================================ The ledger and HTTP


@pytest.fixture
def minted(db, world):
    ark, _ = mint(db, shoulder=world["sh_a"], created_by="test")
    db.commit()
    return ark


@pytest.fixture
def api(as_principal, root):
    return as_principal(root)


def _in(days: int) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


def test_a_hold_without_a_reason_is_refused(db, root, world):
    """The reason is published, and lifting the hold needs it."""
    with pytest.raises(Invalid):
        ops.set_hold(db, root, kind="naan", key="99999", until=_in(1), reason="  ")


def test_a_hold_that_ends_in_the_past_is_refused(db, root, world):
    with pytest.raises(Invalid):
        ops.set_hold(db, root, kind="naan", key="99999", until=_in(-1), reason="a slip")


def test_a_hold_longer_than_the_limit_is_refused(db, root, world):
    """A long hold is no different from a permanent one. Extending means setting it
    again, which the audit log records."""
    with pytest.raises(Invalid):
        ops.set_hold(
            db, root, kind="naan", key="99999", until=_in(120),
            reason="too long", max_days=90,
        )


def test_an_organisation_admin_cannot_hold_a_namespace(db, world, principal_of):
    """One organisation's decision must not take another organisation's identifiers
    with it."""
    org = principal_of(manager=world["a"])
    with pytest.raises(Forbidden):
        ops.set_hold(
            db, org, kind="shoulder", key=world["sh_a"].id, until=_in(1), reason="stop it"
        )


def test_another_organisations_ark_cannot_be_held(db, world, minted, principal_of):
    """Holding is a way of touching a row, so it stops at the same reach."""
    other = principal_of(manager=world["b"])
    with pytest.raises(Forbidden):
        ops.set_hold(db, other, kind="ark", key=minted.ark, until=_in(1), reason="stop it")


def test_a_hold_is_recorded_in_the_arks_history(db, root, minted):
    """The audit log only records NAAN level and above, and an organisation may be
    the one holding."""
    ops.set_hold(db, root, kind="ark", key=minted.ark, until=_in(1), reason="bad target")
    db.commit()
    actions = list(db.scalars(select(ArkChange.action).where(ArkChange.ark == minted.ark)))
    assert "hold" in actions


def test_a_resolver_does_not_redirect_a_held_ark(api, db, root, minted):
    minted.url = "https://example.ac.jp/thing"
    ops.set_hold(db, root, kind="ark", key=minted.ark, until=_in(1), reason="being migrated")
    db.commit()
    r = api.get(f"/ark:/{minted.ark}")
    assert r.status_code == 200
    assert "being migrated" in r.text
    assert api.get(f"/ark:/{minted.ark}?json").json()["hold"]["reason"] == "being migrated"


def test_releasing_a_hold_restores_redirection(api, db, root, minted):
    minted.url = "https://example.ac.jp/thing"
    ops.set_hold(db, root, kind="ark", key=minted.ark, until=_in(1), reason="being migrated")
    db.commit()
    ops.release_hold(db, root, kind="ark", key=minted.ark)
    db.commit()
    assert api.get(f"/ark:/{minted.ark}").status_code == 302


def test_a_hold_can_be_set_through_the_api(as_principal, principal_of, db, world, minted):
    p = principal_of(
        authority=Authority.NAAN, manager=world["a"],
        scopes={"ark:mint", "ark:update", "ark:read", "ark:hold"},
    )
    client = as_principal(p)
    r = client.put(
        "/api/hold",
        json={"ark": f"ark:/{minted.ark}", "until": _in(2).isoformat(), "reason": "being migrated"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["hold_reason"] == "being migrated"


def test_without_the_hold_scope_nothing_can_be_held(as_principal, principal_of, world, minted):
    """Permission to change a target must not also mean permission to stop one."""
    p = principal_of(manager=world["a"], scopes={"ark:update"})
    r = as_principal(p).put(
        "/api/hold",
        json={"ark": f"ark:/{minted.ark}", "until": _in(2).isoformat(), "reason": "being migrated"},
    )
    assert r.status_code == 403


def test_the_list_of_holds_is_bounded_by_reach(db, root, world, principal_of):
    ops.set_hold(db, root, kind="naan", key="88888", until=_in(1), reason="another NAAN")
    db.commit()
    org = principal_of(manager=world["a"])
    assert [h["target"] for h in ops.held(db, root)] == ["88888"]
    assert ops.held(db, org) == []


def test_delegating_a_shoulder_uses_the_same_operation_as_the_cli(db, root, world):
    """No operation exists only on a screen; delegation is something people will want
    to automate."""
    sh = ops.set_shoulder_redirect(
        db, root, shoulder_id=world["sh_a"].id,
        redirect="303 https://sub.example.ac.jp/ark:/$id",
    )
    db.commit()
    assert sh.redirect.startswith("303 ")


def test_a_held_namespace_appears_in_well_known(api, db, root, world):
    """In a federated setup, the lower level has to be able to check mechanically that
    the level above holds something."""
    ops.set_hold(
        db, root, kind="shoulder", key=world["sh_a"].id, until=_in(1),
        reason="the delegate is down",
    )
    db.commit()
    # The inventory is only returned when JSON is asked for; the default is the
    # text/plain the specification defines in 5.6.
    held = api.get("/.well-known/ark", headers={"Accept": "application/json"}).json()["held"]
    assert held and held[0]["reason"] == "the delegate is down"


def test_all_three_models_can_be_held():
    """The same shape at every level. If only some had it, how to stop something would
    depend on what it is."""
    for model in (Naan, Shoulder, Ark):
        assert {"hold_until", "hold_reason", "hold_by"} <= set(model.__table__.columns.keys())
