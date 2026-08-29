# OIDC モードを体験する

Keycloak・PostgreSQL・arkhe（採番／管理と解決の 2 プロセス）を立てる一式。
**arkhe をどこにも入れずに、認証つきで一周できる。**

```bash
docker compose up -d --build
```

| | URL |
| --- | --- |
| 管理画面・採番 API | <http://localhost:8057/admin/> |
| 解決（**認証不要**） | <http://localhost:8058/ark:/…> |
| API ドキュメント | <http://localhost:8057/api/docs> |
| Keycloak 管理コンソール | <http://localhost:8080/>（`admin` / `admin`） |

→ http://localhost:8057/admin/ を開くと Keycloak のログイン画面に送られる。

| 利用者 | パスワード | 到達範囲 |
| --- | --- | --- |
| `ops` | `arkhe-demo-2026` | システム管理者（全 NAAN） |
| `naan-admin` | `arkhe-demo-2026` | NAAN 管理者（99999 配下） |
| `org-admin` | `arkhe-demo-2026` | 組織管理者（例示大学のみ） |

同じ台帳を 3 つの立場で見比べられる。`org-admin` では他組織が見えず、監査ログは 403 になる。

## 採番して、解決する

```bash
# 1. Keycloak からトークンを取る（client_credentials。人もブラウザも登場しない）
TOKEN=$(curl -s -X POST \
  http://keycloak.localhost:8080/realms/arkhe/protocol/openid-connect/token \
  -d grant_type=client_credentials \
  -d client_id=example-invenio \
  -d client_secret=example-invenio-secret-for-demo-only | jq -r .access_token)

# 2. 採番する（8057 = minter）
ARK=$(curl -s -X POST http://localhost:8057/api/mint \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"url":"https://repo.example.ac.jp/records/999","title":"最初の一件"}' | jq -r .ark)

# 3. 解決する（8058 = resolver。**Authorization ヘッダを付けない**）
curl -i "http://localhost:8058/$ARK"        # 302 → 元の URL
curl "http://localhost:8058/$ARK?"          # ? → 記述（ERC）
curl "http://localhost:8058/$ARK??"         # ?? → 記述と方針
```

## LAN の別の端末から見る

```bash
ARKHE_DEMO_HOST=192.168.1.20 docker compose -f docker-compose.yml -f lan.yml up -d
```

**公開先を `0.0.0.0` にするだけでは足りない。** issuer と redirect_uri は
**ブラウザが実際に打つ URL** でなければならないので、具体的なアドレスが要る
（`0.0.0.0` は「未指定のアドレス」で宛先には使えず、ブラウザはこれを localhost と
解釈するため、別の端末から開くとその端末自身に接続しに行く）。

| | |
| --- | --- |
| 待ち受け | `0.0.0.0` — どの NIC でも受ける |
| issuer | `${ARKHE_DEMO_HOST}:8080` — ブラウザが打つ URL |
| redirect_uri | `${ARKHE_DEMO_HOST}:8057` — Keycloak が照合する文字列 |

redirect_uri は `lan-redirect` が起動時に足す。**realm JSON には焼き込まない**——
公開されるファイルに特定の LAN アドレスを書くことになるため。

既定（`lan.yml` なし）が `127.0.0.1` なのは、この一式が**デモ用の秘密値を平文で
持ち、Keycloak が dev モード**で、利用者のパスワードを上に公開しているから。
LAN に出すのは明示的な操作にしてある。

## 解決は認可サーバに依存しない

分けてあるのは飾りではない。止めてみると分かる:

```bash
docker compose stop keycloak

curl -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8057/api/mint \
  -H 'Content-Type: application/json' -d '{"url":"https://x/1"}'   # 401
curl -o /dev/null -w '%{http_code}\n' "http://localhost:8058/$ARK"  # 302

docker compose start keycloak
```

**採番は止まるが、解決は止まらない。** 解決に認証は要らないので、resolver は
認証の設定を一切持たない（`ARKHE_SESSION_SECRET` すら要求されない）。既に配った
識別子が外部の障害で解決不能になる、という事態を構造で避けている。

## API も同じ Keycloak で叩く

この構成は `ARKHE_AUTH=apikey,oauth2,oidc` で動いている。**機構は排他ではない**ので、
3 つとも同時に受け付ける（移行期に両方要るのが普通）。

| 機構 | 何を送るか |
| --- | --- |
| `apikey` | arkhe が出した鍵をそのまま `Bearer` で送る |
| `oauth2` | arkhe 自身の `/oauth/token` で client_secret をトークンに換える |
| `oidc` | Keycloak が出したトークンを送る（下記） |

管理画面の利用者ページから、`apikey` と `oauth2` の鍵はどちらも発行できる。
**その構成で通らない種別は出さない**ので、`ARKHE_AUTH` から機構を外すと
選択肢からも消える。

到達範囲は**トークンではなく arkhe の台帳が決める**。`example-invenio` は例示
研究所の主体として登録してあるので、こうなる:

```
採番                    → ark:/99999/x9…       通る
tombstone               → insufficient_scope   登録に無い操作
shoulder=/y2 を指定     → この主体の範囲外     他組織の名前空間
```

### scope は認可サーバが配る

realm に `ark:mint` / `ark:update` / `ark:read` / `ark:tombstone` を client scope として
定義し、クライアントに割り当ててある。**`arkhe-api`（audience）は realm の既定に
入れていない**——既定にすると、この realm に後から作ったどんなクライアントでも
arkhe 宛だと名乗れるトークンを取れてしまう。トークンには割り当てたものだけが載り、
arkhe はそれと**登録済みの範囲との積**を採る（トークンで範囲は広がらない）。

認可サーバが arkhe の語彙を持たない場合は、登録済みの範囲をそのまま使う。素通しに
しても危なくないのは `aud` の検証が先に効いているからで、逆に無関係な語彙
（`profile` など）と積を採ると必ず空集合になり、分かりにくい 403 を生むだけになる。

## issuer の文字列を揃えるのが要点

認可サーバの issuer は、**ブラウザから見た URL と arkhe（コンテナ）から見た URL が
同じ文字列**でなければならない。食い違うと `iss` の検証で落ちる。ここでは
`keycloak.localhost:8080` に揃えている。

```
ブラウザ   keycloak.localhost → 127.0.0.1 → 公開ポート 8080 → Keycloak
arkhe      keycloak.localhost → compose のネットワークエイリアス → Keycloak:8080
```

`*.localhost` は多くの環境で 127.0.0.1 に解決される（systemd-resolved・主要ブラウザ）。
解決されないときは hosts に `127.0.0.1 keycloak.localhost` を足す。

## arkhe は認可サーバにならない

ここで arkhe がやるのは **OIDC のクライアント（RP）になる**ことだけ。認可コード
フローを開始し、戻ってきた JWT を JWKS で検証し、セッションにする。**トークンは
発行せず、同意も預からない。**

外部で認証できることと、この名前空間を触ってよいことは別なので、**戻ってきた身元は
arkhe の台帳（`Client`）に突き合わせる**。登録が無ければ入れない。

## 本番に持っていくときは

* `ARKHE_SESSION_SECRET` と `ARKHE_ADMIN_CLIENT_SECRET` を差し替える（この compose の値は
  体験用に平文で書いてある）
* `ARKHE_SESSION_SECURE` を外す（HTTPS で出すなら Cookie に Secure を付ける）
* Keycloak を `start-dev` ではなく `start` で動かし、`sslRequired` を `external` にする
* 利用者は `arkhe client add <認可サーバが返す識別子> <NAAN> --person` で登録する
