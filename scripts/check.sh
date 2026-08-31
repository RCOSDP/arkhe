#!/usr/bin/env bash
# check.sh — この版が出せる状態かを確かめる。**唯一の検査手順**である。
#
# もともと .github/workflows/{ci,docs}.yml がやっていたことを、そのままここへ移した。
# **系統を 2 つ持たない**——手元と CI に分かれると、「片方では通る」変更が生まれ、
# やがて誰も赤い側を見なくなる。
#
#   bash scripts/check.sh              # 全部
#   bash scripts/check.sh --no-db      # マイグレーションの往復を飛ばす
#   bash scripts/check.sh --no-docs    # 文書のビルドを飛ばす
#   PGPORT=55433 bash scripts/check.sh 使い捨て PostgreSQL の待ち受けポート
#
# 見るもの:
#   1. lock と pyproject のずれ（uv sync --frozen）
#   2. ruff
#   3. pytest
#   4. マイグレーションを **PostgreSQL で往復**（SQLite は PostgreSQL が弾く形を通す）
#      ＋ alembic check
#   5. OpenAPI を実装から書き出して、コミット済みのものとずれていないか
#   6. mkdocs build --strict
#
# **道具が無い項目は黙って通さず SKIP と出す。**「入っていないから通った」が
# いちばん危ない——緑を見て出したのに、見ていない検査があることになる。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WITH_DB=1; WITH_DOCS=1
while [ $# -gt 0 ]; do
  case "$1" in
    --no-db)   WITH_DB=0;;
    --no-docs) WITH_DOCS=0;;
    -h|--help) sed -n '2,24p' "$0"; exit 0;;
    *) echo "不明な引数: $1" >&2; exit 2;;
  esac; shift
done

PGPORT="${PGPORT:-55432}"
PG_NAME="${PG_NAME:-arkhe-check-pg}"
SKIPPED=0
sec()  { printf '\n\033[1m=== %s ===\033[0m\n' "$*"; }
ok()   { echo "  ✓ $*"; }
skip() { echo "  ~ SKIP: $*"; SKIPPED=$((SKIPPED + 1)); }
die()  { echo "  ✗ $*" >&2; exit 1; }
run()  { "$@" || die "$* が落ちた"; }

command -v uv >/dev/null 2>&1 || die "uv が無い。https://docs.astral.sh/uv/"

sec "1. lock どおりに入れる"
# **lock と pyproject.toml がずれていたらここで落とす。** ずれたまま緑になるほうが困る。
run uv sync --frozen --all-extras
ok "uv sync --frozen"

sec "2. ruff"
run uv run ruff check src tests
ok "ruff"

sec "3. pytest"
run uv run pytest -q
ok "pytest"

sec "4. マイグレーションの往復（PostgreSQL）"
# **デモの DB には当たらない。** 落として作り直す検査なので、消えて困るものに向けない。
pg_down() { docker rm -f "$PG_NAME" >/dev/null 2>&1 || true; }
if [ "$WITH_DB" = 0 ]; then
  skip "--no-db が指定された。**SQLite だけの確認は CI 相当ではない**"
elif ! command -v docker >/dev/null 2>&1; then
  skip "docker が無い。PostgreSQL でのマイグレーション検査を通していない"
else
  trap pg_down EXIT
  pg_down
  docker run -d --rm --name "$PG_NAME" \
    -e POSTGRES_USER=arkhe -e POSTGRES_PASSWORD=arkhe -e POSTGRES_DB=arkhe \
    -p "$PGPORT:5432" postgres:17-alpine >/dev/null || die "PostgreSQL を起動できない"
  up=0
  for _ in $(seq 1 40); do
    docker exec "$PG_NAME" pg_isready -U arkhe >/dev/null 2>&1 && { up=1; break; }
    sleep 1
  done
  [ "$up" = 1 ] || die "PostgreSQL が起動しない（$PG_NAME）"
  export ARKHE_DATABASE_URL="postgresql+psycopg://arkhe:arkhe@localhost:$PGPORT/arkhe"
  export ARKHE_AUTH=apikey
  run uv run alembic upgrade head
  run uv run alembic downgrade base
  run uv run alembic upgrade head
  # **`alembic check` の指摘は本物。** 宣言してあるのに作られない FK をこれが見つける。
  run uv run alembic check
  pg_down; trap - EXIT
  ok "upgrade → downgrade base → upgrade → check"
fi

sec "5. OpenAPI が実装に追随しているか"
# 仕様は実装から起こす。**コミット済みのものがずれていたら、ここで気づく。**
run uv run python scripts/export_openapi.py
if git diff --quiet -- docs/assets/openapi-*.json 2>/dev/null; then
  ok "docs/assets/openapi-*.json は最新"
else
  git diff --stat -- docs/assets/openapi-*.json | sed 's/^/    /'
  die "コミット済みの OpenAPI が実装から遅れている。書き出した結果をコミットする"
fi

sec "6. 文書"
if [ "$WITH_DOCS" = 0 ]; then
  skip "--no-docs が指定された"
else
  # --strict: リンク切れや解決できない参照を、警告で済ませず失敗にする
  run uv run mkdocs build --strict --quiet --site-dir "$(mktemp -d)"
  ok "mkdocs build --strict"
fi

echo
if [ "$SKIPPED" -gt 0 ]; then
  printf '\033[1m✓ 通過（ただし %d 項目 SKIP。出す前にその項目を通すこと）\033[0m\n' "$SKIPPED"
else
  printf '\033[1m✓ 全部通過\033[0m\n'
fi
