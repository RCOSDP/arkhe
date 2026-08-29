# arkhe

**ドキュメント: <https://rcosdp.github.io/arkhe/ja/>**

*[English version](README.md)*

ARK 識別子の基盤。**採番（minter）と解決（resolver）を別プロセスで動かす。**

ARK は DOI / Handle と違い、有償の登録組織と中央基盤を前提としない識別子体系で、
「**永続性は文字列の性質ではなく、サービスの問題**」という立場を取る。arkhe はその立場のまま、
組織へ名前空間を委譲し、永続性の水準を各組織が自己申告できる形で運用するための実装。

名前の由来はギリシャ語 ἀρχή（始原・原理）。参照が始まる点、という意味。

FastAPI ＋ SQLAlchemy 2.0。`src/arkhe/arkspec/`（ARK 仕様の純関数層）と
`src/arkhe/domain/resolution.py`（解決の決定ロジック）は **stdlib しか使わない**ので、
仕様の検証だけしたい利用者は何もインストールせずに読める。

設計・受け入れ条件・実装計画・仕様適合状況の各文書は、JC2 の作業リポジトリ側にある
（`ark_design_policy.md` / `ark_acceptance_criteria.md` / `ark_implementation_plan.md` /
`ark_conformance_jc2ark.md` ほか）。

## 動かしてみる

Keycloak・PostgreSQL・arkhe（採番／管理と解決の 2 プロセス）が、台帳の入った
状態で立ち上がる。

```bash
cd compose/oidc && docker compose up -d --build
```

| | |
| --- | --- |
| 管理画面・採番 API | <http://localhost:8057/admin/> |
| 解決（**認証不要**） | <http://localhost:8058/ark:/…> |
| API ドキュメント | <http://localhost:8057/api/docs> |

`ops` / `naan-admin` / `nibb`（いずれもパスワードは `arkhe-demo-2026`）で入り比べると、
同じ台帳が到達範囲ごとにどう見えるかが分かる。Keycloak を止めると採番は 401 に
なるが解決は答え続ける——[クイックスタート](https://rcosdp.github.io/arkhe/ja/quickstart/)。

## 構成

| | |
| --- | --- |
| `src/arkhe/arkspec/` | **ARK 仕様の純関数層。フレームワークにも DB にも依存しない。** 仕様の難所はここ |
| `src/arkhe/domain/` | 解決・認可・採番・管理操作・承継。**HTTP を知らない** |
| `src/arkhe/db/` | SQLAlchemy のモデルとリポジトリ |
| `src/arkhe/auth/` | 3 つの認証機構（apikey / oauth2 / oidc）と `Principal` |
| `src/arkhe/api/` | FastAPI のルータ、管理画面、国際化 |

`ARKHE_RESOLVER=1` で resolver として起動する。**minter に解決の口は無く、resolver に
採番の口も無い**（別々にスケールさせ、resolver を読み取り専用ロールとレプリカに
向けるため）。

データモデルは [`docs/data-model.ja.md`](docs/data-model.ja.md)（ER 図）。

## 認証

**排他の「モード」ではなく、機構を個別に有効化する。** 移行期に「API キーと OIDC の
両方を受ける」が普通に要るため。

```
ARKHE_AUTH=apikey,oidc
```

| | |
| --- | --- |
| `apikey` | 個人アクセストークン方式。**arkhe 単体で完結する**（外部依存なし） |
| `oauth2` | arkhe 自身が発行する。**client_credentials だけ**——ARK の採番は組織システムからの M2M で、認可コードフローが解く「利用者が第三者アプリに代理を許可する」構図が無いため |
| `oidc` | 外部の認可サーバ（Keycloak 等）が発行した JWT を検証する。人間のログインが要る場面はこちらに委譲する |

どの機構で認証しても `Principal` 1 つに集約され、**認可の判断は 1 か所**に集まる。

到達範囲は 3 段（`system` / `naan` / `manager`）。**配られた側が、配った側より広く
届くことはない。**

## 管理画面への入口

**ブラウザは Authorization ヘッダを付けられない。** API は Bearer トークンで足りるが、
人が管理画面に入る経路は別に要る。`ARKHE_ADMIN_LOGIN` で選ぶ。

| | |
| --- | --- |
| `bearer` | 既定。ログイン画面を持たない。トークンを付けられる相手（curl・自動化）専用 |
| `oidc` | arkhe が **OIDC のクライアント（RP）として**認可コードフロー（PKCE つき）を回し、戻ってきた身元をセッション Cookie にする |
| `proxy` | 前段の認証プロキシ（oauth2-proxy、nginx の OIDC など）が済ませた前提で、そのヘッダを信じる |

**「クライアントになる」ことと「認可サーバになる」ことは別。** arkhe は後者にはならない
（トークンを発行せず、同意も預からない）。`oidc` でやるのは、認可サーバに人を送り、
戻ってきた JWT を確かめることだけで、資源側の仕事の範囲に収まる。

⚠️ `proxy` を選ぶなら、**arkhe に直接届く経路を塞ぐこと。** 残っていると誰でも
ヘッダを詐称できる（k8s なら NetworkPolicy、単体なら 127.0.0.1 だけで待ち受ける）。

どの入口でも、行き着く先は API と同じ `Principal` で、到達範囲の判定も同じ。

### 利用者を足す

`proxy` / `oidc` で管理画面に入る人は、**人の主体として登録する**。

```bash
arkhe client add alice@example.ac.jp 99999 --manager 1 --person \
  --scopes "ark:mint ark:read"
```

`client_id` には**認可サーバやプロキシが返す識別子**（メール、eppn など）をそのまま
入れる。届いた身元をこの値で突き合わせるので、一致しなければ入れない。

**資格情報は発行しない。** 人の身元は外部が保証するものなので、arkhe に鍵を持たせない
（持たせると、外部で失効させてもその鍵で入れてしまう）。

> **人と機械は型で分けてある。** 機械の主体（API キーで名乗るもの）は、前段のヘッダで
> **名乗れない**。プロキシを正しく置けば防げる話だが、設定 1 つの誤りが「一括投入
> バッチとして全件書き換え」に化けるのは脆いので、経路そのものを塞いでいる。
> 逆向きも同じで、人の主体は API キーで認証できない。

### ID とパスワードでログインする

外部 IdP が無い組織のための入口。

```bash
export ARKHE_ADMIN_LOGIN=password
export ARKHE_SESSION_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"

arkhe client add alice@example.ac.jp 99999 --manager 1 --person
arkhe client passwd alice@example.ac.jp     # 入力は画面に出ない
```

**`oidc` や `proxy` が使えるならそちらがよい。** 身元の管理が 1 か所に集まり、退職や
異動が組織側の操作だけで効く。`password` は、それが無い組織でも単体で建てられる
ようにするためのもの。

守っていること:

* 平文は保存しない（Argon2）
* **利用者の存在を漏らさない。** 未登録でも誤ったパスワードでも、同じ応答・同じ所要時間
* **総当たりを止める。** 5 回続けて失敗すると 15 分受け付けない。ログイン画面を出す
  以上、これが無いと辞書攻撃に素で晒される
* 長さだけを要求する（12 文字以上）。記号や大文字を強いる規則は、覚えられない文字列を
  生んで結局どこかに書き留められるので採らない
* パスワードを持てるのは**人の主体だけ**。変更しても古い行は消さず無効にする

参照: [`compose/oidc/`](compose/oidc/) に Keycloak を立てて `oidc` モードを
そのまま体験できる compose 一式がある。

### API の認証を単体で済ませる（Keycloak なし）

`ARKHE_AUTH` に `oauth2` を含めると、**arkhe 自身がトークンを配る**。認可サーバを
別に立てられない組織でも、OAuth2 の作法で API を叩ける。

```bash
export ARKHE_AUTH=oauth2
export ARKHE_TOKEN_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"

arkhe client add univ-repo 99999 --manager 1 --scopes "ark:mint ark:update"
arkhe client key univ-repo --kind client_secret     # 平文はこの一度だけ

curl -X POST http://localhost:8000/oauth/token \
  -d grant_type=client_credentials -d client_id=univ-repo -d client_secret=...
# → {"access_token": "...", "token_type": "Bearer", "expires_in": 3600, "scope": "..."}
```

**grant は client_credentials だけ。** ARK の採番は組織のシステムからの M2M で、
認可コードフロー（利用者が第三者アプリに代理を許可する手順）が要る場面が無い。
人のログインが要るなら `ARKHE_ADMIN_LOGIN` で外部に委譲する。

実装しないものを明記しておく: `authorization_code` / PKCE、`refresh_token`、
introspection、revocation。これらが要るようになったら、その時点で外部の認可サーバに
寄せるほうが安全——中途半端な認可サーバを育てるより。

| | arkhe 単体 | Keycloak が要る |
| --- | --- | --- |
| `apikey` | ○ | |
| `oauth2` | ○ | |
| `oidc` | | ○ |

`ARKHE_AUTH=apikey,oidc` のように**併用できる**（移行期に両方受けたい場面がある）。

## 開発

```bash
uv venv --python 3.12 && uv pip install -e '.[app,dev]'
python -m pytest -q          # 184 tests
python -m ruff check src tests

# 台帳を組み立てる
arkhe naan add 99999 "国立情報学研究所"
arkhe onboard 99999 "基礎生物学研究所" --shoulder /x9
arkhe client add nibb-web 99999 --manager 1
arkhe client key nibb-web        # 平文はこの一度しか表示されない

# 起動
uvicorn arkhe.app:create_app --factory
```

管理画面は `/admin/`（日英切替つき）。API のドキュメントは `/api/docs`。

## 由来

`src/arkhe/arkspec/` の一部は Internet Archive の
[arklet](https://github.com/internetarchive/arklet)（MIT）から派生している。
該当箇所には出典を記し、[`NOTICE`](NOTICE) に著作権表示と許諾文を含めている。
