# クイックスタート

入口は 2 つ。**見る**なら compose、**触る**ならローカル導入が早い。

## Docker で

```bash
git clone https://github.com/RCOSDP/arkhe.git
cd arkhe/compose/oidc
docker compose up -d --build
```

Keycloak・PostgreSQL・arkhe が立ち、台帳も入った状態になる。arkhe は本番と同じく
**採番／管理と解決の 2 プロセスに分かれている**。

| | URL |
| --- | --- |
| 管理画面・採番 API | <http://localhost:8057/admin/> |
| 解決（**認証不要**） | <http://localhost:8058/ark:/…> |
| API ドキュメント | <http://localhost:8057/api/docs> |
| Keycloak 管理コンソール | <http://localhost:8080/>（`admin` / `admin`） |

**<http://localhost:8057/admin/>** を開き、次のいずれかでログインする。

| 利用者 | パスワード | 到達範囲 |
| --- | --- | --- |
| `ops` | `arkhe-demo-2026` | システム管理者・全 NAAN |
| `naan-admin` | `arkhe-demo-2026` | NAAN 管理者・99999 配下すべて |
| `nibb` | `arkhe-demo-2026` | 機関管理者・1 機関のみ |

**順に入り比べるのが、[到達範囲](concepts/delegation.md)を理解する近道**。`nibb` では
他機関が見えず、監査ログは 403 になる。

続けて、採番して解決してみる。

```bash
TOKEN=$(curl -s -X POST \
  http://keycloak.localhost:8080/realms/arkhe/protocol/openid-connect/token \
  -d grant_type=client_credentials -d client_id=nibb-invenio \
  -d client_secret=nibb-invenio-secret-for-demo-only | jq -r .access_token)

ARK=$(curl -s -X POST http://localhost:8057/api/mint \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"url": "https://example.org/records/1", "title": "最初の一件"}' | jq -r .ark)

curl -i "http://localhost:8058/$ARK"     # 302 で元の URL へ
curl "http://localhost:8058/$ARK??"      # 記述と、その背後の方針
```

認可サーバを止めて、もう一度両方やってみる。

```bash
docker compose stop keycloak
# 採番は 401 になる——解決は 302 のまま
docker compose start keycloak
```

**採番は止まるが、解決は止まらない。** 解決に認証は要らないので、resolver は
認証の設定を一切持たない。既に配った識別子が、別のものの障害で解決できなくなる
という事態を構造で避けている。

!!! warning "この構成は見るためのもので、動かすためのものではない"
    秘密値が compose に平文で書いてあり、Keycloak は dev モードで、デモ用の
    パスワードは上に公開されている。[デプロイ](guides/deployment.md)を参照。

## ローカルで

```bash
git clone https://github.com/RCOSDP/arkhe.git && cd arkhe
uv venv --python 3.12 && uv pip install -e '.[app,dev]'
python -m pytest -q          # 219 tests
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
