# jc2-ark

JC2 の ARK 識別子基盤。**採番（minter）と解決（resolver）を別プロセスで動かす。**

- 設計: `../ark_design_policy.md`
- 受け入れ条件: `../ark_acceptance_criteria.md`
- 実装計画: `../ark_implementation_plan.md`

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
