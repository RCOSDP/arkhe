"""That the reference pages have not fallen behind the implementation.

Nothing here relies on remembering to write something down. It is the same principle the
rest of arkhe follows, rules live in code, applied to the documentation: a rule that
depends on memory is eventually broken. When these checks were added, two settings and
one command were already missing.

Only the reference pages with tables are covered. Binding the prose mechanically would
stop people writing it at all. The exception is example ARKs, because whether a check
digit is correct is a fact a machine can verify, so it can be bound even in prose.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from arkhe import cli
from arkhe.settings import Settings

DOCS = pathlib.Path(__file__).resolve().parents[1] / "docs"


def _commands(app, prefix: str = "") -> list[str]:
    out = [f"{prefix}{c.name or c.callback.__name__.replace('_', '-')}"
           for c in app.registered_commands]
    for g in app.registered_groups:
        out += _commands(g.typer_instance, f"{prefix}{g.name} ")
    return sorted(out)


@pytest.mark.parametrize("page", ["reference/configuration.md", "reference/configuration.ja.md"])
def test_every_setting_is_on_the_reference_page(page):
    doc = (DOCS / page).read_text(encoding="utf-8")
    missing = [f"ARKHE_{n.upper()}" for n in Settings.model_fields
               if f"ARKHE_{n.upper()}" not in doc]
    assert not missing, f"settings missing from {page}: {missing}"


@pytest.mark.parametrize("page", ["reference/cli.md", "reference/cli.ja.md"])
def test_every_command_is_on_the_reference_page(page):
    doc = (DOCS / page).read_text(encoding="utf-8")
    missing = [c for c in _commands(cli.app) if f"arkhe {c}" not in doc]
    assert not missing, f"commands missing from {page}: {missing}"


def test_both_languages_have_the_same_table_rows():
    """Catch a row added to one language only. The prose is not compared.

    A row missing from one page means that setting or command does not exist for those
    readers.
    """
    def rows(text: str) -> int:
        return sum(1 for ln in text.splitlines() if ln.startswith("| `"))

    for stem in ("reference/configuration", "reference/cli"):
        en = rows((DOCS / f"{stem}.md").read_text(encoding="utf-8"))
        ja = rows((DOCS / f"{stem}.ja.md").read_text(encoding="utf-8"))
        assert en == ja, f"{stem}: table rows differ, en={en} ja={ja}"


# --------------------------------------------------------------------------
# The published OpenAPI documents are in English
# --------------------------------------------------------------------------


@pytest.mark.parametrize("resolver", [False, True], ids=["minter", "resolver"])
def test_no_japanese_leaks_into_the_published_openapi(resolver):
    """The readers are outside this ledger and may not read Japanese.

    Anything that reaches the specification through a docstring or a message catalogue
    would leak, so the leak is detected here rather than relying on someone remembering
    each time a route is added.
    """
    import re

    from arkhe.app import create_app

    schema = create_app(
        Settings(resolver=resolver, database_url="sqlite://", auth=["apikey", "oauth2"],
                 admin_login="bearer", token_secret="x" * 32)
    ).openapi()

    cjk = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]")
    found = []

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str) and cjk.search(node):
            found.append(f"{path}: {node[:60]}")

    walk(schema)
    assert not found, "Japanese in the OpenAPI document:\n  " + "\n  ".join(found)


# --------------------------------------------------------------------------
# Every error code is on the reference page
# --------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["reference/errors.md", "reference/errors.ja.md"])
def test_every_error_code_is_on_the_reference_page(page):
    """Stop a code being added without being written down.

    A code is a promise that callers may branch on it rather than on the wording, so
    returning one that is not in the list breaks that promise. Same reasoning as the
    settings and the commands above.
    """
    from arkhe import errors

    text = (DOCS / page).read_text()
    missing = [c.number for c in errors.CODES if f"`{c.number}`" not in text]
    assert not missing, f"codes missing from {page}: {missing}"


def test_codes_are_unique_and_in_order():
    """A code is never reused: two different meanings behind one number breaks every
    caller that branches on it."""
    from arkhe import errors

    numbers = [c.number for c in errors.CODES]
    assert len(numbers) == len(set(numbers))
    assert numbers == sorted(numbers)
    assert all(n.startswith("ARKHE-") and n[6:].isdigit() for n in numbers)


def test_each_code_has_english_wording_and_a_japanese_note():
    """Both are needed: the message that goes out is English, and the operational note
    is Japanese."""
    import re

    from arkhe import errors

    cjk = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]")
    for c in errors.CODES:
        # No Japanese in the message itself.
        assert c.message.strip() and not cjk.search(c.message), c.number
        assert cjk.search(c.ja), c.number


# --------------------------------------------------------------------------
# Example ARKs are shaped like ARKs that would really be minted
# --------------------------------------------------------------------------

#: The NAAN used in examples. Other NAANs, such as ark:12345/... or the real
#: ark:67531/..., follow their own institution's conventions, not ours.
EXAMPLE_NAAN = "99999"

#: Examples that are deliberately wrong. What a check digit protects can only be shown
#: with a name that fails it.
DELIBERATELY_WRONG = {
    "x9tn1qkq2g8": "a transcription error, told apart from a 404 (ARKHE-1403)",
    "c7w545sj4zz": "a name from outside that import refuses (ARKHE-1012)",
}

#: Where the reader is meant to substitute their own name, the example ends in an
#: ellipsis and is skipped. Qualifiers such as /c3, .pdf or %2F... are cut here, which
#: is exactly right: N7 computes the check digit over the base name.
_ARK = re.compile(r"ark:/?(\d{5})/([0-9a-z]+)(\u2026?)")

#: The OpenAPI documents are generated from the implementation, so including them
#: binds the examples written in docstrings as well.
_PAGES = sorted(DOCS.rglob("*.md")) + sorted(DOCS.glob("assets/openapi-*.json"))


def _example_arks():
    """Yield (page, line, name) for every ark:99999/... in the documentation."""
    for path in _PAGES:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for naan, name, elided in _ARK.findall(line):
                if naan == EXAMPLE_NAAN and not elided:
                    yield path.relative_to(DOCS), lineno, name


def test_example_arks_are_shaped_like_minted_ones():
    """Readers learn the shape from the examples.

    An example that could never be minted teaches the wrong length and the wrong
    character set. Two things are checked: that the name is betanumeric, with no vowels
    and no l, and that the check digit is correct. Both are rules arkspec really
    enforces, so an example that drifts from the implementation fails here.
    """
    from arkhe.arkspec.betanumeric import BETANUMERIC, verify_ark_check_digit

    bad = []
    for page, lineno, name in _example_arks():
        if name in DELIBERATELY_WRONG:
            continue
        if outside := set(name) - set(BETANUMERIC):
            bad.append(f"{page}:{lineno} ark:99999/{name} - not betanumeric: "
                       f"{sorted(outside)}")
        elif not verify_ark_check_digit(EXAMPLE_NAAN, name):
            bad.append(f"{page}:{lineno} ark:99999/{name} - the check digit is wrong")
    assert not bad, "examples that could not be minted:\n  " + "\n  ".join(bad)


def test_the_deliberately_wrong_examples_really_are_wrong():
    """Keep the allow list from going stale.

    Renaming an example without updating DELIBERATELY_WRONG leaves a hole in the check
    above. So both are verified: that each one still fails, and that it still appears in
    the documentation.
    """
    from arkhe.arkspec.betanumeric import verify_ark_check_digit

    for name, why in DELIBERATELY_WRONG.items():
        assert not verify_ark_check_digit(EXAMPLE_NAAN, name), f"{name} now passes ({why})"

    used = {name for _, _, name in _example_arks()}
    assert not (set(DELIBERATELY_WRONG) - used), \
        f"allowed but no longer in the documentation: {sorted(set(DELIBERATELY_WRONG) - used)}"


# --------------------------------------------------------------------------
# Every route and scope in the implementation appears in the changelog
# --------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Routes that predate this check. The changelog describes them in prose but never
#: spells the path: /api/hold is "holding redirection", and /ark:{rest} is the
#: resolution path itself. Nothing newly added belongs here; if a path is missing, it
#: has not been written down yet.
PREDATES_THE_CHECK = {
    "/api/hold",
    "/api/hold/release",
    "/api/register",
    "/api/update/bulk",
    "/ark:{rest}",
    "/ark:/{rest}",
    "ark:update",
}


def _exposed() -> set[str]:
    """The routes and scopes the implementation exposes, taken from the OpenAPI
    documents.

    Those are generated from the implementation and check.sh fails when the committed
    copies differ, so a route cannot exist without appearing there.
    """
    import json

    names: set[str] = set()
    for f in ("openapi-minter.json", "openapi-resolver.json"):
        spec = json.loads((DOCS / "assets" / f).read_text(encoding="utf-8"))
        names |= set(spec.get("paths", {}))
        for scheme in spec.get("components", {}).get("securitySchemes", {}).values():
            for flow in scheme.get("flows", {}).values():
                names |= set(flow.get("scopes", {}))
    return names


def test_routes_and_scopes_appear_in_the_changelog():
    """Stop something being added without being written down.

    0.3.0 shipped POST /api/purge and ark:purge without a word in either changelog. The
    implementation, the tests and the guards were all there, and it appeared in cli.md,
    errors.md and the OpenAPI documents, but the changelog was silent. That happens in a
    58-file diff. A scope in particular is something operators can only learn from the
    changelog.

    Both languages are checked: present in only one is absent for those readers.
    """
    logs = {name: (ROOT / name).read_text(encoding="utf-8")
            for name in ("CHANGELOG.md", "CHANGELOG.ja.md")}
    missing = [f"{n} is missing from {log}"
               for n in sorted(_exposed() - PREDATES_THE_CHECK)
               for log, text in logs.items() if n not in text]
    assert not missing, "missing from the changelog:\n  " + "\n  ".join(missing)


def test_the_allowed_old_routes_still_exist():
    """Keep the allow list from going stale. Renaming a route without updating
    PREDATES_THE_CHECK would let the new spelling through unseen.
    """
    gone = PREDATES_THE_CHECK - _exposed()
    assert not gone, f"allowed but no longer implemented: {sorted(gone)}"


def _status_test_table() -> str:
    """The code block under the list of test files in STATUS.md.

    Only that block is read, not the whole file: a file name appearing somewhere else
    would pass without the list itself being right. STATUS.md is written in Japanese, so
    its heading is quoted as an escape.
    """
    heading = "\u30c6\u30b9\u30c8\u306e\u5185\u8a33"  # "the test breakdown"
    text = (ROOT / "STATUS.md").read_text(encoding="utf-8")
    _, _, after = text.partition(heading)
    assert after, "STATUS.md has no list of test files"
    parts = after.split("```")
    assert len(parts) >= 3, "no code block under the list of test files"
    return parts[1]


def test_the_test_file_list_matches_what_exists():
    """Keep the one remaining list from falling behind.

    This list also lived in AGENTS.md, where it was five files out of date. The
    duplicate is gone and only STATUS.md has it, so nobody would notice it drifting.

    Both directions are checked. A file that is missing leaves a hole, and a file that
    is listed but does not exist is just as bad: after a rename the old name stays and
    the reader cannot find it.
    """
    listed = set(re.findall(r"test_\w+\.py", _status_test_table()))
    files = {p.name for p in (ROOT / "tests").glob("test_*.py")}
    assert not (files - listed), f"missing from the list in STATUS.md: {sorted(files - listed)}"
    assert not (listed - files), f"listed but not present: {sorted(listed - files)}"


#: Screens that predate this check. Some are never spelt out: /admin/callback is where
#: OIDC returns to, not somewhere a reader goes. Nothing newly added belongs here.
PAGES_PREDATING_THE_CHECK = {
    "/admin/",
    "/admin/arks",
    "/admin/audit",
    "/admin/callback",
    "/admin/client/new",
    "/admin/clients",
    "/admin/holds",
    "/admin/login",
    "/admin/manager/new",
    "/admin/mint",
    "/admin/naan/new",
    "/admin/shoulder/new",
}


def _admin_pages() -> set[str]:
    """The admin pages: GET routes with no variable in the path.

    Routes with a variable, such as /admin/arks/{ark}, and POST operations are not
    things a reader would write down, so they are not demanded here.
    """
    from fastapi.routing import APIRoute

    from arkhe.api import admin

    return {
        r.path
        for r in admin.router.routes
        if isinstance(r, APIRoute) and "GET" in r.methods and "{" not in r.path
    }


def test_admin_pages_appear_in_the_changelog():
    """The screens are not in the OpenAPI documents, so the route check cannot see
    them.

    0.5.0 added the statistics page without a word in either changelog. The CLI and the
    API were written up; only the screen, added later, was missed, the same shape as the
    purge omission in 0.3.0. A person caught it before release, but nothing stopped it.
    """
    logs = {name: (ROOT / name).read_text(encoding="utf-8")
            for name in ("CHANGELOG.md", "CHANGELOG.ja.md")}
    missing = [f"{p} is missing from {log}"
               for p in sorted(_admin_pages() - PAGES_PREDATING_THE_CHECK)
               for log, text in logs.items() if p not in text]
    assert not missing, "screens missing from the changelog:\n  " + "\n  ".join(missing)


def test_the_allowed_old_screens_still_exist():
    """Keep the allow list from going stale. Changing a path without updating it would
    let the new spelling through unseen.
    """
    gone = PAGES_PREDATING_THE_CHECK - _admin_pages()
    assert not gone, f"allowed but no longer implemented: {sorted(gone)}"


#: Commands whose names do not appear in the changelog. It is empty: there were 13
#: when the check was added, and each was filled in under the version that introduced
#: it. Keep it empty. If you want to add one, write the changelog entry instead.
COMMANDS_PREDATING_THE_CHECK: set[str] = set()


def test_operator_commands_appear_in_the_changelog():
    """The reference page was bound, but the changelog was not.

    Whether a command is in cli.md has been checked for a while, but that does not tell
    a reader when it appeared. arkhe stat happened to be written up; nothing enforced
    it.
    """
    logs = {name: (ROOT / name).read_text(encoding="utf-8")
            for name in ("CHANGELOG.md", "CHANGELOG.ja.md")}
    missing = [f"arkhe {c} is missing from {log}"
               for c in _commands(cli.app)
               if c not in COMMANDS_PREDATING_THE_CHECK
               for log, text in logs.items() if f"arkhe {c}" not in text]
    assert not missing, "commands missing from the changelog:\n  " + "\n  ".join(missing)


def test_the_allowed_old_commands_still_exist():
    """Keep the allow list from going stale. Renaming a command without updating it
    would let the new name through unseen.
    """
    gone = COMMANDS_PREDATING_THE_CHECK - set(_commands(cli.app))
    assert not gone, f"allowed but no longer implemented: {sorted(gone)}"


# --------------------------------------------------------------------------
# The current values STATUS.md states match the real ones
# --------------------------------------------------------------------------


def test_the_version_in_status_matches_pyproject():
    """A number that moves at every release drifts unless the release touches it.

    It sat at 0.0.9 through two releases. The procedure in AGENTS.md now says to update
    it, but procedures are not always followed.
    """
    import tomllib

    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    want = version["project"]["version"]
    status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
    assert f"**{want}**" in status, f"STATUS.md does not state {want} as the version"


def test_the_migration_head_in_status_matches_the_real_one():
    """alembic check compares the schema with the models, not with the documentation.

    They did drift: after the 0.4.0 migration, STATUS.md still named the 0.3.0 head. The
    value can be read mechanically, so it is.
    """
    import re

    # The annotations are not written consistently (str | ... | None against
    # Union[str, ...], and both quote styles), so only the assigned string is read.
    revisions, downs = set(), set()
    for f in (ROOT / "alembic" / "versions").glob("*.py"):
        text = f.read_text(encoding="utf-8")
        if m := re.search(r'^revision\b[^=]*=\s*["\']([^"\']+)["\']', text, re.M):
            revisions.add(m.group(1))
        if m := re.search(r'^down_revision\b[^=]*=\s*["\']([^"\']+)["\']', text, re.M):
            downs.add(m.group(1))
    heads = revisions - downs
    assert len(heads) == 1, f"the head is not unique: {sorted(heads)}"
    head = heads.pop()
    status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
    assert head in status, f"STATUS.md does not name the current head ({head})"


#: Files that may contain Japanese, because the Japanese is the product rather than a
#: comment: the message catalogues, the ja field of each error code, and the Japanese
#: navigation labels of the documentation site.
JAPANESE_IS_THE_PRODUCT = {
    "src/arkhe/cli_i18n.py",
    "src/arkhe/errors.py",
    "mkdocs.yml",
}


def test_the_code_is_written_in_english():
    """Identifiers, comments and docstrings are English everywhere.

    The reader of the implementation and the reader of the interface are different
    people. The interface speaks both languages through the catalogues; the code speaks
    one, so that anyone who works on it can read all of it.

    Checked mechanically because a rule like this decays one file at a time: a Japanese
    comment added next to Japanese comments looks like it belongs.
    """
    import re

    cjk = re.compile("[" + "".join(
        f"{chr(a)}-{chr(b)}" for a, b in ((0x3040, 0x309f), (0x30a0, 0x30ff),
                                         (0x4e00, 0x9fff))
    ) + "]")
    root = ROOT
    checked = ("src", "tests", "scripts", "alembic", "compose", "clients")
    offenders = []
    for folder in checked:
        for path in sorted((root / folder).rglob("*")):
            if path.suffix not in {".py", ".sh", ".html", ".yml", ".json", ".toml"}:
                continue
            if "__pycache__" in path.parts:
                continue
            rel = str(path.relative_to(root))
            if rel in JAPANESE_IS_THE_PRODUCT or rel.startswith("src/arkhe/api/i18n/"):
                continue
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if cjk.search(line):
                    offenders.append(f"{rel}:{i}")
    assert not offenders, "Japanese in the code:\n  " + "\n  ".join(offenders[:20])
