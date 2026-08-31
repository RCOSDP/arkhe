# AGENTS.md

このリポジトリを改修するときの手引き。**人にも、コーディングエージェントにも同じ
ものを渡す**——片方だけの決まりを作ると、もう片方が破る。

設計の意図そのものは[不変条件](docs/concepts/invariants.md)と
[Contributing](docs/project/contributing.md) にある。ここに書くのは**手順と、
実際に踏んだ罠**。

**今どこまで来ていて何が無いかは [STATUS.md](STATUS.md)。** 版・テスト数・分かっている穴は
そちらだけに書く（両方に書くと必ず片方が古くなる）。

---

## 1. 何をしているシステムか

ARK 識別子の払い出しと解決。**一度配った名前が、別のものを指すようにならない**
——設計の大半はこの 1 つの約束から出てくる拒否である。

だから、この基盤で最も避けたい失敗は「動かないこと」ではなく、**間違ったまま
静かに動き続けること**。以下の手順はほぼすべてそのためにある。

## 2. 手を動かす前に

```bash
uv sync --frozen --all-extras     # lock どおりに入れる
uv run pytest -q                  # 全部通ること（件数は STATUS.md）
uv run ruff check src tests
```

`--frozen` は lock と `pyproject.toml` がずれていたら落ちる。**依存を足したら
`uv lock` を実行する**（忘れると `check.sh` で落ちる。それが狙い）。

### CI は無い。検査も公開も手元で走る

```bash
bash scripts/check.sh          # 検査ぜんぶ
bash scripts/deploy-docs.sh    # ドキュメントサイトを gh-pages へ
bash scripts/release.sh vX.Y.Z # 版を出す（--publish を付けたときだけ実際に出る）
```

**系統は 1 つにする。** 手元と CI の 2 系統があると「片方では通る」変更が生まれ、
やがて誰も片方を見なくなる。GitHub Actions は置いていない——`.github/` に残して
あるのは issue と PR のテンプレート、そして依存の更新（Dependabot）だけ。

`check.sh` は sync（`--frozen`）→ ruff → pytest → **使い捨ての PostgreSQL を立てて
マイグレーションを往復**（デモの DB には当たらない）→ OpenAPI のずれ → `mkdocs --strict`。
**道具が無い項目は黙って通さず SKIP と出す**——「入っていないから通った」がいちばん危ない。

## 3. 地図

まずリポジトリ全体。**どこに何があり、どれが生成物か。**

```
src/arkhe/     実装。層の説明は下
tests/         ファイル名が対象を表す
alembic/       マイグレーション。**PostgreSQL で検証する**
docs/          MkDocs。`page.md` が英語、`page.ja.md` が日本語
compose/oidc/  Keycloak つきの体験環境。**見本であって手本ではない**
scripts/       check.sh / deploy-docs.sh / release.sh（**CI の代わり**）、export_openapi.py
.github/       issue と PR のテンプレート、Dependabot。**ワークフローは持たない**
AGENTS.md      これ。手順と罠
STATUS.md      現在地と、分かっている穴
CHANGELOG{,.ja}.md  版ごとの変更。**未リリースの節に足す**
site/ dist/ db.sqlite3   生成物。**すべて .gitignore 済み**
```

そして実装の層。

```
arkspec/    ARK 仕様を純粋な関数で。**stdlib しか import しない**
domain/     解決・認可・採番・管理・一覧の絞り込み。HTTP を知らない
db/         SQLAlchemy のモデル
auth/       3 つの機構、1 つの Principal
api/        FastAPI のルータ、管理画面、i18n
cli.py      運用コマンド。**画面と同じ domain を呼ぶ**
```

`arkspec/` と `domain/resolution.py` が何にも依存しないのは偶然ではない
——フレームワークを丸ごと入れ替えたときに 97 件のテストが無傷で移れた理由が
これ。**仕様のロジックが DB を必要としたら、設計がどこか間違っている。**

### 画面と CLI に差を作らない

`cli.py` の冒頭に書いてあるとおり、**CLI にしかできないこと・画面にしかできない
ことを作らない**。実際に破れていた例が `ark list` で、画面にはあったが CLI に
無かった。絞り込みは `domain/queries.py` に置いて両方が同じ式を通る。

**到達範囲の判定を 2 か所に書かない。** 片方だけ直したときに、画面には出ない
ものが CLI には出る——そして気づくのは、見えてはいけないものが見えた後になる。

### 文言は画面ごとのファイルに、日本語と英語を並べて足す

`api/i18n/` は画面で分けてある（`_shell` `_ledger` `_clients` `_arks` `_signin`
`_audit`）。**言語で分けていないのは、対を離すと片方だけ足したことが差分に
出ないから**——起動時の検査は最後の砦であって、最初の砦ではない。訳文に
`` ` `` や `**` を書かないこと（そのまま画面に出る。テストで縛ってある）。

## 4. 触る前に知っておくこと

到達範囲は 3 段（`Authority`）。**上の段は下の段を含む。**

```
SYSTEM   RA の運用者。全 NAAN に届く
NAAN     1 つの NAAN の配下すべて
MANAGER  1 組織ぶん（shoulder_id を併せると 1 shoulder に固定）
```

到達範囲は**クライアント登録の属性**で、要求本文やトークンの中身からは決して
来ない。トークンは scope を**狭める**ことしかできない。ここを緩める変更は
差し戻される。

CLI は `_root()` でシステム管理者として動く。サーバのシェルに入れる時点で DB に
届くので権限で絞っても意味の在る防御にならない——**代わりに操作は必ず監査に残る**。

### 委譲まわりを触るなら、解決の順を先に読む

`domain/resolution.py` の判断順（完全一致 → 祖先 → **検査桁** → shoulder の redirect →
404）は、**順序そのものが結論を決める**。検査桁が shoulder 委譲より先にあるので、
委譲先が検査桁を作らないと**上位経由の解決だけが 404 になる**——下位に直接来た要求は
通るので、いちばん見つけにくい壊れ方をする。

複数の arkhe で分担する構成の前提と穴は[分散して運用する](docs/guides/federation.md)。
**台帳を分けた瞬間、コードが守っていた不変条件のいくつかが人の手に移る**（同じ
shoulder を 2 か所で採らない、権威を持つ台帳は NAAN あたり 1 つ）。

## 5. 実際に踏んだ罠

**同じ穴に二度落ちないために書いてある。** どれも実際に起きた。

| | |
| --- | --- |
| **`alembic check` の指摘は本物** | `use_alter` の FK は `op.create_table` が落とす。「宣言してあるのに作られない」が実際に起きた。SQLite は通す |
| **マイグレーションは PostgreSQL で見る** | SQLite は PostgreSQL が弾くスキーマを通す。開発中に 2 回、これがバグを隠した。`upgrade → downgrade base → upgrade → check` まで回す |
| **CHANGELOG に `s.index("### Added")` を使わない** | ファイル先頭からの最初の一致を返すので、**リリース済みの節に追記してしまう**。2 回やった。「未リリース」の見出しを起点に探す |
| **CSP の `script-src 'none'` は Swagger UI を白紙にする** | `/api/docs` `/api/redoc` だけ `DOCS_CSP` を当てている。触ったら実物を開いて見ること |
| **`/healthz` は全モードに要る** | resolver / minter / admin のどれで起動しても要る。1 つに付け忘れて k8s に殺され続けた |
| **`/readyz` に `Depends(get_session)` を使わない** | 依存がハンドラより先に落ちるので 503 でなく 500 になる。自前でセッションを開く |
| **`dataclasses.replace` は代入しないと効かない** | `replace(res, ...)` の戻り値を捨てたまま次行で `return` していて、直したつもりが直っていなかった |
| **i18n の訳文に `` ` `` や `**` を書かない** | 画面にそのまま出る。何度もやったのでテストで縛ってある |
| **部分ユニーク索引** | `(manager_id, label)` の一意制約は空文字を弾いてしまう。ラベル無しの主体は 1 組織 1 つしか作れなくなる |
| **参照ページは生成物ではない** | `docs/reference/cli.md` と `configuration.md` は**手で書く**。Contributing に「生成される」と書いてあったのは誤りで、そのせいで設定 2 つとコマンド 1 つが未記載のまま残っていた。今は `tests/test_docs.py` が落とす |
| **`uv lock` は版を上げたら要る** | `pyproject.toml` の `version` を上げると lock とずれて `--frozen` が落ちる |
| **Typer の help は import 時に確定する** | だから CLI の言語は環境変数から一度だけ決まる。`--lang` のような実行時切り替えは作れない |

## 6. テスト

新しい挙動には、**それが無ければ落ちるテスト**を付ける。認可に触るなら
**通らないほうの場合**も書く——面白いのは正しい主体が通ったことではなく、
**間違った主体が通らなかったこと**。

テストは文になっている（`test_他組織のARKは更新できない`）。落ちたときに、
例外を投げた関数ではなく**壊れた決まり**が名指しされるように。

```
tests/test_resolution.py   解決とインフレクション
tests/test_authz.py        到達範囲。**負の場合を厚く**
tests/test_admin.py        管理画面
tests/test_cli.py          運用コマンド
tests/test_docs.py         参照ページが実装から遅れていないこと
tests/test_cli_i18n.py     訳の抜けと差し込み先のずれ
```

## 7. 文書

MkDocs Material、**接尾辞で 2 言語**（`page.md` が英語、`page.ja.md` が日本語）。
図は Mermaid のコードブロック——再生成する画像ファイルを持たない。

```bash
uv run mkdocs build --strict     # 警告 0 を保つ
uv run python scripts/export_openapi.py   # API 仕様はここだけ生成物
```

**設定を足したら `docs/reference/configuration.{md,ja.md}` に、コマンドを足したら
`cli.{md,ja.md}` に、両方の言語で行を足す。** 忘れるとテストが落ちる。

ページを 1 枚足すときにやること（**どれか 1 つ抜けると片方の言語で消える**）:

1. `docs/…/name.md` と `docs/…/name.ja.md` を対で作る
2. `mkdocs.yml` の `nav` に英語の題で足す
3. 同じ題を `nav_translations` に日本語で足す——**ここを忘れると日本語版に英語の項目が並ぶ**
4. 日本語の見出しに深いリンクを張るなら `{#anchor}` を自分で書く（`attr_list` が効く）。
   自動生成のアンカーは見出しを 1 つ足すとずれる

## 8. コミットとリリース

コミットメッセージは**変更ではなく理由**を書く。将来の読者が知りたいのは、
何を知っていたからそれが正解だったのか——特に答えが奇妙に見えるところで。

リリースも手元で回る。**既定は「出さない」**——確かめるのは安く何度でもできるが、
タグと GitHub のリリースはそうではない。

```bash
bash scripts/release.sh v0.0.9              # 検査と dist の作成だけ
bash scripts/release.sh v0.0.9 --publish    # タグ → push → GitHub のリリース
```

**手順そのものも検査する**——版の一致（`pyproject` とタグ）、CHANGELOG にその版の節と
リンク定義が**日英とも**あること、「未リリース」の比較リンクが新しい版を指していること。
どれも実際に間違えたことのある場所である。

版は `pyproject.toml` だけで決まる。ずれていれば `release.sh` が落とす
——**「v0.0.2 と名乗る 0.0.1」を世に出さないため**。手順:

1. `pyproject.toml` の `version` を上げる → `uv lock`
2. CHANGELOG の「未リリース / Unreleased」の下に版の節を作る（**リリース済みの
   節に追記しない**）。末尾のリンク定義も 2 言語ぶん、「未リリース」の比較リンクも
   新しい版に置き換える
3. コミット
4. `bash scripts/release.sh vX.Y.Z` が緑 → `--publish` を付けて出す
5. `bash scripts/deploy-docs.sh`（変更履歴のページを追随させる）
6. `weko4` 側のサブモジュールポインタを進める

0.x のあいだはプレリリースとして出る。

### デモの台帳に実在するものを置かない

`seed_demo.py` と `realm-arkhe.json` に置くのは**例示用の名前と番号だけ**。
本物の機関名を置くと、その機関が arkhe を使っているように読める——画面をその
まま見せる資料や録画に載ったときに、こちらの意図と関係なく既成事実になる。
NAAN も同じで、割り当て済みの番号は使わない（`99999` は仕様が試験用に予約して
いる番号、`12345` / `54321` は例示のための値）。

## 9. 動かして確かめる

**画面に関わる変更は、実物を開いて見る。** 括弧書きの用語も、スマホ幅での
はみ出しも、テストでは落ちなかった。

```bash
cd compose/oidc && docker compose up -d      # arkhe :8057 / resolver :8058 / Keycloak :8080
docker compose exec -T arkhe arkhe ark list
```

LAN から見せるときは `lan.yml` を重ねて `ARKHE_DEMO_HOST` を指定する。

イメージを焼き直したら**古いコンテナを残さない**——別ポートに古い版が生きて
いて、見ている画面が違う、が実際に起きた。

## 10. 迷ったとき

**識別子は振り直せない。** 迷う変更のほとんどは、「間違えたときに取り返せるか」
で決まる。取り返せないものは、緩めるより拒否するほうを既定にする。
