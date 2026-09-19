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
往復** → **通しの検査**（本番と同じ形に建てて HTTP で叩く）→ OpenAPI が実装から
ずれていないか → `mkdocs build --strict`。デモの DB には
当たらない。**道具が無い項目は黙って通さず SKIP と出す**——「入っていないから通った」が
いちばん危ない。

**系統を 2 つ持たないため**にこうしてある。手元と CI に分かれると、「片方では通る」
変更が生まれ、やがて誰も片方を見なくなる。

```bash
uv run pytest -m e2e           # 通しの検査だけ
```

素の `pytest` からは外してある——25 秒ほどかかるからで、docker で PostgreSQL を立て、
**minter と resolver を `uvicorn` で建て**、台帳を **CLI で組み**、**素の HTTP** で
叩く。ほかの試験は `TestClient` で app を直に呼び、SQLite の上で、認証を差し替えて
いる——**ここで見るのは部品ではなく、組み上がった形である。**

台帳を組むのは `scripts/seed_e2e.py` で、**手で確かめるときも同じものが使える**:

```bash
uv run python scripts/seed_e2e.py --migrate --arks 500
```

NAAN・組織・主体と鍵・合言葉を作り、**状態の混ざった ARK**（公開・公開前・保留・
墓碑・修飾子つき・取り下げ済み）を入れて、鍵を刷って見せる。**検査がこれを呼ぶので、
この道具だけが古くなることはない。**

出す側の 2 本:

```bash
bash scripts/deploy-docs.sh                 # このサイトを gh-pages へ
bash scripts/release.sh vX.Y.Z              # 検査と dist の作成だけ（既定）
bash scripts/release.sh vX.Y.Z --publish    # タグ → push → GitHub のリリース
```

**検査ではない**ものが 1 つ。

```bash
python scripts/bench.py http://127.0.0.1:8000/ark:99999/x9tn1qkq2g7 -n 3000 -c 8
```

`check.sh` からは呼ばない。負荷測定は時間がかかるうえ、結果が機械とその日の状態に
左右されるので、**緑と赤で語れない**。**自分の数字**を取るための道具である
（[デプロイ](../guides/deployment.md#規模の見積もり)に載っているのは、ある 1 台の値）。

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

テスト名は文になっている（`test_m3_another_organisations_ark_cannot_be_updated`）。
**失敗したときに、例外を投げた関数ではなく壊れた規則の名前が出る**ようにするため。

**コードは英語で書く**——識別子・コメント・docstring とも。日本語が残るのは
多言語カタログ（`api/i18n/`・`cli_i18n.py`・`errors.py` の `ja`）だけで、
あれは日本語の画面そのものである。文書は日英の両方を保つ。

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
