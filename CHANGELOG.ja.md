# 変更履歴

*[English](CHANGELOG.md)*

書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/)、版は
[SemVer](https://semver.org/lang/ja/)。**識別子を振り直せない体系で何を破壊的変更と
みなすか**は[方針](https://rcosdp.github.io/arkhe/ja/project/versioning/)にある。

## [未リリース]

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

[未リリース]: https://github.com/RCOSDP/arkhe/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.1
