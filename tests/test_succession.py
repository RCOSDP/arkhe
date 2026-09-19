"""Succession and departure: identifiers survive a change of custodian.

With NR declared, a name that has been handed out cannot be reassigned, because
reassigning it kills the original identifier. Resolution therefore continues; what
changes is only who mints new names and where they redirect.
"""

from __future__ import annotations

import pytest

from arkhe.db.repository import SqlArkRepository
from arkhe.domain import admin_ops as ops
from arkhe.domain import minting
from arkhe.domain.authz import Invalid
from arkhe.domain.resolution import Outcome, resolve


def _resolve(db, key):
    naan, name = key.split("/", 1)
    return resolve(SqlArkRepository(db), naan, name)


def test_succession_does_not_change_where_arks_resolve(db, world, root):
    arks = [
        minting.mint(db, shoulder=world["sh_a"], created_by="a", url=f"https://a/{i}")[0]
        for i in range(3)
    ]
    db.commit()
    keys = [a.ark for a in arks]

    ops.succeed(db, root, predecessor_id=world["a"].id, successor_id=world["b"].id)
    db.commit()

    for i, k in enumerate(keys):
        r = _resolve(db, k)
        assert r.outcome is Outcome.REDIRECT
        assert r.location == f"https://a/{i}"  # untouched


def test_succession_moves_the_namespace_to_the_successor(db, world, root):
    ops.succeed(db, root, predecessor_id=world["a"].id, successor_id=world["b"].id)
    db.commit()
    assert world["sh_a"].manager_id == world["b"].id
    assert world["a"].succeeded_by_id == world["b"].id
    assert world["a"].active is False


def test_after_succession_the_old_namespace_stops_minting(db, world, root):
    ops.succeed(db, root, predecessor_id=world["a"].id, successor_id=world["b"].id, retire=True)
    db.commit()
    assert world["sh_a"].status == "retired"


def test_succession_cannot_cross_naans(db, world, root):
    """Crossing NAANs would change the shape of the identifier, making it another
    name."""
    with pytest.raises(Invalid):
        ops.succeed(db, root, predecessor_id=world["a"].id, successor_id=world["c"].id)


def test_departure_repoints_every_target_at_the_organisations_resolver(db, world, root):
    arks = [
        minting.mint(db, shoulder=world["sh_a"], created_by="a", url="https://old/x")[0]
        for _ in range(2)
    ]
    db.commit()
    r = ops.depart(
        db, root, manager_id=world["a"].id,
        resolver_template="https://repo.example.ac.jp/ark/${blade}",
    )
    db.commit()
    assert r["rewritten"] == 2
    for a in arks:
        res = _resolve(db, a.ark)
        assert res.location.startswith("https://repo.example.ac.jp/ark/")


def test_departure_sends_unregistered_names_to_that_resolver_too(db, world, root):
    """Anything that needs ongoing work gets forgotten, and dead links remain. The
    same delegation is placed on the shoulder so that later work stays with the
    organisation."""
    from arkhe.arkspec.betanumeric import check_digit_base, noid_check_digit

    ops.depart(
        db, root, manager_id=world["a"].id,
        resolver_template="https://repo.example.ac.jp/ark/${blade}",
    )
    db.commit()
    stem = "a1zzzzzzzz"
    name = stem + noid_check_digit(check_digit_base("99999", stem))
    res = _resolve(db, f"99999/{name}")
    assert res.outcome is Outcome.REDIRECT
    assert res.reason == "delegated by shoulder"


def test_departure_stops_minting_and_keeps_resolution(db, world, root):
    ark, _ = minting.mint(db, shoulder=world["sh_a"], created_by="a", url="https://old/x")
    db.commit()
    ops.depart(db, root, manager_id=world["a"].id)
    db.commit()
    assert world["sh_a"].status == "retired"
    assert _resolve(db, ark.ark).outcome is Outcome.REDIRECT  # resolution continues


def test_departure_can_leave_update_rights_behind(db, world, root):
    """Separate scopes pay off here: the organisation can no longer mint, but it can
    still repoint its own targets."""
    r = ops.depart(db, root, manager_id=world["a"].id, keep_update_label="self-managed")
    db.commit()
    assert r["update_secret"]
    from arkhe.auth import apikey

    p = apikey.authenticate(db, r["update_secret"])
    assert p.scopes == frozenset({"ark:update"})


def test_departure_disables_old_keys_but_keeps_the_rows(db, world, root):
    from sqlalchemy import select

    from arkhe.db.models import Client

    ops.register_client(db, root, client_id="a-web", naan="99999", manager_id=world["a"].id)
    db.commit()
    ops.depart(db, root, manager_id=world["a"].id)
    db.commit()
    still = db.scalar(select(Client).where(Client.client_id == "a-web"))
    assert still is not None and still.active is False  # keep whose key it was
