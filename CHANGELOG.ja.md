# 変更履歴

*[English](CHANGELOG.md)*

書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)、版は
[SemVer](https://semver.org/lang/ja/)。**識別子を振り直せない体系で何を破壊的変更と
みなすか**は[方針](https://rcosdp.github.io/arkhe/ja/project/versioning/)にある。

## [未リリース]

## [0.0.2] — 2026-08-28

すべて、0.0.1 を Kubernetes と compose に実際に載せて出たもの。テストでは 1 つも
出ていない——4 件とも「コードが正しい」と「デプロイできる」の間に落ちていた。

### 修正

- `/healthz` をどのモードでも載せた。resolve ルータにしか無かったので、minter と
  admin は liveness probe に 404 を返し続け、繰り返し殺されていた。
- resolver に認証設定を要求しないようにした。認証を通す口も管理画面も無いのに、
  起動時に `ARKHE_SESSION_SECRET` と OIDC の設定を求めていた——使いもしない
  セッション署名鍵を、解決系の全ノードに配らせていたことになる。
- shoulder を指定した主体が機関を継ぐようにした。`--shoulder` だけ渡すと
  manager が空のまま作られ、認可の入口で必ず弾かれていた。しかも「shoulder は
  合っているのに通らない」という追いにくい形で。shoulder と食い違う `manager` を
  明示した場合は、黙ってどちらかを優先せず拒む。
- ラベルの一意性は、ラベルがあるときだけにした。`(manager_id, label)` の一意制約に
  空文字が含まれていたため、1 機関にラベル無しの主体を 1 つしか置けなかった。
  プロセスごとに鍵を分ける普通の構成（`web-api` / `web-ui` / `worker`）が通らず、
  鍵を共有させる圧力になっていた。移行は `56e5e54db345`。
- compose のブラウザログインが `invalid_scope: openid profile email` で落ちていた。
  realm の import で `clientScopes` を宣言すると Keycloak 組み込みの一式は追加では
  なく置き換えになるため、`profile` と `email` が realm に存在していなかった。

### 変更

- デモ realm の `defaultDefaultClientScopes` から `arkhe-api` を外した。realm の
  既定に入れていたので、**後から作ったどんなクライアントでも** arkhe 宛だと名乗れる
  トークンを取れた。audience は「このトークンがどの API 向けか」の宣言であって、
  既定で配るものではない。
- compose の resolver を独立したサービス（`:8058`）にした。デプロイ時と同じ形に
  なるうえ、Keycloak を止めると採番が 401 になり解決は 302 のままであることが、
  そのまま見える。

## [0.0.1] — 2026-08-28

最初のタグ。プレリリースであり、**版が `0` で始まる間は MINOR が破壊的変更を運ぶ。**

### 追加

- ARK の採番と解決。`?` / `??` / `?info` / `?json` の inflection、suffix passthrough、
  検査桁、未知 NAAN のグローバルリゾルバへの取次。
- 3 段の委譲（`system` / `naan` / `manager`）。ARK が名前空間を受け渡す構造の写しで、
  **配られた側が配った側より広く届くことはない。**
- API の認証 3 機構（`apikey` / `oauth2` / `oidc`）。排他ではなく個別に有効化でき、
  どれで認証しても `Principal` 1 つに集約される。
- 管理画面への入口 4 種類（`bearer` / `password` / `oidc` / `proxy`）。
- 操作ベースの管理画面（日英）。テーブルの行編集は持たない——行編集はドメインの
  禁則を素通りするため。
- 承継と離脱。どちらも**既存の識別子は解決し続ける。**
- 冪等な採番。同じ `request_id` の再送には、前回と同じ ARK を返す。
- ドキュメントサイト（日英、一部は実装から生成）。

### 備考

- Django から FastAPI + SQLAlchemy 2.0 へ書き直した。仕様の層（`arkspec/`、
  `domain/resolution.py`）は無改造で運べ、**97 本のテストがそのまま通った。**
- `arkspec/` の一部は Internet Archive の arklet（MIT）から派生。NOTICE を参照。

[未リリース]: https://github.com/RCOSDP/arkhe/compare/v0.0.2...HEAD
[0.0.2]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.2
[0.0.1]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.1
