# Contributing

## Getting set up

```bash
uv venv --python 3.12 && uv pip install -e '.[app,dev]'
python -m pytest -q
python -m ruff check src tests
```

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

The configuration and CLI pages are generated from the implementation. If you add a
setting or a command, they follow automatically — do not transcribe them by hand.

## Commits

Explain the reasoning, not just the change. A future reader wants to know what you
knew that made this the right answer — especially where the answer looks odd.
