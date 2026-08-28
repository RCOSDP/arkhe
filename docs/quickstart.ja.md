# クイックスタート

入口は 2 つ。**見る**なら compose、**触る**ならローカル導入が早い。

## Docker で

```bash
git clone https://github.com/RCOSDP/arkhe.git
cd arkhe/compose/oidc
docker compose up -d --build
```

Keycloak・PostgreSQL・arkhe が立ち、台帳も入った状態になる。

**<http://localhost:8057/admin/>** を開き、次のいずれかでログインする。

| 利用者 | パスワード | 到達範囲 |
| --- | --- | --- |
| `ops` | `arkhe-demo-2026` | システム管理者・全 NAAN |
| `naan-admin` | `arkhe-demo-2026` | NAAN 管理者・99999 配下すべて |
| `nibb` | `arkhe-demo-2026` | 機関管理者・1 機関のみ |

**順に入り比べるのが、[到達範囲](concepts/delegation.md)を理解する近道**。`nibb` では
他機関が見えず、監査ログは 403 になる。

!!! warning "この構成は見るためのもので、動かすためのものではない"
    秘密値が compose に平文で書いてあり、Keycloak は dev モードで、デモ用の
    パスワードは上に公開されている。[デプロイ](guides/deployment.md)を参照。

## ローカルで

```bash
git clone https://github.com/RCOSDP/arkhe.git && cd arkhe
uv venv --python 3.12 && uv pip install -e '.[app,dev]'
python -m pytest -q          # 209 tests
```

SQLite に最小の台帳を作る。

```bash
export ARKHE_DATABASE_URL="sqlite:///$PWD/arkhe.db"
export ARKHE_AUTH=apikey
alembic upgrade head

arkhe naan add 99999 "あなたの組織"
arkhe onboard 99999 "例大学" --shoulder /x9
arkhe client add univ-repo 99999 --manager 1 --scopes "ark:mint ark:update"
arkhe client key univ-repo          # 平文はこの一度だけ表示される
```

起動して、1 本採番して、解決する。

```bash
uvicorn arkhe.app:create_app --factory &

curl -X POST http://127.0.0.1:8000/api/mint \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"url": "https://example.org/records/1", "title": "最初の対象"}'
# → {"ark": "ark:/99999/x9…", …}

curl -i "http://127.0.0.1:8000/ark:/99999/x9…"        # 302 で対象へ
curl    "http://127.0.0.1:8000/ark:/99999/x9…??"      # 永続性宣言
```

## いま何が起きたか

**取り消せない識別子**を 1 本作った。ARK は再割当てしないと宣言する体系なので、
arkhe に削除は無い。対象が失われたときは削除ではなく
[tombstone](concepts/invariants.md) にする。

末尾の `??` は、その識別子について**何を約束しているか**をリゾルバに尋ねたもの。
**対象が失われていても答えられる**問いである。

## 次に読む

- [ARK とは何か](concepts/ark.md) — 設計全体が組み立てられている約束
- [認証](guides/authentication.md) — API に 3 機構、人の入口に 3 種類
- [設定](reference/configuration.md) — 全項目
