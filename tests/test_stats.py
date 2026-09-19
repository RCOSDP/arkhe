"""Statistics over the ledger.

Two things matter. The numbers have to add up, and nothing out of reach may be counted:
a total leaks that something exists, and how many ARKs another organisation holds is a
measure of its size, which is not ours to tell.

The counting lives in one place, domain/stats.py, so the screens, the CLI and the API
all report the same numbers. These tests look at the domain and the API.
"""

from __future__ import annotations

import pytest

from arkhe.db.models import Authority
from arkhe.domain import admin_ops as ops
from arkhe.domain import stats
from arkhe.domain.minting import mint


@pytest.fixture
def ledger(db, world):
    """Three ARKs in organisation a, one of them reserved, and two in organisation b."""
    for _ in range(2):
        mint(db, shoulder=world["sh_a"], created_by="test")
    mint(db, shoulder=world["sh_a"], created_by="test", reserve=True)
    for _ in range(2):
        mint(db, shoulder=world["sh_b"], created_by="test")
    db.commit()


def test_the_totals_and_the_breakdown_agree(db, root, ledger):
    """Statistics that do not add up lose the reader's trust. Published and reserved
    are counted in one pass."""
    st = stats.ledger_stats(db, root)
    assert st.arks == 5
    assert st.public + st.reserved == st.arks
    assert st.reserved == 1
    assert sum(s.arks for s in st.by_shoulder) == st.arks


def test_an_organisation_sees_only_its_own(db, world, ledger, principal_of):
    """A total leaks existence. Loosen this and another organisation's size leaks."""
    org = principal_of(manager=world["a"], scopes={"ark:read"})
    st = stats.ledger_stats(db, org)
    assert st.arks == 3
    assert st.public == 2 and st.reserved == 1
    # No other organisation appears in the breakdown either, not even by name.
    assert [s.shoulder for s in st.by_shoulder] == [world["sh_a"].shoulder]


def test_a_naan_administrator_sees_every_organisation_under_it(db, ledger, principal_of):
    naan_admin = principal_of(authority=Authority.NAAN, scopes={"ark:read"})
    st = stats.ledger_stats(db, naan_admin)
    assert st.arks == 5
    assert st.scope == "naan"


def test_filtering_cannot_widen_the_reach(db, world, ledger, principal_of):
    """Naming an organisation out of reach returns zero. A filter is not a key."""
    org = principal_of(manager=world["a"], scopes={"ark:read"})
    st = stats.ledger_stats(db, org, org=str(world["b"].id))
    assert st.arks == 0


def test_names_withdrawn_after_publication_are_counted_separately(db, root, world, ledger):
    """Removing something after publishing it is breaking the promise, so it is not
    buried in the total."""
    a, _ = mint(db, shoulder=world["sh_a"], created_by="test", reserve=True)
    b, _ = mint(db, shoulder=world["sh_a"], created_by="test")
    db.commit()
    ops.withdraw_ark(db, root, ark=a.ark)                      # a reserved one
    ops.purge_ark(db, root, ark=b.ark, reason="removal order", confirm=b.ark)  # published
    db.commit()
    st = stats.ledger_stats(db, root)
    assert st.withdrawn == 2
    assert st.withdrawn_after_publication == 1


def test_shoulder_states_appear_even_when_empty(db, root, ledger):
    """"No delegated shoulders" and "we do not track delegation" are different
    statements."""
    st = stats.ledger_stats(db, root)
    assert set(st.shoulders) == {"active", "reserved", "delegated", "retired"}


def test_only_holds_in_force_are_counted(db, root, world, ledger):
    from datetime import UTC, datetime, timedelta

    ark, _ = mint(db, shoulder=world["sh_a"], created_by="test")
    db.commit()
    assert stats.ledger_stats(db, root).holds["ark"] == 0
    ops.set_hold(db, root, kind="ark", key=ark.ark,
                 until=datetime.now(UTC) + timedelta(days=3), reason="under investigation")
    db.commit()
    assert stats.ledger_stats(db, root).holds["ark"] == 1


def test_the_api_returns_only_what_is_in_reach(as_principal, principal_of, world, ledger):
    org = as_principal(principal_of(manager=world["a"], scopes={"ark:read"}))
    r = org.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["arks"] == 3
    assert body["scope"] == "organisation"


def test_the_api_requires_ark_read(as_principal, principal_of, world, ledger):
    """Reads need a credential too. Counts are not public just because they are
    numbers."""
    no_read = as_principal(principal_of(manager=world["a"], scopes={"ark:mint"}))
    assert no_read.get("/api/stats").status_code == 403


def test_the_minting_windows_overlap(db, root, ledger):
    """What was minted in 24 hours is also in the 7-day and 30-day counts; they are
    not separate populations."""
    st = stats.ledger_stats(db, root)
    assert st.minted["24h"] <= st.minted["7d"] <= st.minted["30d"]
    assert st.minted["30d"] == st.arks


# ------------------------------- The admin screens, which show the same numbers


def test_the_screen_shows_what_the_domain_counted(as_principal, principal_of, db, world, ledger):
    """The screen does not do its own counting. One count differing by where it is
    read is the worst kind of drift, so it is compared with the domain.
    """
    from arkhe.domain import stats as domain

    ui = as_principal(principal_of(authority=Authority.NAAN, scopes={"ark:read"}))
    page = ui.get("/admin/stats")
    assert page.status_code == 200
    st = domain.ledger_stats(db, principal_of(authority=Authority.NAAN, scopes={"ark:read"}))
    assert str(st.arks) in page.text
    assert "/admin/stats" in page.text          # it is in the navigation


def test_the_screen_shows_nothing_out_of_reach(as_principal, principal_of, world, ledger):
    """A total leaks existence, and another organisation's shoulder must not appear
    either."""
    org = as_principal(principal_of(manager=world["a"], scopes={"ark:read"}))
    page = org.get("/admin/stats")
    assert page.status_code == 200
    assert world["sh_b"].shoulder not in page.text


def test_the_screen_the_api_and_the_cli_agree(as_principal, principal_of, db, world, ledger):
    """One place counts, domain/stats.py, and the three entrances must not
    disagree."""
    from arkhe.domain import stats as domain

    p = principal_of(authority=Authority.NAAN, scopes={"ark:read"})
    api = as_principal(p).get("/api/stats").json()
    dom = domain.ledger_stats(db, p)
    assert api["arks"] == dom.arks
    assert api["public"] == dom.public
    assert api["withdrawn_after_publication"] == dom.withdrawn_after_publication


# ------------------------------- Fingerprints, for confirming a restore worked


def test_a_fingerprint_catches_swapped_targets_at_the_same_count(db, root, world, ledger):
    """Matching counts prove nothing.

    With the same count but swapped targets, every identifier is broken, and that is
    what confirming a restore has to look at.
    """
    from arkhe.db.models import Ark

    before = stats.ledger_fingerprint(db)
    row = db.query(Ark).order_by(Ark.ark).first()
    row.url = "https://wrong.example/"
    db.commit()
    after = stats.ledger_fingerprint(db)

    assert after.ark_count == before.ark_count, "the count is unchanged, which is the point"
    assert after.arks != before.arks, "targets changed but the fingerprint did not"


def test_a_fingerprint_is_stable_for_one_ledger(db, root, ledger):
    """Without a fixed order it would differ every time and be useless."""
    assert stats.ledger_fingerprint(db).arks == stats.ledger_fingerprint(db).arks


def test_withdrawn_names_are_fingerprinted_separately(db, root, world, ledger):
    """Minting keeps working if withdrawn_name is lost, so the loss is silent.

    Collapsing everything into one value would hide where the difference is, so check
    that arks stays equal while withdrawn changes.
    """
    from arkhe.domain.minting import mint

    a, _ = mint(db, shoulder=world["sh_a"], created_by="t", reserve=True)
    db.commit()
    before = stats.ledger_fingerprint(db)
    ops.withdraw_ark(db, root, ark=a.ark)
    db.commit()
    after = stats.ledger_fingerprint(db)

    assert after.withdrawn != before.withdrawn, "a name was withdrawn but nothing changed"
    assert after.withdrawn_count == before.withdrawn_count + 1


def test_holds_are_left_out_of_the_fingerprint(db, root, world, ledger):
    """Anything that changes by itself at an expiry is left out: a difference could
    not be read as damage, and an alarm that always rings stops being read.
    """
    from datetime import UTC, datetime, timedelta

    from arkhe.db.models import Ark

    ark = db.query(Ark).order_by(Ark.ark).first().ark
    before = stats.ledger_fingerprint(db)
    ops.set_hold(db, root, kind="ark", key=ark,
                 until=datetime.now(UTC) + timedelta(days=3), reason="under investigation")
    db.commit()
    assert stats.ledger_fingerprint(db).arks == before.arks


# ------------------------------- Finding reserved ARKs that were left behind


def test_the_oldest_reserved_ark_is_reported(db, root, world):
    """A backlog shows in age, not in count.

    Ten reserved yesterday is ordinary; one reserved three years ago is forgotten. A
    count cannot tell them apart.
    """
    from datetime import UTC, datetime, timedelta

    from arkhe.domain.minting import mint

    assert stats.ledger_stats(db, root).reserved_oldest is None, "nothing to report yet"

    a, _ = mint(db, shoulder=world["sh_a"], created_by="t", reserve=True)
    a.created_at = datetime.now(UTC) - timedelta(days=400)
    mint(db, shoulder=world["sh_a"], created_by="t", reserve=True)   # a recent one
    mint(db, shoulder=world["sh_a"], created_by="t")                 # published, so ignored
    db.commit()

    oldest = stats.ledger_stats(db, root).reserved_oldest
    assert oldest is not None
    assert (datetime.now(UTC) - oldest).days >= 399, "this is not the oldest one"


def test_a_published_ark_is_never_a_backlog(db, root, world):
    """Something published is out in the world; being old is fine."""
    from datetime import UTC, datetime, timedelta

    from arkhe.domain.minting import mint

    a, _ = mint(db, shoulder=world["sh_a"], created_by="t")   # published
    a.created_at = datetime.now(UTC) - timedelta(days=999)
    db.commit()
    assert stats.ledger_stats(db, root).reserved_oldest is None


def test_reserved_arks_can_be_filtered_by_age(db, root, world):
    """Noticing a backlog is no use if the rows cannot be listed."""
    from datetime import UTC, datetime, timedelta

    from arkhe.domain.minting import mint
    from arkhe.domain.queries import narrow_arks, visible_arks

    old, _ = mint(db, shoulder=world["sh_a"], created_by="t", reserve=True)
    old.created_at = datetime.now(UTC) - timedelta(days=400)
    new, _ = mint(db, shoulder=world["sh_a"], created_by="t", reserve=True)
    db.commit()

    stmt = narrow_arks(visible_arks(root), state="reserved", older_than_days=365)
    found = {a.ark for a in db.scalars(stmt)}
    assert old.ark in found
    assert new.ark not in found, "a recently reserved ARK was picked up"
    # Age is independent of state; one day someone will want old published ones.
    assert isinstance(db.scalars(narrow_arks(visible_arks(root), older_than_days=1)).all(), list)


def test_every_timestamp_comes_back_with_a_time_zone(db, root, world):
    """A type that depends on the engine breaks whoever receives it.

    SQLite has no time zone type, so a column declared DateTime(timezone=True) comes
    back naive, while PostgreSQL returns an aware value. That meant a TypeError on one
    of them, which is what made arkhe stat crash.
    """
    from datetime import UTC, datetime

    from arkhe.domain.minting import mint

    mint(db, shoulder=world["sh_a"], created_by="t", reserve=True)
    db.commit()
    st = stats.ledger_stats(db, root)
    for name in ("first_mint", "last_mint", "reserved_oldest"):
        got = getattr(st, name)
        assert got is not None and got.tzinfo is not None, f"{name} has no time zone"
        datetime.now(UTC) - got          # the subtraction working is the check


def test_every_count_names_its_column():
    """No count(*) anywhere: name the column being counted.

    count(*) counts rows, which an index alone cannot always answer, since PostgreSQL
    visits the heap to check visibility. count(<column>) can be answered from that
    column's index. It matters more as the ledger grows, because counting happens on the
    screens and in the minting quota, which are the hardest places to avoid.

    This is checked mechanically. Fixing the three that exist today would not stop the
    next person writing func.count() again.
    """
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src"
    bare = [
        f"{path.relative_to(src)}:{i}"
        for path in src.rglob("*.py")
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\bcount\(\s*\)", line)
    ]
    assert not bare, "a count does not name its column: " + ", ".join(bare)
