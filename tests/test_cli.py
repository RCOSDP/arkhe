"""The operator commands, checked against the same queries the screens use.

The CLI runs as the system administrator through _root(), so what matters here is not
authorisation but filtering and truncation: a truncated list must not read as the whole
list.
"""

from __future__ import annotations

from typer.testing import CliRunner

from arkhe import cli
from arkhe.auth.principal import Principal
from arkhe.db.models import Authority
from arkhe.domain import minting
from arkhe.domain.queries import narrow_arks, visible_arks

runner = CliRunner()


def _run(factory, *args):
    """Run a command. Only the database is substituted; authorisation and output are
    the real ones."""
    from contextlib import contextmanager

    @contextmanager
    def session():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    orig, cli._session = cli._session, session
    try:
        return runner.invoke(cli.app, list(args))
    finally:
        cli._session = orig


def _mint(db, shoulder, n, *, by="minter", url="https://example.org/{i}", title=""):
    out = []
    for i in range(n):
        ark, _ = minting.mint(
            db, shoulder=shoulder, created_by=by, url=url.format(i=i), title=title
        )
        out.append(ark)
    db.commit()
    return out


def test_ark_list_shows_what_was_minted(db, factory, world):
    _mint(db, world["sh_a"], 2)
    r = _run(factory, "ark", "list")
    assert r.exit_code == 0
    assert r.stdout.count("ark:99999/a1") == 2
    # The target has to be there: it is the column people read off the list.
    assert "https://example.org/0" in r.stdout


def test_an_empty_result_says_so(db, factory, world):
    r = _run(factory, "ark", "list")
    assert r.exit_code == 0
    from arkhe import cli_i18n

    assert any(cat["ark.list.empty"] in r.output for cat in cli_i18n.CATALOGS.values())


def test_a_truncated_list_says_so(db, factory, world):
    _mint(db, world["sh_a"], 5)
    r = _run(factory, "ark", "list", "--limit", "2")
    assert r.exit_code == 0
    # It stops at the limit and shows how to get the rest. Without that, the list
    # reads as complete.
    assert r.stdout.count("ark:") == 2
    assert "--offset 2" in r.output


def test_a_complete_list_says_nothing_about_offsets(db, factory, world):
    _mint(db, world["sh_a"], 2)
    r = _run(factory, "ark", "list", "--limit", "2")
    assert "--offset" not in r.output


def test_offset_returns_the_rest(db, factory, world):
    _mint(db, world["sh_a"], 5)
    first = _run(factory, "ark", "list", "--limit", "2").stdout
    rest = _run(factory, "ark", "list", "--limit", "2", "--offset", "2").stdout
    got = {ln.split()[0] for ln in (first + rest).splitlines() if ln.startswith("ark:")}
    assert len(got) == 4  # the pages continue without repeating


def test_filtering_by_naan_and_organisation(db, factory, world):
    _mint(db, world["sh_a"], 1)
    _mint(db, world["sh_b"], 1)
    _mint(db, world["sh_c"], 1)  # another NAAN

    assert _run(factory, "ark", "list", "--naan", "88888").stdout.count("ark:") == 1
    out = _run(factory, "ark", "list", "--org", str(world["a"].id)).stdout
    assert "ark:99999/a1" in out and "ark:99999/b2" not in out


def test_search_looks_at_the_ark_the_target_and_the_title(db, factory, world):
    """The same three fields as the screens, because whoever is searching may only
    have one of them."""
    _mint(db, world["sh_a"], 1, url="https://findme.example/x", title="unrelated")
    _mint(db, world["sh_b"], 1, url="https://other.example/y", title="the wanted title")

    assert _run(factory, "ark", "list", "-q", "findme").stdout.count("ark:") == 1
    assert _run(factory, "ark", "list", "-q", "wanted").stdout.count("ark:") == 1
    # The ARK itself works as a query too
    assert _run(factory, "ark", "list", "-q", "a1").stdout.count("ark:") == 1


def test_filtering_cannot_widen_the_reach(db, world):
    """Why the screens and the CLI share one query.

    When a principal bound to one organisation names another one with --org, nothing
    comes back, because visible_arks has already narrowed the query.
    """
    _mint(db, world["sh_a"], 1)
    _mint(db, world["sh_b"], 1)
    only_a = Principal(
        client_id="c", naan="99999", authority=Authority.MANAGER, manager_id=world["a"].id
    )
    stmt = narrow_arks(visible_arks(only_a), org=str(world["b"].id))
    assert db.scalars(stmt).all() == []
