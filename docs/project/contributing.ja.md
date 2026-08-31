# 参加する

!!! tip "コードを触るなら"
    リポジトリ直下の [`AGENTS.md`](https://github.com/RCOSDP/arkhe/blob/main/AGENTS.md)
    に手順と、**実際に踏んだ罠**がまとめてある。人にもコーディングエージェントにも
    同じものを渡している。

## 準備

```bash
uv sync --frozen --all-extras   # lock どおりに入れる
uv run pytest -q
uv run ruff check src tests
```

## CI は無い。検査は手元で走る

```bash
bash scripts/check.sh          # 検査ぜんぶ
bash scripts/check.sh --no-db  # docker が無いとき（**同じにはならない**）
```

sync（`--frozen`）→ ruff → pytest → **使い捨ての PostgreSQL を立ててマイグレーションを
往復** → OpenAPI が実装からずれていないか → `mkdocs build --strict`。デモの DB には
当たらない。**道具が無い項目は黙って通さず SKIP と出す**——「入っていないから通った」が
いちばん危ない。

**系統を 2 つ持たないため**にこうしてある。手元と CI に分かれると、「片方では通る」
変更が生まれ、やがて誰も片方を見なくなる。

出す側の 2 本:

```bash
bash scripts/deploy-docs.sh                 # このサイトを gh-pages へ
bash scripts/release.sh vX.Y.Z              # 検査と dist の作成だけ（既定）
bash scripts/release.sh vX.Y.Z --publish    # タグ → push → GitHub のリリース
```

## レビューで見ること

**不変条件が保たれているか。** この設計の多くは拒否でできている
（[壊さないもの](../concepts/invariants.md)）。**コードが守っていたものを規約に
格下げする**変更は差し戻される。

**理由がコードに書いてあるか。** ここでのコメントは *何を* ではなく *なぜ* を書く。
`# カウンタを増やす` は雑音で、`# 衝突は握りつぶさず数える。衝突率の上昇が
名前空間の枯渇を知らせる唯一の合図だから` は読み手が復元できない情報である。

**効く場所で検証したか。** マイグレーションは **PostgreSQL で確認**すること。
SQLite は PostgreSQL が弾くスキーマを通す。開発中に 2 度、この差が実バグを隠した。

## テスト

新しい振る舞いには、それが無いと落ちるテストを付ける。**認可に触るなら否定側も**——
正しい主体が入れたことより、**間違った主体が入れなかったこと**のほうが重要。

テスト名は文になっている（`test_他組織のARKは更新できない`）。**失敗したときに、
例外を投げた関数ではなく壊れた規則の名前が出る**ようにするため。

## 層

```
arkspec/    ARK 仕様の純関数層。stdlib のみ。
domain/     解決・認可・採番・管理。HTTP を知らない。
db/         SQLAlchemy のモデルとリポジトリ。
auth/       3 機構、1 つの Principal。
api/        FastAPI のルータ、管理画面、国際化。
```

`arkspec/` と `domain/resolution.py` が何にも依存しないのは偶然ではない。**フレーム
ワークを丸ごと入れ替えても 97 本のテストが無改造で通った**のはこれのおかげである。
**この性質を保つこと。** 仕様のロジックに DB が要るなら、設計が別のどこかで
間違っている。

## ドキュメント

MkDocs Material、素の Markdown、接尾で対訳（`page.md` が英語、`page.ja.md` が日本語）。
図は Mermaid をコードブロックに書く——**画像を書き出す手順を挟まない。**

```bash
python scripts/export_openapi.py     # API 仕様をコードから作り直す
mkdocs serve
```

生成しているのは API 仕様だけ。**設定とコマンドのページは手で書く**——項目や
コマンドを足したら、2 言語ぶん行を足すこと。忘れると `tests/test_docs.py` が落ちる。
このページには以前「生成している」と書いてあり、そのせいで設定 2 つとコマンド 1 つが
未記載のまま残っていた。

## コミット

変更内容だけでなく、**なぜそれが正解なのか**を書く。将来の読み手が知りたいのは、
あなたが何を分かっていてその判断に至ったか——とくに、答えが奇妙に見えるときに。
