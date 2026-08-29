# API

以下の仕様は**実装からビルド時に生成**している。サーバの実際の振る舞いと食い違うことが
ない。

稼働中のインスタンスも同じものを出す。Swagger UI は `/api/docs`、ReDoc は
`/api/redoc`、生の文書は `/api/openapi.json`。

## 役割ごとに開く口

**minter に解決の口は無く、resolver に採番の口も無い。** 別プロセスなので別々に
スケールでき、resolver は読み取り専用のレプリカに向けられる。

=== "minter + 管理画面"

    <div class="api-frame" markdown>
    <iframe src="../../assets/swagger.html?spec=openapi-minter.json" loading="lazy"></iframe>
    </div>

    [生の文書を開く](../assets/openapi-minter.json)

=== "resolver"

    <div class="api-frame" markdown>
    <iframe src="../../assets/swagger.html?spec=openapi-resolver.json" loading="lazy"></iframe>
    </div>

    [生の文書を開く](../assets/openapi-resolver.json)

## スキーマからは読み取れないこと

**採番は、頼めば冪等になる。** `request_id` を付けて送れば、同じ要求の再送には
**前回と同じ ARK** が返り、新しくは採らない。万オーダーの投入では途中で接続が切れる
ほうが普通で、控えが無いまま再送すると**誰も指していない識別子**が増える——ARK は
それを回収できない。

**リクエストの shoulder は範囲を広げない。** 省略すれば組織の既定が使われ、名指した
場合に問われるのは「それが自分の範囲の内側かどうか」だけ。

**委譲された shoulder は 307 を返す。プロキシはしない。** その名前空間の採番が外で
行われるなら、行き先を教える。代理で呼ばないのは、応答が失われたときに
**向こうでは採番されたがこちらは知らない ARK** が生まれるから。

**一括操作は部分適用しない。** 一括更新の 1 件でも欠けるか範囲外なら、全体が失敗する。
arklet は順序不定の問い合わせ結果を入力と `zip` しており、**別のレコードの値を書き込み
うる**バグがあった。

## 解決

解決は OpenAPI では十分に表せない——1 本の経路で、接尾によって振る舞いが変わるため。

| 要求 | 応答 |
| --- | --- |
| `/ark:/99999/x9abc` | `302` で対象へ。行き先が無ければ記述を返す |
| `/ark:/99999/x9abc/page/3` | `302` で *対象*`/page/3` へ。**suffix passthrough。子に識別子は要らない** |
| `/ark:/99999/x9abc?` | ERC/ANVL の kernel（who / what / when / where） |
| `/ark:/99999/x9abc??` | 上に加えて**永続性宣言** |
| `/ark:/99999/x9abc?info` | 同じ内容を人に向けて |
| `/ark:/99999/x9abc?json` | 同じ内容を機械に向けて |
| `/ark:/12345/…`（未知 NAAN） | `302` でグローバルリゾルバへ |
| `/.well-known/ark` | このリゾルバが何を預かっているか。採番を外に委ねているならその案内先 |

裸の `?` は、プロトコルの層でクエリ文字列なしと区別できない（**ASGI でも同じ**）。
前段が生の URI を渡せるなら `ARKHE_RAW_URI_HEADER` を設定する。
