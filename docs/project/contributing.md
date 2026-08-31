# Contributing

!!! tip "Changing the code?"
    [`AGENTS.md`](https://github.com/RCOSDP/arkhe/blob/main/AGENTS.md) in the repository
    root carries the working procedure and **the traps actually hit during development**
    — the same document is handed to people and to coding agents.

## Getting set up

```bash
uv sync --frozen --all-extras   # install exactly what the lock says
uv run pytest -q
uv run ruff check src tests
```

## Run CI locally before you push

```bash
./scripts/ci.sh          # everything CI checks
./scripts/ci.sh --no-db  # without docker — **not the same thing**
```

It mirrors `.github/workflows/ci.yml` and `docs.yml`, down to **starting a disposable
PostgreSQL and round-tripping the migrations** (it never touches the demo database).
Finding out after the push only costs a round trip.

If you are cutting a release, `./scripts/release.sh vX.Y.Z` checks that the tag matches
the version, that the CHANGELOG has that section and its link definition in both
languages, runs the CI equivalent and builds `dist/`. **It does not push.**

## What the review will ask

**Does an invariant still hold?** Most of the design is refusals — see
[Invariants](../concepts/invariants.md). A change that makes one of them merely a
convention rather than something the code enforces will be sent back.

**Is the reasoning in the code?** Comments here say *why*, not *what*. `# increment
the counter` is noise; `# collisions are counted rather than swallowed, because a
rising rate is how a filling namespace announces itself` is the thing a reader cannot
reconstruct.

**Was it verified where it matters?** Migrations must be checked against PostgreSQL.
SQLite accepts schemas PostgreSQL rejects — twice during development, that difference
hid a real bug.

## Tests

New behaviour needs a test that fails without it. For anything touching
authorisation, add the negative case too: the interesting question is not that the
right principal got in, but that the wrong one did not.

Tests read as sentences on purpose — `test_他組織のARKは更新できない` — so a failure
names the rule that broke rather than the function that raised.

## The layers

```
arkspec/    the ARK specification as pure functions. stdlib only.
domain/     resolution, authorisation, minting, administration. Knows nothing of HTTP.
db/         SQLAlchemy models and the repository.
auth/       three mechanisms, one Principal.
api/        FastAPI routers, the admin interface, i18n.
```

`arkspec/` and `domain/resolution.py` depending on nothing is not an accident — it is
what let 97 tests move across a complete framework rewrite untouched. **Keep it that
way.** If specification logic needs a database, the design is wrong somewhere else.

## Documentation

The site is MkDocs Material, plain Markdown, bilingual by suffix: `page.md` is English,
`page.ja.md` is Japanese. Diagrams are Mermaid in a fenced block — no image files to
regenerate.

```bash
python scripts/export_openapi.py     # regenerate the API spec from the code
mkdocs serve
```

Only the API spec is generated. **The configuration and CLI pages are written by
hand** — add a setting or a command and you must add its row, in both languages.
`tests/test_docs.py` fails if you don't; this page used to claim they were generated,
and two settings and one command went undocumented because of it.

## Commits

Explain the reasoning, not just the change. A future reader wants to know what you
knew that made this the right answer — especially where the answer looks odd.
