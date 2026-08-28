# 設定

すべて `ARKHE_` 接頭の環境変数、または `.env` の項目。`arkhe check` で検証でき、
足りないものがあればその場で止まる。

!!! danger "秘密値に既定値は無い（意図的に）"
    `ARKHE_TOKEN_SECRET` / `ARKHE_SESSION_SECRET` / `KC_ADMIN_PASSWORD` は、
    未設定なら**値を代用せずに起動を止める**。動いてしまう既定値は、気づかれないまま
    本番に出ていく既定値である。

## 役割

| | 既定 | |
| --- | --- | --- |
| `ARKHE_RESOLVER` | `false` | resolver として動かす。**minter に解決の口は無く、resolver に採番の口も無い**——別々にスケールでき、resolver は読み取り専用のレプリカに向けられる |
| `ARKHE_DEBUG` | `false` | |
| `ARKHE_ALLOWED_HOSTS` | `*` | カンマ区切り |

## データベース

| | 既定 | |
| --- | --- | --- |
| `ARKHE_DATABASE_URL` | `postgresql+psycopg://arkhe@localhost/arkhe` | |
| `ARKHE_READ_DATABASE_URL` | — | resolver 用の読み取り専用接続。未設定なら上と同じ |

!!! warning "マイグレーションは PostgreSQL で検証すること"
    SQLite は PostgreSQL が許さないものを通してしまう。とくに `manager` と
    `shoulder` の循環参照と、表の作成順。**開発中に両方とも SQLite だけの確認を
    すり抜けた。**

## 認証 — API

| | 既定 | |
| --- | --- | --- |
| `ARKHE_AUTH` | `apikey,oidc` | **併用可**。順に試す。`apikey` / `oauth2` / `oidc` |
| `ARKHE_TOKEN_SECRET` | — | `oauth2` の署名鍵。**32 バイト以上**（RFC 7518 §3.2） |
| `ARKHE_TOKEN_TTL` | `3600` | |
| `ARKHE_TOKEN_ISSUER` | — | |
| `ARKHE_OIDC_ISSUER` | — | `oidc` では必須 |
| `ARKHE_OIDC_AUDIENCE` | — | **API のアクセストークン**に求める audience。ID トークンの `aud` ではない（そちらは `admin_client_id`） |
| `ARKHE_OIDC_JWKS_URL` | — | 未設定なら issuer の discovery から引く |

どれを選ぶべきかは[認証](../guides/authentication.md)を参照。

## 認証 — 管理画面

| | 既定 | |
| --- | --- | --- |
| `ARKHE_ADMIN_LOGIN` | `bearer` | `bearer` / `password` / `oidc` / `proxy` |
| `ARKHE_SESSION_SECRET` | — | `bearer` 以外では必須。32 バイト以上 |
| `ARKHE_SESSION_TTL` | `28800` | 8 時間 |
| `ARKHE_SESSION_SECURE` | `true` | HTTPS で出すなら付けたままにする |
| `ARKHE_ADMIN_CLIENT_ID` | — | `oidc` では必須 |
| `ARKHE_ADMIN_CLIENT_SECRET` | — | |
| `ARKHE_ADMIN_SCOPE` | `openid profile email` | |
| `ARKHE_PROXY_USER_HEADER` | `X-Forwarded-User` | `proxy` 用 |

!!! danger "`proxy` は直接届く経路を塞ぐことが前提"
    プロキシを通らずに arkhe へ届く経路が残っていると、**誰でもヘッダを詐称できる**。
    k8s なら NetworkPolicy、単体なら 127.0.0.1 だけで待ち受ける。

## 解決

| | 既定 | |
| --- | --- | --- |
| `ARKHE_GLOBAL_RESOLVER` | `https://n2t.net` | 未知 NAAN の取次先（D2） |
| `ARKHE_RAW_URI_HEADER` | — | 生のリクエスト URI を運ぶヘッダ名。裸の `?` を判別するために使う。クエリ文字列が空の `?` は **ASGI でも区別できない** |

## 採番

| | 既定 | |
| --- | --- | --- |
| `ARKHE_BULK_LIMIT` | `1000` | 1 リクエストの件数。**それ以上は分割し、`request_id` を付ける**——切れた塊はそのまま再送してよい |
