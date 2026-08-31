# STATUS

**2026-08-31 時点の arkhe の現在地。** 作業を止めて再開するときに、まずここを読む。

設計の意図は[不変条件](docs/concepts/invariants.md)、手順と踏んだ罠は
[AGENTS.md](AGENTS.md)、変更の履歴は [CHANGELOG.ja.md](CHANGELOG.ja.md) にある。
**ここに書くのは「今どこまで来ていて、何が無いか」だけ**——重複させると必ず片方が古くなる。

## 一言でいうと

**単一台帳で動く ARK 基盤としては一通り揃っている。** 採番・解決・委譲・承継離脱・
3 つの認証機構・管理画面・監査まで実装され、緑で、文書がある。まだ 0.x なのは、
運用実績が無いことと、複数拠点で分担する構成（[分散して運用する](docs/guides/federation.md)）に
まだ穴があるため。

| | |
| --- | --- |
| 版 | **0.0.9**（2026-08-31 リリース）。`main` は clean、タグと `pyproject.toml` は一致 |
| テスト | **427 件すべて green**（`uv run pytest -q`、約 14 秒） |
| 静的検査 | `ruff check src tests` 通過（E/F/I/UP/B、line-length 100） |
| 文書 | `mkdocs build --strict` 警告 0。日英 2 言語で 18 ページ |
| マイグレーション | head は単一（`a3f1c9e2d570`）。`scripts/check.sh` が PostgreSQL 17 で up→down→up→check を回す |
| 実装規模 | `src/arkhe/` 51 ファイル・約 9,000 行 |
| Python | 3.12 以上。本体の依存は **optional**（`arkspec` と `domain.resolution` は何も入れずに import できる） |

## 何が動くか

**すべて単一台帳（1 つの arkhe ＋ 1 つの DB）を前提にした状態。**

| 領域 | 状態 | 場所 |
| --- | --- | --- |
| ARK 仕様の純関数層 | NOID 生成、検査桁、shoulder 分割、正規化・インフレクション | `arkspec/` |
| 解決 | 完全一致 → 祖先 passthrough → 検査桁 → shoulder 委譲 → 404／取次。`?` `??` `?info` `?json` | `domain/resolution.py` |
| 採番 | 衝突は握りつぶさず数えて採り直す。冪等鍵（`request_id`）、一括採番、quota | `domain/minting.py` |
| 委譲 | shoulder の 4 状態、`delegated` は `307` で行き先を返す（**プロキシしない**） | `domain/admin_ops.py` |
| 転送の保留 | ARK / shoulder / NAAN を**期限つきで**止める。解決は止めない（`200` と記述） | `domain/resolution.py` |
| 承継・離脱 | `arkhe succeed` / `arkhe depart --resolver`。**`Ark` の行には触れない** | `domain/admin_ops.py` |
| 認証 | `apikey` / `oauth2`（client_credentials のみ）/ `oidc`。**併用できる** | `auth/` |
| 管理画面への入口 | `bearer` / `password` / `oidc` / `proxy` の 4 つ | `auth/login.py` |
| 認可 | 3 段の到達範囲。**判断は 1 か所**、リクエストで広がらない | `domain/authz.py` |
| 管理画面 | 台帳・主体・ARK 一覧・監査・未登録主体。日英切替、画面ごとの i18n | `api/admin/`, `api/i18n/` |
| 記録 | `AuditEvent`（NAAN 以上の操作）と `ArkChange`（行き先の変更は全件） | `db/models.py` |
| 運用コマンド | 24 コマンド。**画面と同じ `domain` を通る** | `cli.py` |
| 観測性 | `/healthz` `/readyz`、構造化ログ、`/.well-known/ark` | `observability.py`, `api/resolve.py` |
| 体験環境 | Keycloak ＋ PostgreSQL ＋ minter/resolver の compose | `compose/oidc/` |

テストの内訳（403 件）:

```
test_admin_forms.py  画面のフォーム        test_authz.py       到達範囲（負の場合を厚く）
test_admin.py        管理画面             test_resolution.py  解決とインフレクション
test_arkspec.py      仕様の純関数層        test_api.py         API
test_auth.py         3 機構の認証          test_models.py      不変条件（削除拒否ほか）
test_succession.py   承継と離脱            test_cli.py         運用コマンド
test_cli_i18n.py     訳の抜け             test_docs.py        参照ページの追随
```

## 分かっている穴

**「無い」と分かっているものを、探す前に書いておく。**

### 分散構成（[分散して運用する](docs/guides/federation.md) で扱った）

- **外部で採番された ARK を取り込む口が無い。** `/api/mint` は名前を生成し、
  `/api/register` は既存 base の修飾子専用。**下位の arkhe が採った名前を上位の台帳に
  載せる方法が無い**ので、閉域構成では「上位で先に採って払い出す」か「上位は名前を
  知らない」の二択になる。
- **台帳をまたぐ一覧・監査・quota が無い。** `/.well-known/ark` が出すのは名前空間の
  割当まで。
- **委譲先の健全性を見ていない。** 上位は下位が生きているかを知らない。**止める手は
  ある**（保留）が、気づく手立ては運用の側にある。
- **redirect の循環を検知しない。** A→B→A は無限ループになる。運用で禁じるしかない。

### 実装の細部

- **`ARKHE_RAW_URI_HEADER` だけ `Settings` の外**にある（`api/resolve.py` が
  `os.environ` を直読み）。したがって `.env` から効かず、`arkhe check` の検査対象にも、
  `tests/test_docs.py` の網にも入らない。**参照ページに載っているのは手で書いたから**。
- **`Naan.minter` を設定できるのは管理画面だけ**（`naan add` に対応する選択肢が無い）。
- README.ja.md の例に実在の機関名が 1 か所残っている（`arkhe naan add 99999 "国立情報学研究所"`）。
  0.0.8 でデモ台帳からは外したが、README は対象外にしてある——**arkhe の開発元自身の名前
  なので誤読は生まない**という判断。揃えるなら直す。

### まだ確かめていないこと

- **本番運用の実績が無い。** 性能の数字（解決のレイテンシ、台帳が数百万行のときの
  一覧）を測っていない。
- **復元を試していない。** バックアップの手順は文書にあるが、実際に落として戻す
  リハーサルはしていない。ここは[デプロイ](docs/guides/deployment.md)の
  チェックリストが求めている項目そのもの。

## 次の一手の候補

**決まっていない。** 選ぶときの材料として並べる。

1. **外部採番の取り込み口**。分散構成の穴の本体。入れるなら、名前が委譲した shoulder の
   内側にあること・二重採番でないこと・検査桁が合っていることを取り込み時に検査する
   ——**採番が更新に化けない**という不変条件を、取り込み経路でも守る必要がある。
2. **復元リハーサルと性能測定**。0.1 を名乗る前にやるべきこと。
3. **委譲先の外形監視**。運用の道具であって arkhe の機能とは限らない
   ——ただし**止める側は入った**（保留）ので、あとは気づく手立てだけ。

## 入っているもの: 転送の保留（hold）

委譲先のリゾルバが落ちた、間違った行き先を配ってしまった、機密が漏れて取り下げを
求められた、データが移動中——**どれも急いで止めたいが、識別子を殺したくない**。

**額面どおりに「解決を止める」形では作っていない。** `404` は嘘（その識別子は
存在する）、`503` は識別子が壊れて見える。止めるのは**転送**だけで、応答は `200` と
記述——D6（`url` が空なら記述を返す）と tombstone が既に通っている経路に乗せてある。

| | tombstone | hold |
| --- | --- | --- |
| 意味 | **対象が失われた** | **対象は在るが、今は行き先を出せない** |
| 期間 | 恒久 | **期限つき（必須。上限 `ARKHE_HOLD_MAX_DAYS`）** |
| 元の行き先 | 捨てる | **残す。** 期限が切れれば戻る |
| scope | `ark:tombstone` | `ark:hold` |

決めたこと:

- **粒度は 3 つ**（`ark` / `shoulder` / `naan`）。同じ 3 列を持たせ、**狭いほうが
  優先する**（1 件を止めた理由のほうが具体的だから）。shoulder と NAAN の保留は
  配下の ARK の行を触らない——**触らないから戻せる**。
- **期限切れをバッチで戻さない。** 解決のたびに時計を見る（`resolution.hold_of`）ので、
  止め忘れは残っても**戻し忘れは残らない**。
- **inflection は止めない。** `?info` も `??` も答え続ける——とくに永続性宣言を
  引っ込めるのは、約束そのものを取り下げることになる。理由と期限はそこに載せて公開する。
- **理由は必須。** 公開の口に出るし、外す判断にも要る（書かれていない保留は、
  掛けた本人以外に外せない）。
- **止めた事実を公開する。** `?json` と `/.well-known/ark` の `held` に出る
  ——分散構成では、上位が止めたことを下位が機械的に確かめられる必要がある。
- **保留の判定で問い合わせを増やさない。** ARK → shoulder → NAAN は同じ 1 本の
  問い合わせに載せている（`repository._WITH_HOLD_CHAIN`）。解決はいちばん回る経路。

まだ決めていないこと:

- **クローラにどう伝えるか。** `200` を返す以上 `Retry-After` は使えない。人には
  説明が届くが、機械には「今は行き先が無い」としか伝わらない。
- **委譲先の NAAN を上位が止められるべきか。** 今は自 NAAN に届く主体だけが止められる。

## 環境まわりのメモ

- ローカルの `dist/`（0.0.5〜0.0.8 のビルド成果物）、`db.sqlite3`、`site/`、`.venv/` は
  **すべて `.gitignore` 済み**で追跡されていない。消して困るものは無い。
- `compose/oidc` は **見本であって手本ではない**——秘密値が平文、Keycloak は dev モード。
- **CI は無い。** 検査も公開も `scripts/` の 3 本で、走らせるのは手元である
  ——`check.sh`（検査ぜんぶ）、`deploy-docs.sh`（gh-pages へ）、`release.sh`
  （版を出す。`--publish` のときだけ実際に出る）。**系統を 2 つ持たない**ため。
- ドキュメントサイトは **gh-pages ブランチを配信**している（Settings → Pages →
  Deploy from a branch）。書き手は `deploy-docs.sh` だけで、**gh-pages は手で触らない**。
- `.github/` に残っているのは issue と PR のテンプレート、Dependabot（uv lock を毎週）。
