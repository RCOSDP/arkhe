#!/usr/bin/env bash
# release.sh - cut a release. This is the only way one is made.
#
# It is what .github/workflows/release.yml used to do on a pushed tag, moved here in the
# same order: check first, then publish.
#
#   bash scripts/release.sh v0.0.9              # check and build dist only (default)
#   bash scripts/release.sh v0.0.9 --publish    # and tag, push, and create the release
#
# The default is not to publish, because checking and publishing are separate jobs.
# Checking is cheap and can be repeated; a tag and a GitHub release are not.
#
# What it looks at:
#   1. the version    the tag against version in pyproject.toml
#   2. the changelog  the section, the link definition and the unreleased compare link,
#                     in both languages
#   3. check.sh       every check
#   4. dist/          the sdist and the wheel
#   5. --publish      tag, push, then the GitHub release (0.x is a prerelease). The
#                     notes come from that version's section of CHANGELOG.md
#
# It needs uv, docker (for the migration check), and gh (only with --publish).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TAG=""; PUBLISH=""; CHECK_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --publish)         PUBLISH=1;;
    --no-db|--no-docs) CHECK_ARGS+=("$1");;   # passed through to check.sh
    -h|--help)         awk 'NR > 1 && !/^#/ { exit } NR > 1' "$0"; exit 0;;
    v*)                TAG="$1";;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac; shift
done

sec() { printf '\n\033[1m=== %s ===\033[0m\n' "$*"; }
die() { echo "  ✗ $*" >&2; exit 1; }

PKG="$(uv run --no-project python -c \
  'import tomllib;print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')" \
  || die "cannot read version from pyproject.toml"
[ -n "$TAG" ] || TAG="v$PKG"
VER="${TAG#v}"

sec "1. the version matches ($TAG against pyproject $PKG)"
# The version is decided by pyproject alone. Released while they disagree, it would be
# a 0.0.1 calling itself v0.0.2.
[ "$VER" = "$PKG" ] || die "tag is $VER but pyproject is $PKG. Fix pyproject.toml and run uv lock"
echo "  ✓ $VER"

sec "2. the changelog has a $VER section, in both languages"
# Released without one, nobody has anywhere to look up what changed.
for f in CHANGELOG.md CHANGELOG.ja.md; do
  grep -qF "## [$VER]" "$f"     || die "$f has no '## [$VER]' (still under the unreleased section?)"
  grep -qF "[$VER]: https" "$f" || die "$f has no [$VER]: link definition at the end"
  # The unreleased compare link starts from the new version. Forgetting to move it
  # shows up here.
  grep -qF "compare/v$VER...HEAD" "$f" \
    || die "the unreleased link in $f does not point at compare/v$VER...HEAD"
  echo "  ✓ $f"
done

sec "3. the checks (scripts/check.sh)"
bash scripts/check.sh ${CHECK_ARGS[@]+"${CHECK_ARGS[@]}"} || die "the checks did not pass"

sec "4. build the distribution"
uv pip install --quiet build || die "cannot install build"
uv run python -m build >/dev/null || die "python -m build failed"
ls -1 "dist/arkhe-$VER.tar.gz" "dist/arkhe-$VER-py3-none-any.whl" >/dev/null 2>&1 \
  || die "dist has no artefacts for $VER"
echo "  ✓ dist/arkhe-$VER.tar.gz / arkhe-$VER-py3-none-any.whl"

if [ -z "$PUBLISH" ]; then
  cat <<MSG

Checks passed ($TAG). Nothing has been published.

To publish:
  bash scripts/release.sh $TAG --publish
MSG
  exit 0
fi

sec "5. publish"
command -v gh >/dev/null 2>&1 || die "gh is not installed. https://cli.github.com/"
[ -z "$(git status --porcelain --untracked-files=no)" ] \
  || die "there are uncommitted changes. A tag cannot be moved, so commit first"
branch="$(git rev-parse --abbrev-ref HEAD)"
git rev-parse "$TAG" >/dev/null 2>&1 && die "$TAG already exists"

git tag -a "$TAG" -m "release: $TAG"
git push origin "$branch" || die "cannot push $branch"
git push origin "$TAG"    || die "cannot push $TAG"
# The release notes come from CHANGELOG.md. --generate-notes lists pull requests, and
# where commits go straight to main that leaves a body of one compare link, which is what
# happened with v0.0.9 and v0.2.0. The content is in the changelog, and the first place
# anyone arriving from the release looks should not be the empty one.
notes="$(mktemp)"
trap 'rm -f "$notes"' EXIT
# The heading line is dropped, since GitHub uses the title for it. The match uses
# index() as a prefix test so that the dots in a version are not read as a pattern.
awk -v ver="$VER" '
  index($0, "## [" ver "]") == 1 { f = 1; next }
  f && index($0, "## [")     == 1 { exit }
  f                               { print }
' CHANGELOG.md > "$notes"
[ -s "$notes" ] || die "cannot cut the $VER section out of CHANGELOG.md"
# The body is English, as everything published is. The Japanese changelog is linked.
prev="$(git describe --tags --abbrev=0 "$TAG^" 2>/dev/null || true)"
{
  echo
  echo "---"
  echo
  echo "[Changelog in Japanese](https://github.com/RCOSDP/arkhe/blob/$TAG/CHANGELOG.ja.md)"
  [ -n "$prev" ] && echo "· **Full Changelog**: https://github.com/RCOSDP/arkhe/compare/$prev...$TAG"
} >> "$notes"

# While it is 0.x it is published as a prerelease, so that the version is not
# misread.
pre=""; case "$VER" in 0.*) pre="--prerelease";; esac
gh release create "$TAG" dist/"arkhe-$VER"* \
  --title "$TAG" --notes-file "$notes" $pre || die "cannot create the release"

cat <<MSG

Published: $(gh release view "$TAG" --json url -q .url)

Left to do:
  bash scripts/deploy-docs.sh          # bring the changelog pages up to date
  # if anything embeds arkhe as a submodule, advance that pointer too
MSG
