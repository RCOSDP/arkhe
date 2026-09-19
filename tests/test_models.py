"""Invariants in the models: make the wrong thing impossible rather than forbidden."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from arkhe.db.models import Ark, Naan, NotDeletable
from arkhe.domain import minting


def test_nr_a_published_ark_cannot_be_deleted(db, world):
    """Deleting the row stops resolution, which breaks the identifier. Tombstone it or
    empty the URL instead.

    Only an unpublished ARK can be deleted, which test_publication.py covers.
    """
    ark, _ = minting.mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    with pytest.raises(NotDeletable):
        db.delete(ark)
        db.flush()


def test_nr_a_shoulder_cannot_be_deleted(db, world):
    """Random assignment could hand out the same string again, which is how an NR
    violation starts."""
    with pytest.raises(NotDeletable):
        db.delete(world["sh_a"])
        db.flush()


def test_e1_the_same_ark_cannot_be_created_twice(db, world):
    """The worst flaw in arklet: a primary key collision turned into an UPDATE and
    silently rewrote where an existing ARK pointed."""
    ark, _ = minting.mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    db.add(
        Ark(
            ark=ark.ark, naan="99999", shoulder_id=world["sh_a"].id,
            assigned_name=ark.assigned_name,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_d3_an_authoritative_naan_has_no_redirect(db):
    db.add(Naan(naan="70000", name="bad", is_authoritative=True, redirect="https://x"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_d3_a_non_authoritative_naan_needs_a_redirect(db):
    db.add(Naan(naan="70001", name="bad", is_authoritative=False, redirect=""))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_n2_a_naan_is_a_string(db, root):
    """099999 and 99999 are different NAANs, so they must never become integers."""
    from arkhe.domain import admin_ops as ops

    ops.create_naan(db, root, naan="99999", name="a")
    ops.create_naan(db, root, naan="099999", name="b")
    db.commit()
    assert db.get(Naan, "99999").name == "a"
    assert db.get(Naan, "099999").name == "b"


def test_minting_retries_after_a_collision(db, world):
    """The collision count is returned so that a namespace filling up can be
    noticed."""
    arks = [minting.mint(db, shoulder=world["sh_a"], created_by="t") for _ in range(20)]
    db.commit()
    assert len({a.ark for a, _ in arks}) == 20
    assert all(c == 0 for _, c in arks)  # eight characters do not collide over 20


def test_b4_a_qualifier_stays_inside_the_base_namespace(db, world):
    base, _ = minting.mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    child = minting.register_qualified(db, base=base, qualifier="/page/1", created_by="t")
    db.commit()
    assert child.shoulder_id == base.shoulder_id
    assert child.assigned_name.startswith(base.assigned_name)


def test_b4_an_existing_qualifier_is_not_overwritten(db, world):
    base, _ = minting.mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    minting.register_qualified(db, base=base, qualifier="/p", created_by="t")
    db.commit()
    with pytest.raises(minting.AlreadyRegistered):
        minting.register_qualified(db, base=base, qualifier="/p", created_by="t")


@pytest.mark.parametrize("bad", ["page", "-x", ""])
def test_b4_a_qualifier_starts_with_a_separator(db, world, bad):
    base, _ = minting.mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    with pytest.raises(ValueError):
        minting.register_qualified(db, base=base, qualifier=bad, created_by="t")


def test_the_entity_diagram_matches_the_implementation():
    """A diagram left alone goes stale. Check that the tables and their main columns
    appear in it.

    The columns need not match exactly, because a diagram selects what matters. What is
    caught is a table added without being drawn, and a column removed while the diagram
    still shows it.
    """
    import re
    from pathlib import Path

    from arkhe.db.models import Base

    doc = Path(__file__).resolve().parents[1] / "docs" / "reference" / "data-model.ja.md"
    text = doc.read_text(encoding="utf-8")
    block = re.search(r"```mermaid\n(.*?)```", text, re.S).group(1)

    for name, table in Base.metadata.tables.items():
        assert name.upper() in block, f"{name} is missing from the diagram"
        drawn = set(re.findall(rf"{name.upper()} \{{(.*?)\n    \}}", block, re.S))
        if not drawn:
            continue
        lines = next(iter(drawn)).strip().splitlines()
        cols = {ln.split()[1] for ln in lines if len(ln.split()) > 1}
        real = set(table.columns.keys())
        # A column in the diagram but not in the code is stale or misspelt. The
        # diagram writes title as what_title.
        stale = {c for c in cols if c not in real and c not in {"what_title"}}
        assert not stale, f"{name}: drawn but not in the code: {sorted(stale)}"


def test_the_version_comes_from_one_place():
    """Written in two places, one of them goes stale.

    pyproject.toml is the only source; the package and the OpenAPI documents read it.
    """
    import tomllib
    from pathlib import Path

    import arkhe

    root = Path(__file__).resolve().parents[1]
    declared = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    assert arkhe.__version__ == declared

    # No other place assigns the version. A plain search would match 0.0.1 inside
    # 127.0.0.1, so only "version=" with the literal is looked for.
    import re

    pattern = re.compile(rf'version\s*=\s*["\']{re.escape(declared)}["\']')
    hits = [
        str(f.relative_to(root))
        for f in (root / "src").rglob("*.py")
        if pattern.search(f.read_text(encoding="utf-8"))
    ]
    assert not hits, f"the version is hard-coded in: {hits}"


def test_the_changelogs_match_in_both_languages():
    """Stop one of them from being updated alone.

    The version headings have to match. The prose does not: a translation is a
    translation, not a copy.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    def versions(name: str) -> list[str]:
        text = (root / name).read_text(encoding="utf-8")
        return re.findall(r"^## \[([^\]]+)\]", text, re.M)

    en, ja = versions("CHANGELOG.md"), versions("CHANGELOG.ja.md")
    # Only the unreleased heading differs in wording, so normalise it first. The
    # Japanese heading is quoted because CHANGELOG.ja.md is written in Japanese.
    norm = {"Unreleased": "-", "\u672a\u30ea\u30ea\u30fc\u30b9": "-"}
    assert [norm.get(v, v) for v in en] == [norm.get(v, v) for v in ja], (en, ja)

    import tomllib

    declared = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    assert declared in en, f"{declared} has no section in the changelog"


def test_principals_without_a_label_can_repeat_within_an_organisation(db, world, root):
    """An empty label is not a name collision.

    Treating it as one would stop an ordinary split by role, such as web-api, web-ui and
    worker, from existing in a single organisation, and push people to share one key.
    """
    from arkhe.domain import admin_ops as ops

    sh = world["a"].default_shoulder
    for cid in ("p1", "p2", "p3"):
        ops.register_client(db, root, client_id=cid, naan=sh.naan, shoulder_id=sh.id)
    db.commit()


def test_one_active_principal_per_label(db, world, root):
    """Labelled principals stay unique, so the rotation pattern still works."""
    from arkhe.domain import admin_ops as ops

    sh = world["a"].default_shoulder
    ops.register_client(db, root, client_id="l1", naan=sh.naan, shoulder_id=sh.id, label="bot")
    db.commit()
    with pytest.raises(IntegrityError):
        # register_client flushes, so the unique constraint fires here.
        ops.register_client(
            db, root, client_id="l2", naan=sh.naan, shoulder_id=sh.id, label="bot"
        )
    db.rollback()


def test_the_lock_file_matches_the_declaration():
    """Passing while they differ is the bad outcome.

    Adding a dependency to pyproject.toml without running uv lock installs something
    different in each place. This checks the same thing uv sync --frozen does.
    """
    import pathlib
    import re
    import tomllib

    root = pathlib.Path(__file__).resolve().parents[1]
    lock = (root / "uv.lock").read_text()
    declared = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    names = []
    for group in declared.get("optional-dependencies", {}).values():
        names += [re.split(r"[<>=\[]", x)[0].strip() for x in group]
    missing = [n for n in set(names) if f'name = "{n.lower()}"' not in lock.lower()]
    assert not missing, f"missing from uv.lock: {missing} (run `uv lock`)"


def test_a_collision_is_recorded(db, world, caplog):
    """Counting collisions and throwing the count away would be pointless.

    A collision is the only sign that a namespace is filling up. One does no harm, since
    minting retries, but a rising rate means the names need another character, and
    nobody sees that unless it is recorded.
    """
    import logging
    from unittest.mock import patch

    from arkhe.domain import minting

    # Return the same name twice, so exactly one collision happens.
    names = iter(["bcdfghjkm", "bcdfghjkm", "npqrstvwx"])
    with caplog.at_level(logging.WARNING, logger="arkhe"), \
            patch.object(minting, "generate_noid", lambda n: next(names)):
        first, c1 = minting.mint(db, shoulder=world["sh_a"], created_by="t")
        second, c2 = minting.mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()

    assert c1 == 0 and c2 == 1, "the second mint should collide once"
    assert first.ark != second.ark
    hit = [r for r in caplog.records if r.getMessage() == "mint_collision"]
    assert hit, "a collision happened but was not recorded"
    assert hit[0].fields["collisions"] == 1
    assert hit[0].fields["shoulder"] == world["sh_a"].shoulder


def test_nothing_is_recorded_without_a_collision(db, world, caplog):
    """A line per mint would soon stop being read."""
    import logging

    from arkhe.domain import minting

    with caplog.at_level(logging.WARNING, logger="arkhe"):
        minting.mint(db, shoulder=world["sh_a"], created_by="t")
    db.commit()
    assert not [r for r in caplog.records if r.getMessage() == "mint_collision"]


def test_dangerous_schemes_are_refused_at_the_bottom_layer(db, world):
    """Validation written at each entrance stops working when an entrance is added.

    The admin form took a plain string and called minting.mint() directly, so it went
    straight past the API schema's validation. The rule that the screens and the API
    behave alike was broken by where the validation lived.

    It was not exploitable: redirection and links go through an allow list
    (is_followable), so a javascript: URL was never followed or linked. But that guards
    the moment of use, and the moment of entry needs its own.
    """
    import pytest

    from arkhe.domain.minting import mint

    for bad in ("javascript:alert(1)", "data:text/html,<script>1</script>", "VBScript:x"):
        with pytest.raises(ValueError):
            mint(db, shoulder=world["sh_a"], created_by="t", url=bad)
        db.rollback()


def test_valid_non_http_targets_are_accepted(db, world):
    """An ARK can name a physical object or another identifier.

    Refusing urn:, doi: or mailto: would rule out central uses of the scheme. Empty is
    valid too: an object with no target is exactly what ?info is for.
    """
    from arkhe.domain.minting import mint

    for ok in ("urn:isbn:9784000000000", "doi:10.1234/x", "mailto:a@example.org", ""):
        a, _ = mint(db, shoulder=world["sh_a"], created_by="t", url=ok)
        assert a.url == ok
    db.commit()
