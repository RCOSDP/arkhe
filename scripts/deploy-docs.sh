#!/usr/bin/env bash
# deploy-docs.sh - publish the documentation site to gh-pages. This is the only way it
# is published.
#
# It is what .github/workflows/docs.yml used to do, moved here. GitHub Pages serves the
# gh-pages branch directly (Settings, Pages, Deploy from a branch, gh-pages / root).
# gh-pages is generated, so nobody edits it by hand; this script is its only writer.
#
#   bash scripts/deploy-docs.sh              # check, build, publish
#   bash scripts/deploy-docs.sh --dry-run    # check and build only, without pushing
#
# Two things are checked first. Both exist to stop content being on the site that cannot
# be traced in the repository, which is what checkout did under CI.
#   * no uncommitted changes to tracked files (ALLOW_DIRTY=1 skips it)
#   * HEAD has been pushed to origin (a warning if it has not)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DRY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1;;
    -h|--help) awk 'NR > 1 && !/^#/ { exit } NR > 1' "$0"; exit 0;;
    # A misspelt flag is not passed over silently. While it was, typing --dryrun
    # force-pushed to gh-pages without a word: publishing something meant to be held
    # back is the worst outcome. Handled as in check.sh and release.sh.
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac; shift
done

sec() { printf '\n\033[1m=== %s ===\033[0m\n' "$*"; }
die() { echo "  ✗ $*" >&2; exit 1; }

command -v uv >/dev/null 2>&1 || die "uv is not installed"

sec "1. is it in a state to publish"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  if [ "${ALLOW_DIRTY:-}" = "1" ]; then
    echo "  ! publishing with uncommitted changes (ALLOW_DIRTY=1)"
  else
    git status --short --untracked-files=no | sed 's/^/    /'
    die "there are uncommitted changes. Commit first, or pass ALLOW_DIRTY=1"
  fi
fi
branch="$(git rev-parse --abbrev-ref HEAD)"
git fetch --quiet origin "$branch" 2>/dev/null
remote="$(git rev-parse "origin/$branch" 2>/dev/null || true)"
if [ -n "$remote" ] && [ "$(git rev-parse HEAD)" != "$remote" ]; then
  echo "  ! HEAD differs from origin/$branch. The site could carry content that cannot be traced"
fi
echo "  ✓ $branch $(git rev-parse --short HEAD)"

sec "2. generate the specification from the implementation"
# The API document is generated. It is rebuilt before publishing so that a fix cannot
# be left out of what goes out.
uv run python scripts/export_openapi.py || die "cannot write the OpenAPI documents"
if ! git diff --quiet -- docs/assets/openapi-*.json 2>/dev/null; then
  die "the OpenAPI documents differ from what is committed. Commit them first"
fi

sec "3. checks"
# A broken link is not published. --strict turns warnings into failures.
# Broken anchors within a page are checked too: mkdocs logs those at INFO, so --strict
# does not stop for them, while to a reader they are the same broken link.
out="$(uv run mkdocs build --strict --site-dir "$(mktemp -d)" 2>&1)" \
  || { echo "$out" | tail -20 | sed 's/^/    /'; die "mkdocs build --strict failed"; }
if echo "$out" | grep -q "there is no such anchor"; then
  echo "$out" | grep "there is no such anchor" | sed 's/^/    /'
  die "a link within a page is broken"
fi
echo "  ✓ mkdocs build --strict, including anchors"

if [ -n "$DRY" ]; then
  echo
  printf '\033[1m✓ --dry-run: stopping here. Nothing was published\033[0m\n'
  exit 0
fi

sec "4. publish to gh-pages"
# gh-deploy builds site/ and force-pushes it to gh-pages. No history is kept there;
# it is generated, and the source is what anyone follows.
uv run mkdocs gh-deploy --force --message "docs: publish $(git rev-parse --short HEAD)" \
  || die "gh-deploy failed"

cat <<MSG

Published.

  https://rcosdp.github.io/arkhe/      (Japanese is under /ja/)

It takes up to a minute to appear. If it does not, check that Settings, Pages is set to
Deploy from a branch, gh-pages / (root).
MSG
