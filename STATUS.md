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
| 版 | **0.0.8**（2026-08-29 リリース）。`main` は clean、タグと `pyproject.toml` は一致 |
| テスト | **403 件すべて green**（`uv run pytest -q`、約 13 秒） |
| 静的検査 | `ruff check src tests` 通過（E/F/I/UP/B、line-length 100） |
| 文書 | `mkdocs build --strict` 警告 0。日英 2 言語で 18 ページ |
| マイグレーション | head は単一（`b65e77b221ac`）。`scripts/check.sh` が PostgreSQL 17 で up→down→up→check を回す |
| 実装規模 | `src/arkhe/` 51 ファイル・約 8,400 行 |
| Python | 3.12 以上。本体の依存は **optional**（`arkspec` と `domain.resolution` は何も入れずに import できる） |

## 何が動くか

**すべて単一台帳（1 つの arkhe ＋ 1 つの DB）を前提にした状態。**

| 領域 | 状態 | 場所 |
| --- | --- | --- |
| ARK 仕様の純関数層 | NOID 生成、検査桁、shoulder 分割、正規化・インフレクション | `arkspec/` |
| 解決 | 完全一致 → 祖先 passthrough → 検査桁 → shoulder 委譲 → 404／取次。`?` `??` `?info` `?json` | `domain/resolution.py` |
| 採番 | 衝突は握りつぶさず数えて採り直す。冪等鍵（`request_id`）、一括採番、quota | `domain/minting.py` |
| 委譲 | shoulder の 4 状態、`delegated` は `307` で行き先を返す（**プロキシしない**） | `domain/admin_ops.py` |
| 承継・離脱 | `arkhe succeed` / `arkhe depart --resolver`。**`Ark` の行には触れない** | `domain/admin_ops.py` |
| 認証 | `apikey` / `oauth2`（client_credentials のみ）/ `oidc`。**併用できる** | `auth/` |
| 管理画面への入口 | `bearer` / `password` / `oidc` / `proxy` の 4 つ | `auth/login.py` |
| 認可 | 3 段の到達範囲。**判断は 1 か所**、リクエストで広がらない | `domain/authz.py` |
| 管理画面 | 台帳・主体・ARK 一覧・監査・未登録主体。日英切替、画面ごとの i18n | `api/admin/`, `api/i18n/` |
| 記録 | `AuditEvent`（NAAN 以上の操作）と `ArkChange`（行き先の変更は全件） | `db/models.py` |
| 運用コマンド | 20 コマンド。**画面と同じ `domain` を通る** | `cli.py` |
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
- **`shoulder.redirect` を設定する CLI が無い。** 管理画面と `arkhe depart --resolver`
  からのみ。委譲の設定を自動化で組もうとするとここで止まる。
- **台帳をまたぐ一覧・監査・quota が無い。** `/.well-known/ark` が出すのは名前空間の
  割当まで。
- **委譲先の健全性を見ていない。** 上位は下位が生きているかを知らない。
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

1. **転送の一時停止（hold）。** 分散構成で最初に足りなくなるのはこれだと思われる。
   設計は下に書き出した。

2. **`shoulder.redirect` の CLI**（`arkhe shoulder redirect <id> <template>`）。
   小さく、分散構成の自動化を今すぐ楽にする。画面と同じ `admin_ops` を呼ぶだけ。
3. **外部採番の取り込み口**。分散構成の穴の本体。入れるなら、名前が委譲した shoulder の
   内側にあること・二重採番でないこと・検査桁が合っていることを取り込み時に検査する
   ——**採番が更新に化けない**という不変条件を、取り込み経路でも守る必要がある。
4. **復元リハーサルと性能測定**。0.1 を名乗る前にやるべきこと。
5. **委譲先の外形監視**。運用の道具であって arkhe の機能とは限らない。

## 設計案: 転送の一時停止（hold）

**未実装。** 委譲先のリゾルバが落ちた、乗っ取られた、間違った行き先を配ってしまった、
機密が漏れて取り下げを求められた、データが移動中——**どれも急いで止めたいが、
識別子を殺したくない**。分散構成では、止めたい対象が自分の台帳に無いこともある
（委譲した shoulder の配下）。

### まず、「解決を止める」を額面通りに作らない

| 返し方 | なぜ採らないか |
| --- | --- |
| `404` | **嘘である。** その識別子は存在する。リンクチェッカーは死んだリンクとして記録し、NR を宣言した意味が消える |
| `503` | 一時的だとは伝わるが、**識別子が壊れて見える**のは同じ。永続識別子が「今は答えられない」と言う姿は、約束の側から見ると弱い |
| **`200` ＋ 記述** | **これを採る。** 止めるのは*転送*であって*解決*ではない。D6（`url` が空なら記述を返す）と tombstone が既に通っている経路で、識別子は生きたまま |

**解決は止めてはならない。止めてよいのは転送だけ。** これは[デプロイ](docs/guides/deployment.md)の
「解決は止めてはならない。採番は止めてよい」と同じ線の引き方である。

### tombstone との違い

| | tombstone | hold |
| --- | --- | --- |
| 意味 | **対象が失われた** | **対象は在るが、今は行き先を出せない** |
| 期間 | 恒久 | **期限つき（必須）** |
| 元の行き先 | 捨てる（`ArkChange` にだけ残る） | **保持する。** 期限が切れれば戻る |
| scope | `ark:tombstone` | `ark:hold`（新設。日常の書き手に渡さない） |

### 形

3 つの粒度に、同じ 3 列を持たせる。**行を書き換えないので、戻せる。**

```
Ark      hold_until / hold_reason / hold_by      1 件だけ止める
Shoulder hold_until / hold_reason / hold_by      配下すべて。**ARK の url は触らない**
Naan     hold_until / hold_reason / hold_by      その NAAN すべて
```

**期限は必須にする。** 「一時的」を人の記憶に頼ると恒久化する。上限（たとえば 90 日）を
置き、延長は再設定として監査に残す。

**期限切れをバッチで戻さない。** 解決のたびに `hold_until < now` を見て、切れていれば
効かないと判定する——状態を書き換えないので、**時計だけで戻る**。戻し忘れが起きない。

### 解決のどこに入るか

`domain/resolution.py` の判断順に 2 か所。

1. 完全一致・祖先で ARK が見つかった直後（`_deliver` の前）——ARK → その shoulder →
   その NAAN の順に見て、**どれか効いていれば `DESCRIBE`**
2. `shoulder.redirect` を返す前——委譲先を止めるのはここ（**上位から下位への転送を
   止める**）

**inflection は止めない。** `?info` も `??` も答え続ける。とくに `??`（永続性宣言）を
止めるのは、約束そのものを引っ込めることになる。応答には**理由と期限**を載せる
——止まっていることが外から分かるほうが、黙って止まるより良い。

### 出す口

- `PUT /api/hold` / `DELETE /api/hold`（`ark:hold` scope）
- `arkhe hold add <ark|shoulder|naan> --until <日付> --reason "…"` / `arkhe hold release`
- 管理画面に**保留中の一覧**（期限つきでも、目に見えないと恒久化する）
- `/.well-known/ark` と `?json` に `hold: {reason, until}` を出す
  ——**分散構成では、上位と下位が互いの状態を見られる必要がある**

### 決めていないこと

- **クローラにどう伝えるか。** `200` を返す以上 `Retry-After` は使えない。人には
  説明が届くが、機械には「今は行き先が無い」としか伝わらない。ここは割り切りになる。
- **`Naan` 単位の hold を誰が設定できるか。** 自 NAAN なら `naan` 権限で足りるが、
  委譲先の NAAN を上位が止める構図は、そもそも権威の分割と衝突する。

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
