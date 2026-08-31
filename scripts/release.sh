#!/usr/bin/env bash
# release.sh — 版を出す。**唯一の出し方**である。
#
# もともと .github/workflows/release.yml がタグ push を受けてやっていたことを、
# そのままここへ移した。順番も同じで、確かめてから出す。
#
#   bash scripts/release.sh v0.0.9              # 検査と dist の作成だけ（既定）
#   bash scripts/release.sh v0.0.9 --publish    # ＋ タグを打って push し、リリースを作る
#
# **既定が「出さない」**なのは、確かめる作業と出す作業を分けたいからである。
# 確かめるのは安く何度でもできるが、タグと GitHub のリリースはそうではない。
#
# 見るもの:
#   1. 版の一致       タグと pyproject.toml の version
#   2. 変更履歴       その版の節・リンク定義・「未リリース」の比較リンク（日英とも）
#   3. check.sh       検査ぜんぶ
#   4. dist/          sdist と wheel
#   5. --publish      タグ → push → GitHub のリリース（0.x はプレリリース）
#
# 必要なもの: uv、docker（マイグレーションの検査）、gh（--publish のときだけ）
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TAG=""; PUBLISH=""; CHECK_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --publish)         PUBLISH=1;;
    --no-db|--no-docs) CHECK_ARGS+=("$1");;   # check.sh へ渡す
    -h|--help)         sed -n '2,24p' "$0"; exit 0;;
    v*)                TAG="$1";;
    *) echo "不明な引数: $1" >&2; exit 2;;
  esac; shift
done

sec() { printf '\n\033[1m=== %s ===\033[0m\n' "$*"; }
die() { echo "  ✗ $*" >&2; exit 1; }

PKG="$(uv run --no-project python -c \
  'import tomllib;print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')" \
  || die "pyproject.toml の version を読めない"
[ -n "$TAG" ] || TAG="v$PKG"
VER="${TAG#v}"

sec "1. 版の一致（$TAG ↔ pyproject $PKG）"
# **版は pyproject だけで決まる。** ずれたまま出すと「v0.0.2 と名乗る 0.0.1」になる。
[ "$VER" = "$PKG" ] || die "タグ=$VER だが pyproject=$PKG。pyproject.toml を直して uv lock"
echo "  ✓ $VER"

sec "2. 変更履歴に $VER の節があるか（日英）"
# 無いまま出すと、利用者が「何が変わったのか」を調べる先が無くなる。
for f in CHANGELOG.md CHANGELOG.ja.md; do
  grep -qF "## [$VER]" "$f"     || die "$f に '## [$VER]' が無い（未リリースの節に書いたまま？）"
  grep -qF "[$VER]: https" "$f" || die "$f の末尾に [$VER]: のリンク定義が無い"
  # 「未リリース」の比較リンクは**新しい版を起点**にする。置き換え忘れがここで出る。
  grep -qF "compare/v$VER...HEAD" "$f" \
    || die "$f の未リリースのリンクが compare/v$VER...HEAD を指していない"
  echo "  ✓ $f"
done

sec "3. 検査（scripts/check.sh）"
bash scripts/check.sh ${CHECK_ARGS[@]+"${CHECK_ARGS[@]}"} || die "検査が通らない"

sec "4. 配布物を作る"
uv pip install --quiet build || die "build を入れられない"
uv run python -m build >/dev/null || die "python -m build が落ちた"
ls -1 "dist/arkhe-$VER.tar.gz" "dist/arkhe-$VER-py3-none-any.whl" >/dev/null 2>&1 \
  || die "dist に $VER の成果物が無い"
echo "  ✓ dist/arkhe-$VER.tar.gz / arkhe-$VER-py3-none-any.whl"

if [ -z "$PUBLISH" ]; then
  cat <<MSG

✓ 検査を通過（$TAG）。**まだ何も出していない。**

出すなら:
  bash scripts/release.sh $TAG --publish
MSG
  exit 0
fi

sec "5. 出す"
command -v gh >/dev/null 2>&1 || die "gh が無い。https://cli.github.com/"
[ -z "$(git status --porcelain --untracked-files=no)" ] \
  || die "未コミットの変更がある。タグは動かせないので、先にコミットする"
branch="$(git rev-parse --abbrev-ref HEAD)"
git rev-parse "$TAG" >/dev/null 2>&1 && die "$TAG は既にある"

git tag -a "$TAG" -m "release: $TAG"
git push origin "$branch" || die "$branch を送れない"
git push origin "$TAG"    || die "$TAG を送れない"
# 0.x のあいだはプレリリースとして出す（版の意味を誤解させない）。
pre=""; case "$VER" in 0.*) pre="--prerelease";; esac
gh release create "$TAG" dist/"arkhe-$VER"* \
  --title "$TAG" --generate-notes $pre || die "リリースを作れない"

cat <<MSG

✓ 出した: $(gh release view "$TAG" --json url -q .url)

残り:
  bash scripts/deploy-docs.sh          # 変更履歴のページを追随させる
  # weko4 側のサブモジュールポインタを進める
MSG
