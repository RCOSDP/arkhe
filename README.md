# arkhe

ARK 識別子の基盤。**採番（minter）と解決（resolver）を別プロセスで動かす。**

ARK は DOI / Handle と違い、有償の登録機関と中央基盤を前提としない識別子体系で、
「**永続性は文字列の性質ではなく、サービスの問題**」という立場を取る。arkhe はその立場のまま、
機関へ名前空間を委譲し、永続性の水準を各機関が自己申告できる形で運用するための実装。

名前の由来はギリシャ語 ἀρχή（始原・原理）。参照が始まる点、という意味。

> **状態**: 現行は Django 実装。**FastAPI ＋ SQLAlchemy 2.0 への書き直しを予定**しており、
> 認可は自前発行をやめて外部の認可サーバ（Keycloak 等）へ委譲する。
> `src/jc2ark/arkspec/`（ARK 仕様の純関数層）は stdlib のみに依存するため、書き直しの影響を受けない。
> パッケージ名 `jc2ark` → `arkhe` の改名も書き直しと同時に行う（Django の app_label は
> `ark` なので、改名しても DB のテーブル名は変わらない）。

設計・受け入れ条件・実装計画・仕様適合状況の各文書は、JC2 の作業リポジトリ側にある
（`ark_design_policy.md` / `ark_acceptance_criteria.md` / `ark_implementation_plan.md` /
`ark_conformance_jc2ark.md` ほか）。

## 構成

| | |
| --- | --- |
| `src/jc2ark/arkspec/` | **ARK 仕様の純関数層。Django にも DB にも依存しない。** 仕様の難所はここ |
| `src/jc2ark/ark/` | ドメイン（モデル・解決・認可・API・admin） |
| `src/jc2ark/entrypoints/` | settings / urls / asgi / wsgi / DB ルータ |

`RESOLVER=1` で resolver として起動する。**minter に解決の口は無い**（別々にスケール
させ、resolver を読み取り専用ロールとレプリカに向けるため）。

## 開発

```bash
uv venv --python 3.12 && uv pip install -e '.[app,dev]'
python -m pytest -q          # 133 tests
python -m ruff check src tests
python manage.py onboard 99999 "基礎生物学研究所" --label ingest
```

## 由来

`src/jc2ark/arkspec/` の一部は Internet Archive の
[arklet](https://github.com/internetarchive/arklet)（MIT）から派生している。
該当箇所には出典を記し、`LICENSE` に著作権表示と許諾文を含めている。
