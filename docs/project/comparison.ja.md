# ほかの実装との比較

ARK を採番して解決するソフトウェアはほかにもある。それぞれが何をするのか、そのなかで
arkhe はどこに位置するのか、何を借りたのかを書く。

!!! note "いつ、何を見たか"

    **2026-09-19** 時点、以下の版で確かめた——
    [arklet](https://github.com/internetarchive/arklet) `08c2a6a`（2026-05-28）、
    [arklet-frick](https://github.com/frickdahl/arklet-frick) `4c7045d`（2024-05-01）、
    [EZID](https://github.com/CDLUC3/ezid) `78b31db`（2026-08-25）。**相手も動いている**
    ので、読む時点では古くなっている可能性がある。**実測**と書いたものは動かして得た結果、
    それ以外は読んだだけのもの。

いずれも実際に入れ、使い捨ての PostgreSQL を与え、**その実装自身の view に HTTP で
投げて**確かめた。読んで疑い、動かして確かめている。

## 機能単位の対応表

下の 4 列は踏み込んで見たもの——**arklet と arklet-frick は動かし**、EZID は読んだ。
剣印（†）は**読んだのではなく動かして確かめた**セル。

**✓** ある ／ **✗** 無い ／ **▲** 条件つきである ／ **—** 見当たらないが、無いとも確かめて
いない。

### 解決

| | arkhe | arklet | arklet-frick | EZID |
| --- | :-: | :-: | :-: | :-: |
| `ark:` を大小文字を問わず照合（A1） | ✓ | ✗† | ✗† | ▲ |
| ハイフンを無視（A2） | ✓ | ✗† | ✗† | ▲ |
| suffix passthrough | ✓ | ✗† | ✓ | ✓ |
| 登録済みの**最長**の祖先が勝つ（D5） | ✓ | ✗ | ✗† | — |
| `?info` | ✓ | ✗† | ✓ | ✓ |
| `?json` | ✓ | ✗ | ✓ | — |
| `??`（永続性の宣言） | ✓ | ✗ | ✗† | ✓ |
| 検査桁で誤写と 404 を見分ける | ✓ | ✗ | ✗† | — |
| 知らない NAAN を取り次ぐ | ✓ | ✓† | ✓† | — |

EZID の正規化は自身のコメントが「仕様の規則に従う。ただし shadow ARK のための例外あり」と
言っているので、この 2 つは ✓ ではなく ▲ にしてある。

### 採番と書き込み

| | arkhe | arklet | arklet-frick | EZID |
| --- | :-: | :-: | :-: | :-: |
| 採番の API | ✓ | ✓† | ✓† | ✓ |
| 一括採番 | ✓ | ✗ | ✓ | ✗ |
| **行が取り違わらない**一括更新 | ✓ | — | ✗† | — |
| 採番の冪等鍵 | ✓ | ✗ | ✗ | ✗ |
| 外で採番された ARK の取り込み | ✓ | ✗ | ✗ | ✓ |
| 部分更新（触れない項目は残る） | ✓ | ✗ | ✓ | ✓ |
| 全置換（渡さない項目は消える） | ✓ | ✓ | ✗ | ✓ |

arklet-frick は**要求に無い項目を落とす**ので、更新は常に部分更新であり、**項目を空にする
手段が無い**。arkhe は同じエンドポイントで両方持つ——`PUT` は置き換え、`PATCH` は置き換え
ない。

### 識別子の一生

| | arkhe | arklet | arklet-frick | EZID |
| --- | :-: | :-: | :-: | :-: |
| 公開せずに採る（reserved） | ✓ | ✗ | ✗ | ✓ |
| 公開を取り下げる | ✓ | ✗ | ✗ | ✓ |
| 公開後は削除を断る | ✓ | — | — | ✓ |
| tombstone | ✓ | ✗ | ✗ | ✓ |
| 期限つきで転送を保留する | ✓ | ✗ | ✗ | ✗ |
| 取り下げた名前を二度と割り当てない | ✓ | ✗ | ✗ | — |

arklet も arklet-frick も**削除の口そのものが無い**ので、ここは ✓ ではなく —。API からは
消せず、別の道で消したときにどうなるかも書かれていない。

### 認可と運用

| | arkhe | arklet | arklet-frick | EZID |
| --- | :-: | :-: | :-: | :-: |
| 資格情報の届く範囲 | NAAN・組織・shoulder の 3 段 | NAAN | NAAN | アカウントとグループ（共同所有） |
| 資格情報の保存 | Argon2。接頭辞で引いて 1 回だけ | SHA256 1 回。**平文で持つモデルも現役** | Argon2。ただし**その NAAN の全鍵を試す** | Django のパスワードハッシュ |
| 採番を別の minter に委譲（307） | ✓ | ✗ | ✗ | ✗ |
| minter と resolver を分けて建てる | ✓ | ✗ | ✓ | ▲ |
| 監査ログ | ✓ | ✗ | ✗ | ▲ |
| 管理画面 | ✓ | ✓（Django admin） | ✓（Django admin） | ✓ |
| 画面と CLI が 2 言語 | ✓ | ✗ | ✗ | ✗ |
| 実装から生成する OpenAPI | ✓ | ✗ | ✗ | ✗ |
| 同じプロジェクトのクライアント | ✓ | ▲（取込 CLI） | ▲（CLI） | — |

### そのほかの実装（粗く）

こちらは表層——ルーティング・モデル・README——を読んだだけで動かしていないので、言えることは
少ない。

| | AMS | greens | arks-service | NOID 系 | N2T |
| --- | :-: | :-: | :-: | :-: | :-: |
| 解決 | ✓ | ✓ | ✓ | ✗ | ✓ |
| `ark:` を大小文字を問わず照合 | ✓ | — | — | — | ✓ |
| `?info` / `??` | ✓（ERC テキスト） | — | — | ✗ | ▲ |
| suffix passthrough | ✓（NAAN ごと） | — | — | ✗ | ✓ |
| 機械向けの採番 API | ✗（画面と CSV） | ✓ | ▲（管理画面の口） | ✗（ライブラリ） | ✗ |
| 1 つの設置で複数 NAAN | ✓ | ✗ | ✓ | 対象外 | ✓ |
| 解決を止める状態 | ✓（ARK ごとに HTTP ステータス） | — | — | ✗ | ✗ |
| 公開後は削除を断る | — | ✗（`DELETE` で消える） | — | 対象外 | 対象外 |

## arklet（Internet Archive）

Django、約 1,500 行。操作は採番・更新・解決の 3 つ。arkhe の仕様層はここから派生している
（[由来](../index.ja.md)）ので、いちばん近い親戚にあたる。

| 投げたもの | 返ってきたもの | |
| --- | --- | --- |
| `PUT /update` | **`TypeError: QuerySet.select_for_update() got an unexpected keyword argument 'ark'` → 500** | 実測 |
| `GET /ARK:/…` | **404**——ラベルを大文字小文字を区別して照合している | 実測 |
| 名前の途中にハイフンを入れた `GET /ark:/99999/x9tn1qkq2g7` | 302 で NAAN 自身の URL へ。知らない名前として扱われる（ハイフンを除去していない） | 実測 |
| `GET …?info` | 302 で行き先へ。インフレクションが無い | 実測 |
| `GET …/a-part` | 302 で行き先へ。**suffix は落ちる** | 実測 |
| `POST /mint` | 通る。返るのは古い `ark:/` 形式 | 実測 |

テストは採番だけを見ており、更新は 1 本も無い。**壊れた更新がリリースに乗るのはそこ**。
ほかに: NAAN を `int()` に通すので betanumeric NAAN と先頭 0 は表せない。認可は NAAN 単位
なので、鍵を持つ者はその NAAN の**どの ARK でも書ける**。さらに、鍵を**平文で保持する**
旧 `Key` モデルがハッシュ版と並んで現役で受け付けられている。

こちらの文書のほうも 1 つ直す必要がある: 主キー衝突が `UPDATE` に化けるという
[不変条件](../concepts/invariants.ja.md)が挙げている欠陥は、**本家では既に直っている**。
現在の arklet は `IntegrityError` を捕まえて別の名前を引き直す。

## arklet-frick（Frick Collection）

フォーク、約 2,000 行。親より明確に進んでいる——minter と resolver を別に建てられ、
一括の採番・更新・照会があり、suffix passthrough、`?info` と `?json`、API キーの Argon2
ハッシュ、shoulder の実在検査、そして各項目に Dublin Core のプロパティを添える `?json`。

動かすと 4 つ出た。

| やったこと | 起きたこと | |
| --- | --- | --- |
| 5 件を呼び出し側の順で一括更新 | **5 件中 4 件が別レコードのタイトルを持った**。応答は `{"num_updated": 5}` | 実測 |
| base と `…/sub` の両方が登録された状態で `…/sub/leaf` を解決 | **最短**の祖先が勝った。仕様が求めるのは最長一致 | 実測 |
| 任意の ARK を解決 | 行き先の末尾に `?` が付いた | 実測 |
| `…??` を解決 | `<行き先>??` へ 302。**永続性の宣言が返らない** | 実測 |
| ハイフン入り、検査桁違いを解決 | 知らない名前として外へ取り次いだ | 実測 |

重いのは 1 つめ。`filter(ark__in=…)` の**順序が定まらない**結果を入力と `zip` している。
しかも**黙って**起きる——応答は全件成功と言う。**識別子を採り直せない台帳で、別の識別子に
書き込まれるのは最悪の結果**であり、arkhe の一括操作が
[行ごとに ARK を鍵にし](../reference/api.ja.md)、1 行でも到達範囲の外なら**全体を落とす**
のはそのため。

認可は親と同じく NAAN 単位で、しかもリクエストごとに**その NAAN の全アクティブ鍵を
Argon2 で順に照合する**。鍵の数に比例して重くなる。arkhe が
[接頭辞で鍵を引いて 1 回だけハッシュする](../guides/authentication.ja.md)のはこのため。

## そのほかの実装

| | 何か | 言語 | 現況 |
| --- | --- | --- | --- |
| [EZID](https://github.com/CDLUC3/ezid)（CDL） | ARK **と DOI** の識別子サービス。DataCite / Crossref 登録、OAI-PMH、検索画面、一括ダウンロードまで | Python/Django 約 42,000 行 | 活発。最大 |
| [N2T](https://github.com/CDLUC3/N2T)（CDL） | スキーム横断の全体解決器。minter ではない | Python | 活発。arkhe が知らない NAAN を取り次ぐ先 |
| NOID 系（[pynoid](https://github.com/no-reply/pynoid)、[noid](https://github.com/emdb-empiar/noid)、[noid.js](https://github.com/viaacode/noid.js)） | **採番アルゴリズムだけ**。台帳も解決も持たない | Perl / Python / JS | ライブラリ。2018 年で止まったものもある |
| [arks-service](https://github.com/digitalutsc/arks-service)（UTSC） | 採番・一括 bind・解決と画面 | PHP（Noid4Php 基盤） | 2026-04 更新 |
| [AMS](https://github.com/burgerbibliothek/AMS)（Burgerbibliothek） | 採番・管理画面・CSV 取込・ERC メタデータ | PHP/Laravel | 2026-09 更新。破壊的変更ありと明記 |
| [greens](https://github.com/uhlibraries-digital/greens)（U. Houston） | 採番と解決 | Ruby/Rails | 2023 で停止 |
| Omeka / Drupal / OJS / ArchivesSpace のプラグイン | 既存システムの中で ARK を扱う | PHP ほか | 単体の基盤ではない |

**考え方がいちばん近いのは EZID。** 識別子は `reserved` / `public` / `unavailable` の
状態を持ち、unavailable は tombstone のページへ解決し、**reserved でなければ削除を断る**
（superuser を除く）。ここの[公開ライフサイクル](../concepts/invariants.ja.md)と同じ筋で、
しかも何年も先にそこへ着いている。

## arkhe の位置

**arkhe 独自と言えるもの**（上のどれにも見当たらなかった）:

- **shoulder 単位の採番委譲を `307` で返す**。代理では採らない（[委譲の構造](../concepts/delegation.ja.md)）
- **期限つきの転送の保留**。解決は止めない
- **採番の冪等鍵**。応答が失われても番号を消費しない
- **3 段の到達範囲**——認可が NAAN 単位で止まらず、組織で止まる
- 監査ログと、行き先の変更の全件記録
- 取り下げた名前を二度と割り当てない
- 実装から生成する OpenAPI と、それと突き合わせる [Python クライアント](../guides/python-client.ja.md)
- 管理画面と CLI が 2 言語
- **本番の形で建てて HTTP 越しに叩く通しの検査**

**借りたもの、後から着いたもの**: 公開ライフサイクルは EZID の status モデルの言い換え。
suffix passthrough と `?info` / `?json` は arklet-frick が先。採番アルゴリズムと検査桁は
NOID 由来（arklet 経由）。

**arkhe がやらないこと**: DOI と DataCite / Crossref への登録、OAI-PMH、検索画面や一括
ダウンロード、NOID テンプレート互換、そしてスキーム横断の解決——最後のものは N2T の仕事で、
arkhe はそこへ取り次ぐ。

## 取り込む価値がありそうなもの

- **arklet-frick の `?json`**。各項目に Dublin Core のプロパティ URI を添えている。
  arkhe の `?json` は値だけなので、**外の読み手は `who` と `when` の意味を知っている必要が
  ある**。
- **EZID の共同所有**。1 つの識別子を複数のアカウントが書ける。arkhe は ARK を 1 つの組織に
  結びつけており、そのぶん単純で厳しい。共有は**到達範囲の設計に触る**ので、機能ではなく
  判断の問題になる。
