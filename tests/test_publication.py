"""Publishing to the world, and withdrawing before publication.

NR binds names that have been handed out. That is the one thing being checked here, and
the rest follows from it: whether a reserved ARK resolves, whether a published one can
be deleted, whether a deleted name is ever minted again, and whether a principal out of
reach can delete anything.

The first half covers the ledger and the domain, the second HTTP, the screens and the
CLI.
"""

from __future__ import annotations

import contextlib

import pytest
from sqlalchemy import select

from arkhe.auth.errors import Forbidden
from arkhe.db.models import (
    Ark,
    ArkChange,
    Authority,
    MintReceipt,
    NotDeletable,
    WithdrawnName,
)
from arkhe.domain import admin_ops as ops
from arkhe.domain import minting
from arkhe.domain.authz import Conflict, Invalid, NotFound
from arkhe.domain.minting import mint
from arkhe.domain.queries import narrow_arks, visible_arks


@pytest.fixture
def reserved(db, world):
    """One reserved ARK."""
    ark, _ = mint(db, shoulder=world["sh_a"], created_by="test", reserve=True)
    db.commit()
    return ark


@pytest.fixture
def api(as_principal, root):
    return as_principal(root)


# ============================================================= In the ledger


def test_minting_publishes_by_default(db, world):
    """Keep the old behaviour as the default. An extra publish step would quietly
    leave callers minting ARKs that never resolve."""
    ark, _ = mint(db, shoulder=world["sh_a"], created_by="t")
    assert ark.published_at is not None
    assert ark.is_public


def test_a_reserved_mint_is_unpublished(reserved):
    assert reserved.published_at is None
    assert not reserved.is_public


def test_a_reserved_ark_can_be_deleted(db, root, reserved):
    key = reserved.ark
    ops.withdraw_ark(db, root, ark=key, reason="the request was withdrawn")
    db.commit()
    assert db.get(Ark, key) is None


def test_a_published_ark_cannot_be_deleted(db, root, world):
    """A name that went out is not removed. Only a reserved one can be."""
    ark, _ = mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    with pytest.raises(Conflict):
        ops.withdraw_ark(db, root, ark=ark.ark)


def test_the_orm_refuses_to_delete_a_published_ark(db, world):
    """The rule is not left to people: deleting without going through admin_ops
    fails."""
    ark, _ = mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    with pytest.raises(NotDeletable):
        db.delete(ark)
        db.flush()


def test_a_withdrawn_name_is_never_minted_again(db, root, world, reserved):
    """A reserved string may already be in someone's hands. Pointing it at another
    object is indistinguishable, from outside, from an NR violation."""
    key = reserved.ark
    ops.withdraw_ark(db, root, ark=key, reason="no longer needed")
    db.commit()
    gone = db.get(WithdrawnName, key)
    assert gone is not None
    assert gone.minted_by == "test" and gone.withdrawn_by == root.client_id
    # Import refuses it too. Minting retries on a hit, which only probability shows
    sh = world["sh_a"]
    ops.set_shoulder_status(db, root, shoulder_id=sh.id, status="delegated")
    db.flush()
    with pytest.raises(minting.Withdrawn):
        minting.check_importable(db, sh, gone.assigned_name)


def test_publishing_starts_resolution(db, root, reserved):
    ops.publish_ark(db, root, ark=reserved.ark)
    db.commit()
    assert reserved.published_at is not None


def test_publishing_twice_is_not_an_error(db, root, reserved):
    """Sometimes only the response is lost. Answering 409 to a resend would send the
    caller off to check somewhere else."""
    first = ops.publish_ark(db, root, ark=reserved.ark).published_at
    again = ops.publish_ark(db, root, ark=reserved.ark).published_at
    assert first == again


def test_publication_is_recorded_in_the_arks_history(db, root, reserved):
    """When something went out is always needed later, and the audit log only keeps
    NAAN level and above."""
    ops.publish_ark(db, root, ark=reserved.ark)
    db.commit()
    actions = list(db.scalars(select(ArkChange.action).where(ArkChange.ark == reserved.ark)))
    assert "publish" in actions


def test_withdrawing_also_removes_the_minting_receipt(db, root, world, reserved):
    """The receipt points at the ARK; keeping it would leave a receipt pointing at a
    row that is gone."""
    db.add(MintReceipt(client_id="x", request_id="r1", ark=reserved.ark))
    db.commit()
    ops.withdraw_ark(db, root, ark=reserved.ark)
    db.commit()
    assert db.scalars(select(MintReceipt)).all() == []


def test_an_ark_with_qualifiers_cannot_be_withdrawn(db, root, reserved):
    """Work upwards: removing only the parent leaves part references with nothing to
    inherit from."""
    minting.register_qualified(db, base=reserved, qualifier="/c3", created_by="t")
    db.commit()
    with pytest.raises(Conflict):
        ops.withdraw_ark(db, root, ark=reserved.ark)


def test_a_qualifier_inherits_publication_from_its_base(db, reserved):
    """A part reference never goes out before its base."""
    part = minting.register_qualified(db, base=reserved, qualifier="/c3", created_by="t")
    assert part.published_at is None


def test_another_organisations_ark_cannot_be_withdrawn(db, world, reserved, principal_of):
    """Withdrawing is a way of touching a row, so it stops at the same reach."""
    other = principal_of(manager=world["b"])
    with pytest.raises(Forbidden):
        ops.withdraw_ark(db, other, ark=reserved.ark)


def test_withdrawing_an_ark_that_does_not_exist_is_404(db, root):
    with pytest.raises(NotFound):
        ops.withdraw_ark(db, root, ark="99999/x9nosuchark")


# ============================================================ In resolution


def test_a_reserved_ark_does_not_resolve(api, db, reserved):
    """It is treated as a name that does not exist yet. Answering 200 would reveal
    that an unpublished object exists, and describe it."""
    reserved.url = "https://example.ac.jp/draft"
    db.commit()
    r = api.get(f"/ark:/{reserved.ark}")
    assert r.status_code == 404


def test_a_reserved_ark_is_not_described_either(api, db, reserved):
    reserved.title = "unpublished observation data"
    db.commit()
    r = api.get(f"/ark:/{reserved.ark}?info")
    assert r.status_code == 404
    assert "unpublished observation data" not in r.text


def test_once_published_it_resolves(api, db, root, reserved):
    reserved.url = "https://example.ac.jp/thing"
    ops.publish_ark(db, root, ark=reserved.ark)
    db.commit()
    r = api.get(f"/ark:/{reserved.ark}")
    assert r.status_code == 302
    assert r.headers["location"] == "https://example.ac.jp/thing"


def test_a_reserved_ark_is_not_used_as_an_ancestor(api, db, reserved):
    """Picked up by inheritance, it would send people to an unpublished target."""
    reserved.url = "https://example.ac.jp/draft"
    db.commit()
    r = api.get(f"/ark:/{reserved.ark}/c3")
    assert r.status_code == 404


# ================================== Purging an ARK that has been published


@pytest.fixture
def published(db, world):
    """One published ARK, which is what ordinary minting produces."""
    ark, _ = mint(db, shoulder=world["sh_a"], created_by="test")
    db.commit()
    return ark


def test_an_ra_operator_can_purge_a_published_ark(db, root, published):
    """With no way out, someone under pressure edits the database directly, and a
    deletion that leaves no trace is the worst outcome."""
    key = published.ark
    gone = ops.purge_ark(
        db, root, ark=key, reason="a court removal order", confirm=key
    )
    db.commit()
    assert db.scalars(select(Ark.ark).where(Ark.ark == key)).all() == []
    assert gone.published_at is not None  # tells it apart from a withdrawal
    assert gone.reason == "a court removal order"


def test_a_purged_name_is_never_minted_again(db, root, world, published):
    """Keep the half of the promise that can still be kept. Resolution stops, but the
    name never points at something else: an old reference simply gets 404."""
    key = published.ark
    name = published.assigned_name
    ops.purge_ark(db, root, ark=key, reason="loaded by mistake", confirm=key)
    db.commit()
    assert db.get(WithdrawnName, key) is not None
    sh = world["sh_a"]
    ops.set_shoulder_status(db, root, shoulder_id=sh.id, status="delegated")
    db.flush()
    with pytest.raises(minting.Withdrawn):
        minting.check_importable(db, sh, name)


def test_a_naan_administrator_can_purge_within_that_naan(db, world, published, principal_of):
    """0.4.0 stopped restricting this by tier; what binds is reach and ceremony.

    Once withdrawal existed, unpublish followed by delete reached the same result in two
    steps, so restricting only the one-step version by tier protected nothing.
    """
    naan_admin = principal_of(authority=Authority.NAAN, scopes={"ark:purge"})
    ops.purge_ark(db, naan_admin, ark=published.ark, reason="a removal order",
                  confirm=published.ark)
    assert db.get(Ark, published.ark) is None


def test_an_organisation_admin_can_purge_within_its_shoulder(db, world, published, principal_of):
    org = principal_of(manager=world["a"], scopes={"ark:purge"})
    ops.purge_ark(db, org, ark=published.ark, reason="a removal order", confirm=published.ark)
    assert db.get(Ark, published.ark) is None


def test_another_organisations_ark_cannot_be_purged(db, world, published, principal_of):
    """Reach still binds. Loosening it here would simply be a takeover."""
    other = principal_of(manager=world["b"], scopes={"ark:purge"})
    with pytest.raises(Forbidden):
        ops.purge_ark(db, other, ark=published.ark, reason="we want it gone",
                      confirm=published.ark)
    assert db.get(Ark, published.ark) is not None


def test_purging_without_a_reason_is_refused(db, root, published):
    """A purge that leaves no record is the same as one that never happened."""
    with pytest.raises(Invalid):
        ops.purge_ark(db, root, ark=published.ark, reason="   ", confirm=published.ark)
    assert db.get(Ark, published.ark) is not None


def test_a_mismatched_confirmation_purges_nothing(db, root, world, published):
    """So that a script walking a list cannot empty the ledger by accident."""
    other, _ = mint(db, shoulder=world["sh_a"], created_by="test")
    db.commit()
    with pytest.raises(Invalid):
        ops.purge_ark(db, root, ark=published.ark, reason="delete it", confirm=other.ark)
    with pytest.raises(Invalid):
        ops.purge_ark(db, root, ark=published.ark, reason="delete it", confirm="")
    assert db.get(Ark, published.ark) is not None


def test_a_purge_is_recorded_in_the_audit_log(db, root, published):
    """Everything the system administrator does is recorded. For a row that is gone,
    this and WithdrawnName are all that remain."""
    from arkhe.db.models import AuditEvent

    ops.purge_ark(db, root, ark=published.ark, reason="a removal order", confirm=published.ark)
    db.commit()
    rows = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "purge")))
    assert len(rows) == 1
    assert rows[0].target == published.ark
    assert rows[0].detail["reason"] == "a removal order" and rows[0].detail["published"] is True


def test_a_purged_ark_stops_resolving(api, db, root, published):
    published.url = "https://example.ac.jp/thing"
    db.commit()
    assert api.get(f"/ark:/{published.ark}").status_code == 302
    ops.purge_ark(db, root, ark=published.ark, reason="a removal order", confirm=published.ark)
    db.commit()
    assert api.get(f"/ark:/{published.ark}").status_code == 404


def test_deleting_outside_the_purge_path_is_still_refused(db, root, published):
    """The door stays shut even though a way out exists: outside the session purge_ark
    named, a published row cannot be removed."""
    with pytest.raises(NotDeletable):
        db.delete(published)
        db.flush()
    db.rollback()


def test_the_purge_declaration_applies_to_one_ark_only(db, root, world, published):
    """Not a global flag: in the same session, nothing but the declared ARK can be
    removed."""
    from arkhe.db.models import sanctioned_purge

    other, _ = mint(db, shoulder=world["sh_a"], created_by="test")
    db.commit()
    with sanctioned_purge(db, published.ark), pytest.raises(NotDeletable):
        db.delete(other)
        db.flush()
    db.rollback()


def test_the_purge_declaration_does_not_outlive_the_block(db, root, published):
    """It is cleared even when an exception leaves the block. Not staying raised is
    most of the value here."""
    from arkhe.db.models import sanctioned_purge

    with contextlib.suppress(RuntimeError), sanctioned_purge(db, published.ark):
        raise RuntimeError("failed halfway")
    with pytest.raises(NotDeletable):
        db.delete(published)
        db.flush()
    db.rollback()


def test_purging_a_reserved_ark_records_it_as_a_withdrawal(db, root, reserved):
    """One operation, not two entrances. Purging a reserved ARK is still recorded as a
    withdrawal, with no published_at."""
    gone = ops.purge_ark(db, root, ark=reserved.ark, reason="removed a draft",
                         confirm=reserved.ark)
    db.commit()
    assert gone.published_at is None


def test_purging_works_through_the_api(as_principal, principal_of, db, published):
    """The scope and the reach are both required."""
    ops_client = as_principal(
        principal_of(authority=Authority.SYSTEM, scopes={"ark:purge"})
    )
    r = ops_client.post(
        "/api/purge",
        json={"ark": published.ark, "reason": "a removal order", "confirm": published.ark},
    )
    assert r.status_code == 200, r.text
    assert r.json()["was_published_at"] is not None
    assert db.scalars(select(Ark.ark).where(Ark.ark == published.ark)).all() == []


def test_the_delete_scope_alone_cannot_purge(as_principal, principal_of, published):
    client = as_principal(
        principal_of(authority=Authority.SYSTEM, scopes={"ark:delete"})
    )
    r = client.post(
        "/api/purge",
        json={"ark": published.ark, "reason": "delete it", "confirm": published.ark},
    )
    assert r.status_code == 403


def test_a_naan_administrator_can_purge_through_the_api_too(
    as_principal, principal_of, db, published
):
    client = as_principal(
        principal_of(authority=Authority.NAAN, scopes={"ark:purge"})
    )
    r = client.post(
        "/api/purge",
        json={"ark": published.ark, "reason": "a removal order", "confirm": published.ark},
    )
    assert r.status_code == 200
    # Look it up again. The API commits in another session, so the row still in this
    # identity map would look alive.
    assert db.scalars(select(Ark.ark).where(Ark.ark == published.ark)).all() == []


def test_without_the_scope_nothing_can_be_purged(as_principal, principal_of, db, published):
    """Tiers went away; scopes did not. When one restriction is removed, the rest must
    still hold."""
    client = as_principal(principal_of(authority=Authority.SYSTEM, scopes={"ark:delete"}))
    r = client.post(
        "/api/purge",
        json={"ark": published.ark, "reason": "delete it", "confirm": published.ark},
    )
    assert r.status_code == 403
    assert db.get(Ark, published.ark) is not None


def test_only_a_principal_with_the_scope_can_purge_from_the_screen(
    as_principal, principal_of, db, published
):
    """No button that only refuses when pressed: display and authorisation use one
    decision."""
    no_scope = as_principal(
        principal_of(authority=Authority.NAAN, scopes={"ark:mint"})
    )
    page = no_scope.get(f"/admin/arks/{published.ark}")
    assert "/purge" not in page.text

    naan_ui = as_principal(
        principal_of(authority=Authority.NAAN, scopes={"ark:purge", "ark:mint"})
    )
    page = naan_ui.get(f"/admin/arks/{published.ark}")
    assert "/purge" in page.text
    r = naan_ui.post(
        f"/admin/arks/{published.ark}/purge",
        data={"reason": "a removal order", "confirm": f"ark:{published.ark}"},
    )
    assert r.status_code == 303
    assert db.scalars(select(Ark.ark).where(Ark.ark == published.ark)).all() == []


# ============================================= A resolver on a closed network


@pytest.fixture
def closed(app, settings, as_principal, root):
    """A resolver inside a closed network, which resolves reserved ARKs too.

    One setting changes it, so only the settings are swapped here. The decision lives in
    one place, resolution.serves, shared with the public endpoints.
    """
    settings.resolve_unpublished = True
    return as_principal(root)


def test_a_closed_resolver_resolves_reserved_arks(closed, db, reserved):
    """If ARKs minted inside a closed network do not resolve there, handing them out
    is pointless, and giving closed objects the same kind of identifier fails."""
    reserved.url = "https://closed.example.ac.jp/thing"
    db.commit()
    r = closed.get(f"/ark:/{reserved.ark}")
    assert r.status_code == 302
    assert r.headers["location"] == "https://closed.example.ac.jp/thing"


def test_a_closed_resolver_describes_reserved_arks_too(closed, db, reserved):
    reserved.title = "observation data on a closed network"
    db.commit()
    r = closed.get(f"/ark:/{reserved.ark}?info")
    assert r.status_code == 200
    assert "observation data on a closed network" in r.text


def test_a_closed_resolver_still_allows_deleting_a_reserved_ark(closed, db, root, reserved):
    """Resolving and deleting are different questions. The name stays in
    WithdrawnName, so afterwards it never points at something else, which is what NR
    protects."""
    ops.withdraw_ark(db, root, ark=reserved.ark, reason="plans change on closed networks too")
    db.commit()
    assert db.scalars(select(Ark.ark).where(Ark.ark == reserved.ark)).all() == []


def test_a_public_resolver_does_not_serve_reserved_arks(api, db, reserved, settings):
    """The default is the side that does not leak: a mistake should not expose
    anything."""
    assert settings.resolve_unpublished is False
    reserved.url = "https://closed.example.ac.jp/thing"
    db.commit()
    assert api.get(f"/ark:/{reserved.ark}").status_code == 404


# ================================================================ HTTP


def _key_of(ark: str) -> str:
    """The ledger key for an ARK the API returned (it answers the compact form)."""
    return ark.removeprefix("ark:")


def test_publishing_works_through_the_api(as_principal, principal_of, db, world):
    org = principal_of(manager=world["a"], scopes={"ark:mint"})
    client = as_principal(org)
    made = client.post("/api/mint", json={"reserve": True, "url": "https://x.example/1"})
    assert made.status_code == 201
    assert made.json()["published_at"] is None

    ark = made.json()["ark"]
    out = client.post("/api/publish", json={"ark": ark})
    assert out.status_code == 200
    assert out.json()["published_at"] is not None


def test_withdrawing_works_through_the_api(as_principal, principal_of, db, world):
    org = principal_of(manager=world["a"], scopes={"ark:mint", "ark:delete"})
    client = as_principal(org)
    ark = client.post("/api/mint", json={"reserve": True}).json()["ark"]
    r = client.post("/api/delete", json={"ark": ark, "reason": "the registration was cancelled"})
    assert r.status_code == 200
    assert r.json()["ark"] == ark
    assert client.post("/api/delete", json={"ark": ark}).status_code == 404


def test_deleting_a_published_ark_is_409(as_principal, principal_of, world):
    """The status code tells it apart from a tombstone: the values and the permissions
    are right, but the row is in the wrong state."""
    org = principal_of(manager=world["a"], scopes={"ark:mint", "ark:delete"})
    client = as_principal(org)
    ark = client.post("/api/mint", json={}).json()["ark"]
    r = client.post("/api/delete", json={"ark": ark})
    assert r.status_code == 409
    assert r.json()["code"] == "ARKHE-1501"


def test_without_the_delete_scope_nothing_is_withdrawn(as_principal, principal_of, world):
    """Being able to mint and being able to withdraw are different things."""
    org = principal_of(manager=world["a"], scopes={"ark:mint", "ark:update"})
    client = as_principal(org)
    ark = client.post("/api/mint", json={"reserve": True}).json()["ark"]
    assert client.post("/api/delete", json={"ark": ark}).status_code == 403


def test_a_batch_of_reservations_is_withdrawn_through_the_api(
    as_principal, principal_of, world
):
    org = principal_of(manager=world["a"], scopes={"ark:mint", "ark:delete"})
    client = as_principal(org)
    arks = [client.post("/api/mint", json={"reserve": True}).json()["ark"] for _ in range(3)]

    r = client.post("/api/delete/bulk", json={"data": arks, "reason": "abandoned"})
    assert r.status_code == 200, r.text
    assert r.json() == {"withdrawn": arks, "count": 3}
    assert client.post("/api/query", json={"data": arks}).status_code in (200, 403)


def test_a_batch_holding_a_published_ark_is_409_and_deletes_nothing(
    as_principal, principal_of, db, world
):
    """The cheap path is only for names nobody has seen, and it is all or nothing."""
    org = principal_of(manager=world["a"], scopes={"ark:mint", "ark:delete"})
    client = as_principal(org)
    spare = client.post("/api/mint", json={"reserve": True}).json()["ark"]
    public = client.post("/api/mint", json={}).json()["ark"]

    r = client.post("/api/delete/bulk", json={"data": [spare, public]})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "ARKHE-1501"
    assert db.get(Ark, _key_of(spare)) is not None, "the batch was applied in part"


def test_a_batch_holding_a_name_that_was_public_is_refused(
    as_principal, principal_of, db, world
):
    """Withdrawn from publication is not the same as never published: the name has
    been out, so it is deleted on its own, with a reason and the ARK typed again."""
    org = principal_of(manager=world["a"],
                       scopes={"ark:mint", "ark:delete", "ark:unpublish"})
    client = as_principal(org)
    spare = client.post("/api/mint", json={"reserve": True}).json()["ark"]
    was_public = client.post("/api/mint", json={}).json()["ark"]
    client.post("/api/unpublish",
                json={"ark": was_public, "reason": "a mistake", "confirm": was_public})

    r = client.post("/api/delete/bulk", json={"data": [spare, was_public]})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "ARKHE-1504"
    assert db.get(Ark, _key_of(spare)) is not None


def test_a_batch_cannot_be_deleted_without_the_delete_scope(
    as_principal, principal_of, world
):
    org = principal_of(manager=world["a"], scopes={"ark:mint", "ark:update"})
    client = as_principal(org)
    ark = client.post("/api/mint", json={"reserve": True}).json()["ark"]
    assert client.post("/api/delete/bulk", json={"data": [ark]}).status_code == 403


def test_another_organisations_ark_cannot_be_withdrawn_in_a_batch(
    as_principal, principal_of, db, world, reserved
):
    """Reach binds a batch exactly as it binds one row."""
    other = principal_of(manager=world["b"], scopes={"ark:delete"})
    r = as_principal(other).post("/api/delete/bulk", json={"data": [f"ark:{reserved.ark}"]})
    assert r.status_code in (403, 404)
    assert db.get(Ark, reserved.ark) is not None


def test_another_organisations_ark_cannot_be_withdrawn_through_the_api(
    as_principal, principal_of, db, world, reserved
):
    other = principal_of(manager=world["b"], scopes={"ark:delete"})
    r = as_principal(other).post("/api/delete", json={"ark": reserved.ark})
    assert r.status_code in (403, 404)
    assert db.get(Ark, reserved.ark) is not None


# ====================================================== The screens and the CLI


@pytest.fixture
def admin(as_principal, principal_of):
    """A principal for the screens. Scopes are checked, so they are granted here."""
    return as_principal(
        principal_of(authority=Authority.SYSTEM, scopes={"ark:mint", "ark:delete"})
    )


def test_publishing_works_from_the_screen(admin, db, reserved):
    r = admin.post(f"/admin/arks/{reserved.ark}/publish")
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Ark, reserved.ark).published_at is not None


def test_withdrawing_works_from_the_screen(admin, db, reserved):
    r = admin.post(f"/admin/arks/{reserved.ark}/delete", data={"reason": "removed a draft"})
    assert r.status_code == 303
    # It was removed in another session, so ask the ledger, not the identity map.
    assert db.scalars(select(Ark.ark).where(Ark.ark == reserved.ark)).all() == []


def test_the_detail_page_says_it_is_unpublished(admin, reserved):
    page = admin.get(f"/admin/arks/{reserved.ark}")
    assert "\u516c\u958b\u524d" in page.text  # "unpublished" in the Japanese UI


def test_the_list_can_be_filtered_by_state(db, root, world, reserved):
    """The screens and the CLI share one query; the filter is not written twice."""
    mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    only = db.scalars(narrow_arks(visible_arks(root), state="reserved")).all()
    assert [a.ark for a in only] == [reserved.ark]
    rest = db.scalars(narrow_arks(visible_arks(root), state="public")).all()
    assert reserved.ark not in [a.ark for a in rest]


# ===================== Withdrawing a publication and publishing again (0.4.0)


def test_withdrawing_publication_stops_resolution(db, root, published, api):
    """The reversible half: the row stays and only resolution stops."""
    assert api.get(f"/ark:/{published.ark}").status_code == 200   # described
    ops.unpublish_ark(db, root, ark=published.ark, reason="published by mistake",
                      confirm=published.ark)
    db.commit()
    assert db.get(Ark, published.ark) is not None          # the row stays
    assert db.get(Ark, published.ark).published_at is None
    # Answer as for a name we do not know. Never hint that it exists but is hidden.
    assert api.get(f"/ark:/{published.ark}").status_code == 404


def test_withdrawal_does_not_erase_having_been_published(db, root, published):
    """A one-way column. If it moved, deleting a published name would be as light as
    deleting a reserved one."""
    first = db.get(Ark, published.ark).first_published_at
    assert first is not None
    ops.unpublish_ark(db, root, ark=published.ark, reason="a mistake", confirm=published.ark)
    db.commit()
    assert db.get(Ark, published.ark).first_published_at == first


def test_something_withdrawn_can_be_published_again(db, root, published, api):
    ops.unpublish_ark(db, root, ark=published.ark, reason="a mistake", confirm=published.ark)
    db.commit()
    first = db.get(Ark, published.ark).first_published_at
    ops.publish_ark(db, root, ark=published.ark)
    db.commit()
    row = db.get(Ark, published.ark)
    assert row.published_at is not None
    # The first publication time does not move; republishing does not fill the gap.
    assert row.first_published_at == first
    assert api.get(f"/ark:/{published.ark}").status_code == 200


def test_republishing_is_recorded_as_such(db, root, published):
    """What matters to a reader is that there was a period when it did not resolve."""
    ops.unpublish_ark(db, root, ark=published.ark, reason="a mistake", confirm=published.ark)
    ops.publish_ark(db, root, ark=published.ark)
    db.commit()
    actions = db.scalars(
        select(ArkChange.action).where(ArkChange.ark == published.ark)
    ).all()
    assert "unpublish" in actions
    assert "republish" in actions


def test_something_unpublished_cannot_be_withdrawn(db, root, reserved):
    with pytest.raises(Conflict):
        ops.unpublish_ark(db, root, ark=reserved.ark, reason="a mistake", confirm=reserved.ark)


def test_withdrawal_without_a_reason_is_refused(db, root, published):
    """Someone may already be citing it. The reason is all that will remain."""
    with pytest.raises(Invalid):
        ops.unpublish_ark(db, root, ark=published.ark, reason="  ", confirm=published.ark)
    assert db.get(Ark, published.ark).published_at is not None


def test_a_mismatched_confirmation_withdraws_nothing(db, root, world, published):
    other, _ = mint(db, shoulder=world["sh_a"], created_by="test")
    with pytest.raises(Invalid):
        ops.unpublish_ark(db, root, ark=published.ark, reason="a mistake", confirm=other.ark)
    assert db.get(Ark, published.ark).published_at is not None


def test_a_published_ark_must_be_withdrawn_before_it_is_deleted(db, root, published):
    """Withdrawing and deleting are not one step: the first can be undone."""
    with pytest.raises(Conflict):
        ops.withdraw_ark(db, root, ark=published.ark, reason="delete it", confirm=published.ark)
    ops.unpublish_ark(db, root, ark=published.ark, reason="a mistake", confirm=published.ark)
    ops.withdraw_ark(db, root, ark=published.ark, reason="delete it", confirm=published.ark)
    db.commit()
    assert db.scalars(select(Ark.ark).where(Ark.ark == published.ark)).all() == []
    assert db.get(WithdrawnName, published.ark) is not None


def test_deleting_a_once_published_name_needs_a_reason_and_confirmation(db, root, published):
    """The weight comes from the name's history, not from the caller's tier."""
    ops.unpublish_ark(db, root, ark=published.ark, reason="a mistake", confirm=published.ark)
    with pytest.raises(Invalid):   # no reason
        ops.withdraw_ark(db, root, ark=published.ark, reason="", confirm=published.ark)
    with pytest.raises(Invalid):   # the confirmation does not match
        ops.withdraw_ark(db, root, ark=published.ark, reason="delete it", confirm="ark:99999/x")
    assert db.get(Ark, published.ark) is not None


def test_a_reserved_ark_that_was_never_published_stays_easy_to_delete(db, root, reserved):
    """How much is asked matches what is being lost. Making this heavier would be a
    regression."""
    ops.withdraw_ark(db, root, ark=reserved.ark)
    db.commit()
    assert db.scalars(select(Ark.ark).where(Ark.ark == reserved.ark)).all() == []


def test_a_batch_of_reservations_goes_in_one_request(db, root, world):
    """Reserving in bulk is one request, so abandoning a batch has to be one too.

    One at a time, a thousand reservations are never thrown away in practice: they are
    left in the ledger, which is what the reservation rule exists to avoid.
    """
    arks = [mint(db, shoulder=world["sh_a"], created_by="test", reserve=True)[0]
            for _ in range(5)]
    db.commit()
    keys = [a.ark for a in arks]

    gone = ops.withdraw_bulk(db, root, arks=keys, reason="the deposit was abandoned")
    db.commit()
    assert len(gone) == 5
    assert db.scalars(select(Ark.ark).where(Ark.ark.in_(keys))).all() == []
    # Every name is still burned: a reserved string may already be in someone's hands.
    assert all(db.get(WithdrawnName, k) is not None for k in keys)


def test_one_name_that_was_public_fails_the_whole_batch(db, root, world, published):
    """The cheap path is only for names nobody has seen. Nothing is deleted in part,
    so a batch cannot be half gone before the refusal."""
    spare, _ = mint(db, shoulder=world["sh_a"], created_by="test", reserve=True)
    ops.unpublish_ark(db, root, ark=published.ark, reason="a mistake", confirm=published.ark)
    db.commit()

    with pytest.raises(Conflict):
        ops.withdraw_bulk(db, root, arks=[spare.ark, published.ark])
    db.rollback()
    assert db.get(Ark, spare.ark) is not None, "the batch was applied in part"
    assert db.get(Ark, published.ark) is not None


def test_a_published_ark_cannot_be_deleted_in_a_batch_either(db, root, world, published):
    """The same refusal as the single path, so the batch is not a way round it."""
    spare, _ = mint(db, shoulder=world["sh_a"], created_by="test", reserve=True)
    db.commit()
    with pytest.raises(Conflict):
        ops.withdraw_bulk(db, root, arks=[spare.ark, published.ark])


def test_a_name_withdrawn_then_deleted_is_recorded_as_having_been_public(db, root, published):
    """It has to be distinguishable from withdrawing a reservation. Mixed together in
    the records, nobody could later say whether the name was ever public.
    """
    ops.unpublish_ark(db, root, ark=published.ark, reason="a mistake", confirm=published.ark)
    gone = ops.withdraw_ark(db, root, ark=published.ark, reason="delete it",
                            confirm=published.ark)
    db.commit()
    assert gone.published_at is not None
    assert db.get(WithdrawnName, published.ark) is not None


def test_the_orm_also_blocks_withdraw_then_delete(db, root, published):
    """A guard that can be stepped around in one move is not a guard.

    Looking only at published_at, withdrawing and then deleting walks past it. What is
    checked is first_published_at: whether it was ever public.
    """
    ops.unpublish_ark(db, root, ark=published.ark, reason="a mistake", confirm=published.ark)
    db.flush()
    row = db.get(Ark, published.ark)
    with pytest.raises(NotDeletable):
        db.delete(row)
        db.flush()


# ------------------------------- Who reaches how far: bound by reach, not tier


def test_an_organisation_admin_can_withdraw_within_its_shoulder(db, world, published, principal_of):
    """The decision to withdraw belongs to the organisation that holds the object."""
    org = principal_of(manager=world["a"], scopes={"ark:unpublish"})
    ops.unpublish_ark(db, org, ark=published.ark, reason="we want it taken down",
                      confirm=published.ark)
    db.commit()
    assert db.get(Ark, published.ark).published_at is None


def test_an_organisation_admin_can_withdraw_then_delete(db, world, published, principal_of):
    org = principal_of(manager=world["a"], scopes={"ark:unpublish", "ark:delete"})
    ops.unpublish_ark(db, org, ark=published.ark, reason="a mistake", confirm=published.ark)
    ops.withdraw_ark(db, org, ark=published.ark, reason="delete it", confirm=published.ark)
    db.commit()
    assert db.scalars(select(Ark.ark).where(Ark.ark == published.ark)).all() == []


def test_an_organisation_admin_can_publish_again(db, world, published, principal_of):
    org = principal_of(manager=world["a"], scopes={"ark:unpublish", "ark:mint"})
    ops.unpublish_ark(db, org, ark=published.ark, reason="a mistake", confirm=published.ark)
    ops.publish_ark(db, org, ark=published.ark)
    db.commit()
    assert db.get(Ark, published.ark).published_at is not None


def test_a_naan_administrator_can_withdraw_within_that_naan(db, published, principal_of):
    naan_admin = principal_of(authority=Authority.NAAN, scopes={"ark:unpublish"})
    ops.unpublish_ark(db, naan_admin, ark=published.ark, reason="a mistake",
                      confirm=published.ark)
    db.commit()
    assert db.get(Ark, published.ark).published_at is None


def test_another_organisations_publication_cannot_be_withdrawn(db, world, published, principal_of):
    """Reach still binds. Loosening it here would simply be a takeover."""
    other = principal_of(manager=world["b"], scopes={"ark:unpublish"})
    with pytest.raises(Forbidden):
        ops.unpublish_ark(db, other, ark=published.ark, reason="we want it stopped",
                          confirm=published.ark)
    assert db.get(Ark, published.ark).published_at is not None


def test_a_minting_key_alone_cannot_withdraw(as_principal, principal_of, db, published):
    """Publishing and taking down are different decisions, which is why the scopes are
    separate."""
    minter = as_principal(principal_of(manager=None, scopes={"ark:mint"}))
    r = minter.post(
        "/api/unpublish",
        json={"ark": published.ark, "reason": "we want it stopped", "confirm": published.ark},
    )
    assert r.status_code == 403
    assert db.get(Ark, published.ark).published_at is not None


def test_a_withdrawal_key_alone_cannot_delete(db, world, published, principal_of):
    """A reversible operation and an irreversible one do not share a key."""
    org = principal_of(manager=world["a"], scopes={"ark:unpublish"})
    ops.unpublish_ark(db, org, ark=published.ark, reason="a mistake", confirm=published.ark)
    db.flush()
    from arkhe.domain import authz as _authz
    with pytest.raises(Forbidden):
        _authz.require_scope(org, "ark:delete")


def test_withdrawing_and_republishing_work_from_the_screen(
    as_principal, principal_of, db, published
):
    ui = as_principal(
        principal_of(authority=Authority.NAAN, scopes={"ark:unpublish", "ark:mint"})
    )
    page = ui.get(f"/admin/arks/{published.ark}")
    assert "/unpublish" in page.text
    r = ui.post(
        f"/admin/arks/{published.ark}/unpublish",
        data={"reason": "published by mistake", "confirm": f"ark:{published.ark}"},
    )
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Ark, published.ark).published_at is None
    # Republishing is on the same page: never show only the irreversible option.
    r = ui.post(f"/admin/arks/{published.ark}/publish")
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Ark, published.ark).published_at is not None
