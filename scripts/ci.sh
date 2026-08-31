#!/usr/bin/env bash
# CI をローカルで回す。**`.github/workflows/ci.yml` と `docs.yml` の写し。**
#
# なぜ写しを持つのか: 落ちるのが push の後だと、直すのに往復が要る。**同じ検査を
# 手元で通してから出す**ためのもの。片方だけ直すとずれるので、ワークフローを触ったら
# ここも触ること（ずれていないかは、この 2 つを並べて読めば分かる程度に短くしてある）。
#
#   1. uv sync --frozen        lock と pyproject のずれをここで落とす
#   2. ruff check
#   3. pytest
#   4. マイグレーションを **PostgreSQL で往復**（SQLite は PostgreSQL が弾く形を通す）
#   5. OpenAPI を実装から書き出して mkdocs --strict
#
# 使い方:
#   ./scripts/ci.sh              全部
#   ./scripts/ci.sh --no-db      docker が無いとき（**4 を飛ばす＝CI と同じにはならない**）
#   ./scripts/ci.sh --no-docs    5 を飛ばす
#   PGPORT=55433 ./scripts/ci.sh 使い捨て PostgreSQL の待ち受けポートを変える
set -euo pipefail
cd "$(dirname "$0")/.."

WITH_DB=1; WITH_DOCS=1
while [ $# -gt 0 ]; do
  case "$1" in
    --no-db)   WITH_DB=0;;
    --no-docs) WITH_DOCS=0;;
    -h|--help) sed -n '2,22p' "$0"; exit 0;;
    *) echo "不明な引数: $1" >&2; exit 2;;
  esac; shift
done

PGPORT="${PGPORT:-55432}"
PG_NAME="${PG_NAME:-arkhe-ci-pg}"
step() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- 使い捨ての DB
# **デモの DB は使わない。** 落として作り直す検査なので、消えて困るものに当てない。
pg_up() {
  docker rm -f "$PG_NAME" >/dev/null 2>&1 || true
  docker run -d --rm --name "$PG_NAME" \
    -e POSTGRES_USER=arkhe -e POSTGRES_PASSWORD=arkhe -e POSTGRES_DB=arkhe \
    -p "$PGPORT:5432" postgres:17-alpine >/dev/null
  for _ in $(seq 1 40); do
    docker exec "$PG_NAME" pg_isready -U arkhe >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "PostgreSQL が起動しない（$PG_NAME）" >&2; return 1
}
pg_down() { docker rm -f "$PG_NAME" >/dev/null 2>&1 || true; }

step "uv sync --frozen（lock どおりに入れる）"
uv sync --frozen --all-extras

step "ruff"
uv run ruff check src tests

step "pytest"
uv run pytest -q

if [ "$WITH_DB" = 1 ]; then
  step "マイグレーションの往復（PostgreSQL 17）"
  trap pg_down EXIT
  pg_up
  export ARKHE_DATABASE_URL="postgresql+psycopg://arkhe:arkhe@localhost:$PGPORT/arkhe"
  export ARKHE_AUTH=apikey
  uv run alembic upgrade head
  uv run alembic downgrade base
  uv run alembic upgrade head
  # **`alembic check` の指摘は本物。** 宣言してあるのに作られない FK を、これが見つける。
  uv run alembic check
  pg_down
  trap - EXIT
else
  echo "  （--no-db: マイグレーションの検査を飛ばした。CI と同じではない）" >&2
fi

if [ "$WITH_DOCS" = 1 ]; then
  step "OpenAPI の書き出しと mkdocs --strict"
  uv run python scripts/export_openapi.py
  uv run mkdocs build --strict
  # 書き出した仕様が既存と違えば、**コミット済みの API 仕様が実装から遅れている**。
  if ! git diff --quiet -- docs/assets/openapi-*.json 2>/dev/null; then
    echo "  ⚠ docs/assets/openapi-*.json が更新された。実装に追随させるならコミットする" >&2
  fi
fi

printf '\n\033[1m✓ CI 相当の検査を通過\033[0m\n'
