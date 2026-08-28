# arkhe

*[English version](README.md)*

ARK 識別子の基盤。**採番（minter）と解決（resolver）を別プロセスで動かす。**

ARK は DOI / Handle と違い、有償の登録機関と中央基盤を前提としない識別子体系で、
「**永続性は文字列の性質ではなく、サービスの問題**」という立場を取る。arkhe はその立場のまま、
機関へ名前空間を委譲し、永続性の水準を各機関が自己申告できる形で運用するための実装。

名前の由来はギリシャ語 ἀρχή（始原・原理）。参照が始まる点、という意味。

FastAPI ＋ SQLAlchemy 2.0。`src/arkhe/arkspec/`（ARK 仕様の純関数層）と
`src/arkhe/domain/resolution.py`（解決の決定ロジック）は **stdlib しか使わない**ので、
仕様の検証だけしたい利用者は何もインストールせずに読める。

設計・受け入れ条件・実装計画・仕様適合状況の各文書は、JC2 の作業リポジトリ側にある
（`ark_design_policy.md` / `ark_acceptance_criteria.md` / `ark_implementation_plan.md` /
`ark_conformance_jc2ark.md` ほか）。

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

## 認証

**排他の「モード」ではなく、機構を個別に有効化する。** 移行期に「API キーと OIDC の
両方を受ける」が普通に要るため。

```
ARKHE_AUTH=apikey,oidc
```

| | |
| --- | --- |
| `apikey` | 個人アクセストークン方式。**arkhe 単体で完結する**（外部依存なし） |
| `oauth2` | arkhe 自身が発行する。**client_credentials だけ**——ARK の採番は機関システムからの M2M で、認可コードフローが解く「利用者が第三者アプリに代理を許可する」構図が無いため |
| `oidc` | 外部の認可サーバ（Keycloak 等）が発行した JWT を検証する。人間のログインが要る場面はこちらに委譲する |

どの機構で認証しても `Principal` 1 つに集約され、**認可の判断は 1 か所**に集まる。

到達範囲は 3 段（`system` / `naan` / `manager`）。**配られた側が、配った側より広く
届くことはない。**

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
