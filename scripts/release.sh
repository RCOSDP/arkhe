#!/usr/bin/env bash
# リリースをローカルで通す。**`.github/workflows/release.yml` の写し**（＋手順の検査）。
#
# タグを打った後に落ちると、**世に出ている版の検査が赤い**という始末の悪い状態になる。
# 打つ前に同じものを通しておく。ここが緑なら、あとはタグを push するだけ。
#
#   1. 版の一致          タグ（引数）と `pyproject.toml` の version
#   2. CHANGELOG         その版の節が日英ともあるか。**未リリースの節に足していないか**
#   3. uv sync --frozen  版を上げて `uv lock` を忘れるとここで落ちる
#   4. ruff / pytest
#   5. マイグレーションの往復（PostgreSQL）＋ `alembic check`
#   6. mkdocs --strict
#   7. `python -m build` で dist/ を作る
#
# 使い方:
#   ./scripts/release.sh              pyproject の版で通す（リハーサル）
#   ./scripts/release.sh v0.0.9       その版で通す。**ずれていれば 1 で落ちる**
#   ./scripts/release.sh v0.0.9 --tag 通ったら注釈つきタグを**手元に**作る（push はしない）
#
# **push はしない。** 出したものは取り消せないので、最後の一手は人が打つ。
set -euo pipefail
cd "$(dirname "$0")/.."

TAG=""; MAKE_TAG=0; CI_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --tag)               MAKE_TAG=1;;
    --no-db|--no-docs)   CI_ARGS+=("$1");;   # ci.sh へそのまま渡す
    -h|--help)           sed -n '2,22p' "$0"; exit 0;;
    v*)                  TAG="$1";;
    *) echo "不明な引数: $1" >&2; exit 2;;
  esac; shift
done

step() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

PKG="$(uv run --no-project python -c 'import tomllib;print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')"
[ -n "$TAG" ] || TAG="v$PKG"
VER="${TAG#v}"

step "版の一致（$TAG ↔ pyproject $PKG）"
# **版は pyproject だけで決まる。** ずれたまま出ると「v0.0.2 と名乗る 0.0.1」になる。
if [ "$VER" != "$PKG" ]; then
  echo "タグ=$VER だが pyproject=$PKG。先に pyproject.toml を直して uv lock" >&2; exit 1
fi

step "CHANGELOG に $VER の節があるか（日英）"
missing=0
for f in CHANGELOG.md CHANGELOG.ja.md; do
  grep -qF "## [$VER]" "$f" || { echo "  $f に '## [$VER]' が無い" >&2; missing=1; }
  grep -qF "[$VER]: https" "$f" || { echo "  $f の末尾に [$VER]: のリンク定義が無い" >&2; missing=1; }
  # 「未リリース」の比較リンクは**新しい版を起点**にする。置き換え忘れがここで出る。
  grep -qF "compare/v$VER...HEAD" "$f" \
    || { echo "  $f の未リリースのリンクが compare/v$VER...HEAD を指していない" >&2; missing=1; }
done
[ "$missing" = 0 ] || {
  echo "**未リリースの節に書いたまま**になっていないか確認する（リリース済みの節には足さない）" >&2
  exit 1; }

step "CI 相当（sync/ruff/pytest/マイグレーション/文書）"
./scripts/ci.sh ${CI_ARGS[@]+"${CI_ARGS[@]}"}

step "配布物を作る"
uv pip install --quiet build
rm -rf dist/"arkhe-$VER"* 2>/dev/null || true
uv run python -m build
ls -1 dist/ | grep -F "$VER" || { echo "dist に $VER の成果物が無い" >&2; exit 1; }

if [ "$MAKE_TAG" = 1 ]; then
  step "タグを手元に作る（push はしない）"
  git tag -a "$TAG" -m "release: $TAG"
  echo "  作成: $TAG"
fi

cat <<MSG

✓ リリースの検査を通過（$TAG）

残りは人の手で:
  git tag -a $TAG -m "release: $TAG"      # --tag を付けていれば済んでいる
  git push origin main && git push origin $TAG
  # release.yml が同じ検査をもう一度回し、dist/* を添えて GitHub Release を作る
  # 0.x のあいだはプレリリースとして出る
  # そのあと weko4 側のサブモジュールポインタを進める
MSG
