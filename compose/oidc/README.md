# OIDC モードを体験する

Keycloak を立て、arkhe を **`ARKHE_ADMIN_LOGIN=oidc`** で動かす一式。

```bash
docker compose up -d --build
```

→ http://localhost:8057/admin/ を開くと Keycloak のログイン画面に送られる。

| 利用者 | パスワード | 到達範囲 |
| --- | --- | --- |
| `ops` | `arkhe-demo-2026` | システム管理者（全 NAAN） |
| `naan-admin` | `arkhe-demo-2026` | NAAN 管理者（99999 配下） |
| `nibb` | `arkhe-demo-2026` | 機関管理者（基礎生物学研究所のみ） |

同じ台帳を 3 つの立場で見比べられる。`nibb` では他機関が見えず、監査ログは 403 になる。

Keycloak の管理コンソールは http://localhost:8080/（`admin` / `admin`）。

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
