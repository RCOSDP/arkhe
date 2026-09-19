# Contributing

!!! tip "Changing the code?"
    [`AGENTS.md`](https://github.com/RCOSDP/arkhe/blob/main/AGENTS.md) in the repository
    root carries the working procedure and **the traps actually hit during development**
    — the same document is handed to people and to coding agents.

## Getting set up

```bash
uv sync --frozen --all-extras   # install exactly what the lock says
uv run pytest -q
uv run ruff check src tests clients
```

## There is no CI. The checks run on your machine

```bash
bash scripts/check.sh          # every check
bash scripts/check.sh --no-db  # without docker — **not the same thing**
```

Sync (`--frozen`) → ruff → pytest → **a disposable PostgreSQL with the migrations
round-tripped** → **the end-to-end check** (built in the production shape and driven over
HTTP) → the OpenAPI spec still matching the implementation → `mkdocs build --strict`. It never touches the demo database, and **a check whose tooling is missing
prints SKIP rather than passing quietly** — "it passed because it wasn't installed" is
the dangerous outcome.

**One system, not two.** Split between a laptop and CI, a change that "passes on one
side" appears, and before long nobody looks at the other side.

```bash
uv run pytest -m e2e           # the end-to-end check on its own
```

It is deselected from a plain `pytest` run because it takes about 25 seconds: it starts
PostgreSQL in docker, brings up **a minter and a resolver with `uvicorn`**, builds the
ledger **through the CLI**, and drives the result over **plain HTTP**. The rest of the
suite calls the app directly with `TestClient`, on SQLite, with authentication
substituted — **what gets checked here is the assembled shape, not the parts.**

The ledger is built by `scripts/seed_e2e.py`, and **the same thing serves for checking by
hand**:

```bash
uv run python scripts/seed_e2e.py --migrate --arks 500
```

It creates the NAANs, organisations, principals and their keys and password, fills the
ledger with **ARKs in mixed states** (published, reserved, held, tombstoned, qualified,
withdrawn) and prints the credentials. **The suite calls it, so it cannot go stale on its
own.**

Two more, for publishing:

```bash
bash scripts/deploy-docs.sh                 # this site, to gh-pages
bash scripts/release.sh vX.Y.Z              # checks and dist/ only (the default)
bash scripts/release.sh vX.Y.Z --publish    # tag, push, GitHub release
```

And one that is **not** a check:

```bash
python scripts/bench.py http://127.0.0.1:8000/ark:99999/x9tn1qkq2g7 -n 3000 -c 8
```

`check.sh` does not call it. A benchmark takes time and its result depends on the machine
and on what else that machine is doing, so it cannot be spoken about in green and red.
It is there to get **your own numbers**; the ones in
[Deployment](../guides/deployment.md#sizing) are from one machine.

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

Tests read as sentences on purpose — `test_m3_another_organisations_ark_cannot_be_updated`
— so a failure names the rule that broke rather than the function that raised.

The code is written in English: identifiers, comments and docstrings alike. Japanese
remains only in the message catalogues (`api/i18n/`, `cli_i18n.py`, and the `ja` field in
`errors.py`), which are the Japanese interface itself. The documentation keeps both
languages.

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
