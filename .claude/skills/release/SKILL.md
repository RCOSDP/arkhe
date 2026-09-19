---
name: release
description: arkhe の版を出す。版・変更履歴（日英）・STATUS・OpenAPI を揃え、release.sh で検査してから公開し、docs と weko4 のサブモジュールまで追随させる。「リリースして」「vX.Y.Z を出して」のときに使う。
---

# 版を出す

**`AGENTS.md` の手順が正。** ここはそれを実行に移すための覚え書きで、**踏んだ罠**を
添えてある。手順そのものが変わったら、先に `AGENTS.md` を直す。

## 版を決める

`0.x` のあいだは **MINOR が破壊的変更を運ぶ**（プレリリースとして出る）。

| 変えたもの | 版 |
| --- | --- |
| 振る舞いの追加・設定の追加 | MINOR（`0.9.0` → `0.10.0`） |
| 修正だけ・文書だけ | PATCH（`0.9.0` → `0.9.1`） |
| 不変条件を弱める | MINOR ＋ `BREAKING CHANGE:` を本文に |

**文書だけの修正でも、間違っていたことは利用者に関わる。** 黙って直さず、変更履歴に書く。

## 手順

```bash
# 1. 版
sed -i 's/^version = "OLD"$/version = "NEW"/' pyproject.toml && uv lock

# 2. 変更履歴（日英）——下の「罠」を読んでから
# 3. STATUS.md の版と日付
# 4. OpenAPI は版が埋まっている
uv run python scripts/export_openapi.py

git add -A && bash scripts/check.sh          # ここまでで緑にする
bash scripts/release.sh vNEW                 # 検査だけ。**まだ出ない**
git commit -F - <<'MSG'
release: NEW
…なぜこの版なのかを本文に…
MSG
bash scripts/release.sh vNEW --publish       # タグ → push → GitHub のリリース
bash scripts/deploy-docs.sh                  # 変更履歴のページを追随させる
```

最後に **weko4 のサブモジュールを進める**（`../` 側で `git add arkhe`、`STATUS.md`
76 行目の版表記も）。**WEKO から見て何が効くか**をコミット本文に書く——arkhe の
変更履歴をそのまま写さない。

## 罠

**変更履歴の節は `[未リリース]` の**下**に作る。** `### 追加` を検索して差し込むと、
**リリース済みの節に入る**（2 回やった）。`[未リリース]` の見出しを起点にする。

**日英とも直す。** 末尾のリンク定義（`[NEW]: …/releases/tag/vNEW`）と、
`[未リリース]` の比較リンク（`compare/vNEW...HEAD`）も。`release.sh` が検査する。

**`STATUS.md` を同じコミットに入れる。** 0.1.0 と 0.2.0 で触らずに出したため、
「版 0.0.9」のまま 2 版据え置きになった。**版と head は検査が見ている**
（`tests/test_docs.py`）ので、忘れれば落ちる。

**`check.sh` の OpenAPI 検査は HEAD と比べる。** 未コミットのうちは必ず落ちる
——**中身の問題ではない**。コミットしてから通す。

**リリースノートは `CHANGELOG.md` から起きる。** `--generate-notes` は使わない
（PR を並べるので、main へ直接コミットするこの体系では空になる）。

## 出した後に間違いに気づいたら

**リリース本文は動かせる**（タグと違って）。`gh release edit vX --notes-file …` で
差し替え、`deploy-docs.sh` も回し直す。**その版に入っていたものの記載漏れなら、
出した節に足してよい**——新しい変更の追記ではないので。
