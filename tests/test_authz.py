"""Authorisation. These pin down the flaws found in arklet so they cannot come back.

M3  update ignored the shoulder, so any ARK under the same NAAN could be rewritten
M4  reads were not authorised at all
M5  an unordered queryset was zipped with the input, writing one row's values onto
    another ARK
R1  {naan, shoulder} came from the request body, so another organisation's namespace
    could be minted into
"""

from __future__ import annotations

import pytest

from arkhe.auth.errors import Forbidden, InsufficientScope
from arkhe.db.models import Authority
from arkhe.domain import authz, minting
from arkhe.domain.authz import Invalid, NotFound

# --------------------------------------------------------- Choosing the shoulder


def test_an_omitted_shoulder_uses_the_organisations_default(db, world, principal_of):
    p = principal_of(manager=world["a"])
    assert authz.shoulder_for(db, p, None).shoulder == "/a1"


def test_a_shoulder_of_your_own_organisation_can_be_named(db, world, root, principal_of):
    from arkhe.domain import admin_ops as ops

    extra = ops.add_shoulder(db, root, naan="99999", shoulder="/a2", manager_id=world["a"].id)
    db.commit()
    p = principal_of(manager=world["a"])
    assert authz.shoulder_for(db, p, "/a2").id == extra.id


def test_r1_naming_another_organisations_namespace_does_not_reach_it(db, world, principal_of):
    """This was the hole in arklet: a misconfiguration or a forged field let anyone
    mint into another organisation."""
    p = principal_of(manager=world["a"])
    with pytest.raises(Forbidden):
        authz.shoulder_for(db, p, "/b2")


def test_r1_a_missing_shoulder_and_another_organisations_look_the_same(db, world, principal_of):
    """Do not leak whether something exists.

    A shoulder that belongs to another organisation and one that does not exist must be
    refused in the same way; if they differ, another organisation's layout can be mapped
    by trying names. The only difference in the message is the value the caller sent, so
    that part is masked before comparing.
    """
    p = principal_of(manager=world["a"])
    with pytest.raises(Forbidden) as a:
        authz.shoulder_for(db, p, "/b2")  # exists, and belongs to org B
    with pytest.raises(Forbidden) as b:
        authz.shoulder_for(db, p, "/zz")  # does not exist
    assert str(a.value).replace("/b2", "…") == str(b.value).replace("/zz", "…")


def test_a_pinned_principal_can_only_use_that_shoulder(db, world, principal_of):
    p = principal_of(manager=world["a"], shoulder=world["sh_a"])
    assert authz.shoulder_for(db, p, None).shoulder == "/a1"
    with pytest.raises(Forbidden):
        authz.shoulder_for(db, p, "/b2")


def test_a_naan_wide_principal_must_name_the_shoulder(db, world, principal_of):
    """No default, so nobody mints into another organisation's shoulder by accident."""
    p = principal_of(authority=Authority.NAAN)
    with pytest.raises(Invalid):
        authz.shoulder_for(db, p, None)
    assert authz.shoulder_for(db, p, "/b2").shoulder == "/b2"


def test_a_naan_wide_principal_cannot_reach_another_naan(db, world, principal_of):
    p = principal_of(authority=Authority.NAAN, naan="99999")
    with pytest.raises(Invalid):
        authz.shoulder_for(db, p, "/c3")


def test_the_system_administrator_reaches_every_naan(db, world, principal_of):
    p = principal_of(authority=Authority.SYSTEM, naan="")
    assert authz.shoulder_for(db, p, "/c3").naan == "88888"


def test_an_ambiguous_shoulder_is_never_chosen_for_you(db, world, root, principal_of):
    """The same shoulder string can exist under several NAANs, so do not pick one."""
    from arkhe.domain import admin_ops as ops

    ops.add_shoulder(db, root, naan="88888", shoulder="/a1")
    db.commit()
    p = principal_of(authority=Authority.SYSTEM, naan="")
    with pytest.raises(Invalid) as e:
        authz.shoulder_for(db, p, "/a1")
    assert sorted(e.value.detail["naans"]) == ["88888", "99999"]


# -------------------------------------------------------- Reaching existing ARKs


def test_m3_another_organisations_ark_cannot_be_updated(db, world, principal_of):
    """arklet's update ignored the shoulder, so any ARK under the same NAAN could be
    rewritten. That is worse than minting: it is taking over a persistent
    identifier."""
    ark, _ = minting.mint(db, shoulder=world["sh_b"], created_by="b")
    db.commit()
    p = principal_of(manager=world["a"])
    with pytest.raises(Forbidden):
        authz.assert_may_touch(db, p, ark)


def test_m3_your_own_organisations_ark_can_be_updated(db, world, principal_of):
    ark, _ = minting.mint(db, shoulder=world["sh_a"], created_by="a")
    db.commit()
    authz.assert_may_touch(db, principal_of(manager=world["a"]), ark)


def test_m3_a_naan_wide_principal_reaches_everything_under_it(db, world, principal_of):
    ark, _ = minting.mint(db, shoulder=world["sh_b"], created_by="b")
    db.commit()
    authz.assert_may_touch(db, principal_of(authority=Authority.NAAN), ark)


def test_m3_a_naan_wide_principal_cannot_touch_another_naans_ark(db, world, principal_of):
    ark, _ = minting.mint(db, shoulder=world["sh_c"], created_by="c")
    db.commit()
    with pytest.raises(Forbidden):
        authz.assert_may_touch(db, principal_of(authority=Authority.NAAN, naan="99999"), ark)


# ------------------------------------------------------- Reading and bulk access


def test_m4_reads_are_bounded_by_reach_too(db, world, principal_of):
    """arklet did no authorisation on reads at all."""
    mine, _ = minting.mint(db, shoulder=world["sh_a"], created_by="a")
    theirs, _ = minting.mint(db, shoulder=world["sh_b"], created_by="b")
    db.commit()
    got = authz.visible_arks(db, principal_of(manager=world["a"]), [mine.ark, theirs.ark])
    assert [a.ark for a in got] == [mine.ark]


def test_m5_rows_are_matched_by_key_not_by_position(db, world, principal_of):
    """arklet zipped an unordered queryset with the input, which could write one
    row's values onto a different ARK."""
    arks = [minting.mint(db, shoulder=world["sh_a"], created_by="a")[0] for _ in range(5)]
    db.commit()
    keys = [a.ark for a in arks]
    found = authz.fetch_for_update(db, principal_of(manager=world["a"]), keys)
    assert all(found[k].ark == k for k in keys)


def test_m5_one_missing_row_fails_the_whole_request(db, world, principal_of):
    """Nothing is applied in part. arklet silently truncated when the counts did not
    match."""
    ark, _ = minting.mint(db, shoulder=world["sh_a"], created_by="a")
    db.commit()
    with pytest.raises(NotFound):
        authz.fetch_for_update(db, principal_of(manager=world["a"]), [ark.ark, "99999/nope"])


def test_m5_one_out_of_reach_row_fails_the_whole_request(db, world, principal_of):
    mine, _ = minting.mint(db, shoulder=world["sh_a"], created_by="a")
    theirs, _ = minting.mint(db, shoulder=world["sh_b"], created_by="b")
    db.commit()
    with pytest.raises(NotFound):
        authz.fetch_for_update(db, principal_of(manager=world["a"]), [mine.ark, theirs.ark])


# ------------------------------------------------------------ Scopes and quotas


def test_a_missing_scope_is_refused(principal_of):
    p = principal_of(scopes={"ark:read"})
    with pytest.raises(InsufficientScope) as e:
        authz.require_scope(p, "ark:mint")
    assert e.value.required == "ark:mint"


def test_r3_the_daily_quota_is_per_organisation(db, world, principal_of, root):
    world["a"].quota_per_day = 2
    db.commit()
    p = principal_of(manager=world["a"])
    minting.mint(db, shoulder=world["sh_a"], created_by="a")
    minting.mint(db, shoulder=world["sh_a"], created_by="a")
    db.commit()
    with pytest.raises(authz.Throttled):
        authz.assert_within_quota(db, p)


def test_r3_break_glass_is_exempt_from_the_quota(db, world, principal_of):
    """It must not stop while an incident is being handled."""
    world["a"].quota_per_day = 0
    db.commit()
    authz.assert_within_quota(db, principal_of(authority=Authority.NAAN))


# ------------------------------------------------------- The state of a shoulder


def test_a_reserved_shoulder_does_not_mint(db, world, root):
    from arkhe.domain import admin_ops as ops

    sh = ops.add_shoulder(db, root, naan="99999", shoulder="/rs")
    db.commit()
    sh.status = "reserved"
    with pytest.raises(Forbidden):
        authz.assert_shoulder_mintable(sh)


def test_a_delegated_shoulder_refuses_and_says_where_to_go(db, world, root):
    from arkhe.domain import admin_ops as ops

    sh = ops.add_shoulder(db, root, naan="99999", shoulder="/dg")
    db.commit()
    ops.set_shoulder_status(
        db, root, shoulder_id=sh.id, status="delegated", minter="https://mint.example.org"
    )
    db.commit()
    with pytest.raises(authz.ShoulderDelegated) as e:
        authz.assert_shoulder_mintable(sh)
    assert e.value.minter == "https://mint.example.org"


# ---------------------------------------------------------------------- Auditing


def test_r2_actions_at_naan_level_and_above_are_recorded(db, world, principal_of):
    from sqlalchemy import select

    from arkhe.db.models import AuditEvent

    before = len(db.scalars(select(AuditEvent)).all())  # what building the ledger left
    authz.audit(db, principal_of(authority=Authority.NAAN), "mint", "99999/x")
    authz.audit(db, principal_of(manager=world["a"]), "mint", "99999/y")
    db.commit()
    added = db.scalars(select(AuditEvent)).all()[before:]
    # Actions by an organisation-level principal are not recorded. The narrower the
    # reach, the less there is to gain from recording everything.
    assert [r.target for r in added] == ["99999/x"]


def test_the_scope_vocabulary_matches_the_implementation():
    """If the vocabulary lives in several places, a scope can be registrable without
    being checked anywhere.

    The choices on the screens come from this constant. Compare it with what is actually
    passed to require_scope, so that neither side grows alone.
    """
    import pathlib
    import re

    from arkhe.domain.authz import SCOPES

    api = pathlib.Path("src/arkhe/api")
    used = set()
    for f in api.rglob("*.py"):
        used |= set(re.findall(r'require_scope\(\s*principal,\s*"(ark:[a-z]+)"', f.read_text()))
    assert used == set(SCOPES), f"vocabulary and implementation differ: {used ^ set(SCOPES)}"
