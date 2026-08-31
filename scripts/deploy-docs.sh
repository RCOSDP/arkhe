#!/usr/bin/env bash
# deploy-docs.sh — ドキュメントサイトを gh-pages へ出す。**唯一の公開手順**である。
#
# もともと .github/workflows/docs.yml がやっていたことを、そのままここへ移した。
# GitHub Pages は gh-pages ブランチを直接配信する
# （Settings → Pages → Deploy from a branch → gh-pages / root）。
# **gh-pages は生成物**なので手で触らない。書き手はこのスクリプトだけ。
#
#   bash scripts/deploy-docs.sh              # 検査 → ビルド → 公開
#   bash scripts/deploy-docs.sh --dry-run    # 検査とビルドだけ（push しない）
#
# 出す前に 2 つ確かめる。どちらも「**サイトに在るのにリポジトリで追えない内容**」を
# 防ぐためのもので、CI では checkout がその役をしていた。
#   * 追跡ファイルに未コミットの変更が無いこと（ALLOW_DIRTY=1 で外せる）
#   * HEAD が origin に押されていること（押されていなければ警告）
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DRY=""
[ "${1:-}" = "--dry-run" ] && DRY=1

sec() { printf '\n\033[1m=== %s ===\033[0m\n' "$*"; }
die() { echo "  ✗ $*" >&2; exit 1; }

command -v uv >/dev/null 2>&1 || die "uv が無い"

sec "1. 出せる状態か"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  if [ "${ALLOW_DIRTY:-}" = "1" ]; then
    echo "  ! 未コミットの変更があるまま出す（ALLOW_DIRTY=1）"
  else
    git status --short --untracked-files=no | sed 's/^/    /'
    die "未コミットの変更がある。先にコミットするか ALLOW_DIRTY=1 を付ける"
  fi
fi
branch="$(git rev-parse --abbrev-ref HEAD)"
git fetch --quiet origin "$branch" 2>/dev/null
remote="$(git rev-parse "origin/$branch" 2>/dev/null || true)"
if [ -n "$remote" ] && [ "$(git rev-parse HEAD)" != "$remote" ]; then
  echo "  ! HEAD が origin/$branch と違う。サイトにだけ在って追えない内容になりうる"
fi
echo "  ✓ $branch $(git rev-parse --short HEAD)"

sec "2. 仕様を実装から起こす"
# API 仕様は生成物。**直したのに公開が追随しない**ことがないよう、出す前に必ず作り直す。
uv run python scripts/export_openapi.py || die "OpenAPI を書き出せない"
if ! git diff --quiet -- docs/assets/openapi-*.json 2>/dev/null; then
  die "書き出した OpenAPI がコミット済みと違う。先にコミットする"
fi

sec "3. 検査"
# **リンク切れを公開しない。** --strict は警告を失敗にする。
uv run mkdocs build --strict --quiet --site-dir "$(mktemp -d)" || die "mkdocs build --strict が落ちた"
echo "  ✓ mkdocs build --strict"

if [ -n "$DRY" ]; then
  echo
  printf '\033[1m✓ --dry-run: ここまで。公開はしていない\033[0m\n'
  exit 0
fi

sec "4. gh-pages へ出す"
# gh-deploy は site/ を作って gh-pages に force push する。**履歴は残らない**
# （生成物なので、追うのはソースの側でよい）。
uv run mkdocs gh-deploy --force --message "docs: $(git rev-parse --short HEAD) を公開" \
  || die "gh-deploy が落ちた"

cat <<MSG

✓ 公開した

  https://rcosdp.github.io/arkhe/      （日本語は /ja/）

反映まで数十秒かかる。出ないときは Settings → Pages が
**Deploy from a branch → gh-pages / (root)** になっているか見る。
MSG
