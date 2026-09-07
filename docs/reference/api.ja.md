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
| `/ark:99999/x9abc` | `302` で対象へ。行き先が無ければ記述を返す |
| `/ark:99999/x9abc/page/3` | `302` で *対象*`/page/3` へ。**suffix passthrough。子に識別子は要らない** |
| `/ark:99999/x9abc?` | ERC/ANVL の kernel（who / what / when / where） |
| `/ark:99999/x9abc??` | 上に加えて**永続性宣言** |
| `/ark:99999/x9abc?info` | 同じ内容を人に向けて |
| `/ark:99999/x9abc?json` | 同じ内容を機械に向けて |
| `/ark:12345/…`（未知 NAAN） | `302` でグローバルリゾルバへ |
| `/.well-known/ark` | `text/plain`。リゾルバのルートパス（末尾は `/`） |
| `/.well-known/ark`＋`Accept: application/json` | このリゾルバが何を預かっているか。採番を外に委ねているならその案内先 |

裸の `?` は、プロトコルの層でクエリ文字列なしと区別できない（**ASGI でも同じ**）。
前段が生の URI を渡せるなら `ARKHE_RAW_URI_HEADER` を設定する。

誤りには符号（`ARKHE-1011`）と英語の `message`、構造化された `detail` が付く。
**文面ではなく符号で判定すること**——一覧は[エラー](errors.md)にある。

### THUMP のヘッダと `where`

識別子について**リゾルバ自身が答える**応答——`?` `??` `?info` `?json`、行き先の無い
記述、保留、`404`——には §5.2 の 2 つのヘッダが付く。

```
THUMP-Status: 0.6 404 Not Found
Link: </ark:99999/x9abc>; rel="describes"
```

`Link` は、inflection を知らない受信者に対して「この応答は取得した URL の表現では
なく、**修飾の付いていない ARK を記述したもの**である」と示すためにある。仕様の
応答例は `<…> rel="describes";` と書いているが、これは
[RFC 8288](https://www.rfc-editor.org/rfc/rfc8288) のリンク値として不正なので、
arkhe は `<…>; rel="describes"` を出す——**同じことを、標準のパーサが読める形で
言う**。転送にはどちらも付けない。転送は識別子についての答えではなく、対象への誘導
だからである。

ERC の **`where` は ARK であって、転送先ではない**。§5.1.2 が「一時的な転送先では
なく長期的な識別子」と定めている要素で、**行き先を付け替えても `where` は動かない**
——それがこの要素の価値そのものである。今の行き先は kernel の外の `redirect` として、
あるときだけ出す。

### %-エンコードされた文字

予約文字（`%` `-` `.` `/`）は、**その予約された意味を隠す目的でなら** %-エンコード
してよい——`%2F` は「ここに `/` はあるが成分の区切りではない」と書く唯一の方法である。
したがって `ark:99999/x54%2Fc2` と `ark:99999/x54/c2` は**別の識別子**で、仕様は
エンコードされた文字が復号形で現れることを禁じている（`draft-kunze-ark-42` §3.2）。
arkhe は ASGI の `raw_path` から**エンコードを保ったまま**経路を読み、16 進の大小
だけ揃える（`%2f` → `%2F`。手順5）。復号はしない。

**前段もエンコードを素通しにすること。** nginx なら `proxy_pass` にパスを書かない
（`proxy_pass http://backend;`。書くと復号済みのものを再エンコードする）。Apache なら
`AllowEncodedSlashes NoDecode`。前段が `%2F` を潰す構成では復元できず、その種の名前は
解決できない。

### `/.well-known/ark`

`draft-kunze-ark-42` §5.6 は `ark` を Well-Known URIs レジストリ
（[RFC 8615](https://www.rfc-editor.org/rfc/rfc8615)）に登録し、応答を
**「リゾルバのルートパスを含む plain text、末尾は `/`」**と定めた——そこに
compact ARK を継ぎ足すと解決の要求になる、という約束である。**`Accept` を
送らない相手にも `*/*` の相手にもこれを返す**。ここで JSON を返すと、仕様どおりに
読む発見クライアントからは「このホストに ARK リゾルバは無い」に見える。

```console
$ curl https://ark.example.ac.jp/.well-known/ark
/
```

arkhe 独自の在庫——預かっている名前空間、委譲した shoulder とその `minter`、
止めている名前空間——は同じ URL の JSON 表現なので、名指しで求める:

```console
$ curl -H 'Accept: application/json' https://ark.example.ac.jp/.well-known/ark
```

どちらにも `Vary: Accept` が付く。パスは ASGI の `root_path` から採るので、
プレフィクス付きでマウントするなら設定すること（`uvicorn --root-path /pid`）
——さもないと、無い口を案内することになる。
