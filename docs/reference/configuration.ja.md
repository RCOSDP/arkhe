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
| `ARKHE_ALLOWED_HOSTS` | `*` | カンマ区切り。**絞ると `Host` が一致しない要求を `400` で弾く**（既定の `*` では何も挟まない——前段で終端している構成では前段が見ているのが普通で、二重に弾くと切り分けが難しくなる） |

## データベース

| | 既定 | |
| --- | --- | --- |
| `ARKHE_DATABASE_URL` | `postgresql+psycopg://arkhe@localhost/arkhe` | |
| `ARKHE_READ_DATABASE_URL` | — | resolver 用の読み取り専用接続。未設定なら上と同じ |
| `ARKHE_DB_POOL_SIZE` | `5` | 1 プロセスが常に持つ接続。**worker 数と掛け算になる** |
| `ARKHE_DB_MAX_OVERFLOW` | `10` | 混み合ったときの上乗せ。`POOL_SIZE` に足される（既定で 1 プロセス最大 15） |
| `ARKHE_DB_POOL_RECYCLE` | `0` | 接続を作り直すまでの秒数。`0` で作り直さない。**接続を黙って切る前段の下では、その保持時間より短く** |

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
| `ARKHE_RESOLVE_UNPUBLISHED` | `false` | **公開前の ARK も解決する。閉域に置くリゾルバ向け。** 閉じた網の中で採番した ARK は、その網のリゾルバが解決できなければ配る意味が無い |

!!! danger "公開の面では開けない"
    `?info` と `??` は**認証を要さない口**である。ここを開けたリゾルバが公開の網から
    引けると、**まだ公開していない対象の存在・題名・行き先がそのまま出る**。
    開けてよいのは、届く範囲そのものが閉じているリゾルバだけ。

## 採番

| | 既定 | |
| --- | --- | --- |
| `ARKHE_BULK_LIMIT` | `1000` | 1 リクエストの件数。**それ以上は分割し、`request_id` を付ける**——切れた塊はそのまま再送してよい |
| `ARKHE_HOLD_MAX_DAYS` | `90` | 転送を止めておける最長日数。**期限を必須にしただけでは足りない**——「1 年後」と書けば恒久と変わらないので上限を置く。延ばすなら掛け直す（そのたびに監査に残る） |

## 前段がある場合

| | 既定 | |
| --- | --- | --- |
| `ARKHE_TRUSTED_PROXIES` | `0` | 前段（ロードバランサやプロキシ）を何段信じるか。**`X-Forwarded-For` は誰でも付けられるヘッダ**なので、既定では見ずに直接の接続元を記録する——詐称された値を記録するほうが害が大きい。監査ログに攻撃者の書いた文字列が並ぶのがいちばん困るため。前段が n 段あるなら `n` を入れる。**右から n 番目**を採る（右端は自分の直前の前段が書いた値なので信じられる）。左端を採ってはいけない——そこは client が書いた値 |
| `ARKHE_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING`。記録は JSON 行で、要求 id が入る |
