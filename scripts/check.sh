#!/usr/bin/env bash
# check.sh - decide whether this version is in a state to be released. It is the only
# set of checks there is.
#
# It is what .github/workflows/{ci,docs}.yml used to do, moved here. There is one system
# rather than two: split between a laptop and CI, a change appears that passes on one
# side, and before long nobody looks at the other.
#
#   bash scripts/check.sh              # everything
#   bash scripts/check.sh --no-db      # skip the migration round trip
#   bash scripts/check.sh --no-docs    # skip building the documentation
#   PGPORT=55433 bash scripts/check.sh # the port the throwaway PostgreSQL listens on
#
# What it looks at:
#   1. the lock file against pyproject (uv sync --frozen)
#   2. ruff
#   3. pytest, for the server and for the Python client in clients/python
#   4. the migrations, round-tripped on PostgreSQL, since SQLite accepts schemas
#      PostgreSQL refuses, plus alembic check
#   5. the end-to-end suite: built in the production shape (uvicorn in two roles with
#      PostgreSQL) and driven over HTTP
#   6. the OpenAPI documents, written from the implementation and compared with what is
#      committed
#   7. mkdocs build --strict, which also fails on a broken anchor within a page
#
# A check whose tooling is missing prints SKIP rather than passing quietly. "It passed
# because it was not installed" is the dangerous outcome: the release goes out on a green
# result that did not include it.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WITH_DB=1; WITH_DOCS=1
while [ $# -gt 0 ]; do
  case "$1" in
    --no-db)   WITH_DB=0;;
    --no-docs) WITH_DOCS=0;;
    -h|--help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "$0"; exit 0;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac; shift
done

PGPORT="${PGPORT:-55432}"
PG_NAME="${PG_NAME:-arkhe-check-pg}"
SKIPPED=0
sec()  { printf '\n\033[1m=== %s ===\033[0m\n' "$*"; }
ok()   { echo "  ✓ $*"; }
skip() { echo "  ~ SKIP: $*"; SKIPPED=$((SKIPPED + 1)); }
die()  { echo "  ✗ $*" >&2; exit 1; }
run()  { "$@" || die "$* failed"; }

command -v uv >/dev/null 2>&1 || die "uv is not installed. https://docs.astral.sh/uv/"

sec "1. install exactly what the lock file says"
# If the lock file and pyproject.toml disagree, it stops here. Passing while they
# disagree is the worse outcome.
run uv sync --frozen --all-extras
ok "uv sync --frozen"

sec "2. ruff"
run uv run ruff check src tests clients
ok "ruff"

sec "3. pytest (the server, and the Python client)"
run uv run pytest -q
ok "pytest"

sec "4. the migrations, round-tripped on PostgreSQL"
# It never touches the demonstration database: this check drops and recreates, so it
# is not pointed at anything whose loss would matter.
pg_down() { docker rm -f "$PG_NAME" >/dev/null 2>&1 || true; }
if [ "$WITH_DB" = 0 ]; then
  skip "--no-db was given. Checking on SQLite alone is not the same check"
elif ! command -v docker >/dev/null 2>&1; then
  skip "no docker, so the migrations were not checked on PostgreSQL"
else
  trap pg_down EXIT
  pg_down
  docker run -d --rm --name "$PG_NAME" \
    -e POSTGRES_USER=arkhe -e POSTGRES_PASSWORD=arkhe -e POSTGRES_DB=arkhe \
    -p "$PGPORT:5432" postgres:17-alpine >/dev/null || die "cannot start PostgreSQL"
  up=0
  for _ in $(seq 1 40); do
    docker exec "$PG_NAME" pg_isready -U arkhe >/dev/null 2>&1 && { up=1; break; }
    sleep 1
  done
  [ "$up" = 1 ] || die "PostgreSQL never came up ($PG_NAME)"
  export ARKHE_DATABASE_URL="postgresql+psycopg://arkhe:arkhe@localhost:$PGPORT/arkhe"
  export ARKHE_AUTH=apikey
  run uv run alembic upgrade head
  run uv run alembic downgrade base
  run uv run alembic upgrade head
  # What alembic check reports is real: it is what found a foreign key that was
  # declared and never created.
  run uv run alembic check
  pg_down; trap - EXIT
  ok "upgrade → downgrade base → upgrade → check"
fi

sec "5. the end-to-end suite (uvicorn in two roles, with PostgreSQL)"
# This catches what passes through the fast net: whether the app can be built as a
# factory, whether the credential the CLI printed reaches the ledger the CLI built, and
# whether a resolver stays off the write database. It starts its own throwaway
# PostgreSQL, inside a pytest fixture.
if [ "$WITH_DB" = 0 ]; then
  skip "--no-db was given, so the end-to-end suite did not run"
elif ! command -v docker >/dev/null 2>&1; then
  skip "no docker, so the end-to-end suite did not run"
else
  run uv run pytest -q -m e2e
  ok "the end-to-end suite"
fi

sec "6. the OpenAPI documents follow the implementation"
# The specification is generated from the implementation, and a committed copy that
# has drifted is noticed here.
run uv run python scripts/export_openapi.py
if git diff --quiet -- docs/assets/openapi-*.json 2>/dev/null; then
  ok "docs/assets/openapi-*.json is up to date"
else
  git diff --stat -- docs/assets/openapi-*.json | sed 's/^/    /'
  die "the committed OpenAPI documents are behind the implementation. Commit what was written"
fi

sec "7. documentation"
if [ "$WITH_DOCS" = 0 ]; then
  skip "--no-docs was given"
else
  # --strict turns a broken link or an unresolvable reference into a failure rather
  # than a warning. Broken anchors within a page are caught as well: mkdocs logs those
  # at INFO, so --strict does not stop for them, and renaming a heading quietly kills
  # every link pointing at it. One of them had died.
  out="$(uv run mkdocs build --strict --site-dir "$(mktemp -d)" 2>&1)" \
    || { echo "$out" | tail -20 | sed 's/^/    /'; die "mkdocs build --strict failed"; }
  if echo "$out" | grep -q "there is no such anchor"; then
    echo "$out" | grep "there is no such anchor" | sed 's/^/    /'
    die "a link within a page is broken"
  fi
  ok "mkdocs build --strict, including anchors"
fi

echo
if [ "$SKIPPED" -gt 0 ]; then
  printf '\033[1m✓ passed, with %d skipped. Run those before releasing\033[0m\n' "$SKIPPED"
else
  printf '\033[1m✓ everything passed\033[0m\n'
fi
