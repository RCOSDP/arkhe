# Python クライアント

リポジトリの `clients/python` は、この文書が説明している API の Python クライアント。
minter と resolver のすべてのエンドポイントを持ち、**API 文書には書けない判断を 3 つ**
代わりに行う。

```bash
pip install ./clients/python
```

Python 3.11 以上、依存は `httpx` ひとつ。

## 採番する

```python
from arkhe_client import Arkhe

with Arkhe("https://mint.example.org", token="arkhe_...") as arkhe:
    ark = arkhe.mint(url="https://repo.example.ac.jp/records/42", title="A dataset")
    print(ark.ark)          # ark:99999/x9tn1qkq2g7
    print(ark.published)    # True——reserve を付けない採番はその場で公開される
```

`token=` には API キーか、よそで得たトークンを渡す。arkhe 自身のトークン発行口を使うなら
client_id と client_secret を渡す。最初に必要になったときに取りに行き、期限が来たら取り直す。

```python
Arkhe("https://mint.example.org", client_id="ops", client_secret="arkhes_...",
      scope="ark:mint ark:read")
```

どちらが通るかは `ARKHE_AUTH` 次第。[認証](authentication.ja.md)を参照。

## 応答が失われても番号を消費しない

**採番は取り消せない**ので、`mint()` は必ず冪等鍵を載せ、再送では同じ鍵を送る。サーバは
新しく採らず、最初に採った ARK を返す。

```python
ark = arkhe.mint(url="https://repo.example.ac.jp/records/42")
ark.resent      # True なら、これは最初の採番が返ってきたもの
```

鍵は渡さなければ自動で生成される。これで 1 回の呼び出しの中の再送は守られる。**自分で渡す
価値があるのは、採番する対象の側に残る鍵**——レコード id やジョブ id——で、1 時間後や
翌日の再送も同じ要求だと分かる。

```python
arkhe.mint(url=record.url, request_id=f"record-{record.id}")
```

`mint_many()` は各行に鍵を置く。これが**途中で切れた一括採番をそのまま送り直せる**理由で、
通っていた行は二重に採られず、そのまま返る。

再送しても二重に効かない呼び出しだけを再送する。それ以外は `TransportError` になり、判断は
呼び出し側に残る。**応答が無い場合、書き込みが起きたかどうかは分からない**ため。

## 委譲は「行き先を返す」だけで、追わない

採番が委譲された shoulder では、サーバは `307` と `Location` で別の minter を返す
（[委譲の構造](../concepts/delegation.ja.md)）。**このクライアントはそれを追わない。**
資格情報は自分の組織のものであり、向こうで採られた ARK はこちらの台帳が知らない ARK になる。

```python
from arkhe_client import Delegated

try:
    arkhe.mint(url=record.url, shoulder="/z1")
except Delegated as elsewhere:
    elsewhere.minter    # 行き先。叩ける口が無ければ None
    elsewhere.about     # 案内のページ（委譲側が持っていれば）
```

## 断りにはコードが付く

```python
from arkhe_client import Conflict, Throttled

try:
    arkhe.delete(ark.ark)
except Conflict as refused:
    refused.code        # "ARKHE-1501"——**変わらないのはこちら**
    refused.detail      # 文面の裏にある値
except Throttled as capped:
    capped.retry_after  # サーバが言っていれば、秒数
```

すべての基底は `ArkheError`。`BadRequest` / `Unauthorized` / `Forbidden` / `Delegated` /
`NotFound` / `Conflict` / `Throttled` / `ServerError` / `TransportError` がある。
コードの一覧は[エラー](../reference/errors.ja.md)。

## 解決する

resolver は資格情報を要らないので、別のオブジェクトにしてある。

```python
from arkhe_client import Resolver

with Resolver("https://ark.example.org") as resolver:
    found = resolver.resolve("ark:99999/x9tn1qkq2g7")
    found.target            # 転送先
    found.description       # 転送しなかったときは、代わりに返ってきた記述
```

**転送だけが成功ではない。** 公開前の ARK、転送を保留した ARK、tombstone を立てた ARK は
いずれも記述を返して解決し、そのとき `target` は `None` になる。`describe()` は `?json` で
訊くので決して転送せず、`statement()` は `??` で「この台帳が何を約束しているか」を訊く。

## ほかにあるもの

| | |
| --- | --- |
| 採番 | `mint`, `mint_many`, `register` |
| 取り込み | `import_ark`, `import_many` |
| 書き換え | `update`（置き換え）, `patch`（渡した分だけ）, `update_many` |
| 公開と取り下げ | `publish`, `unpublish`, `delete`, `purge` |
| 失われたと告げる | `tombstone` |
| 転送の保留 | `hold`, `release_hold` |
| 読み | `query`, `stats` |
| 解決 | `Resolver.resolve`, `describe`, `statement`, `inventory`, `exists` |

`update()` は置き換え、`patch()` は渡した分だけ。同じエンドポイントなので取り違えても
静かに通る。`unpublish()` `delete()` `purge()` は `confirm` を取るが、**クライアントは
これを代わりに埋めない**。サーバは ARK と突き合わせており、一覧をなぞるスクリプトが
公開済みの名前を落とせないようにするための検査だから、埋めてしまえばその検査は消える。

## なぜ生成ではなく手書きか

[OpenAPI 文書](../reference/api.ja.md)は実装から生成されていて、インタフェースの記述は
そこ 1 つ。だから生成が素直に見える。**生成が与えるのは網羅で、網羅は検査できる部分**——
`clients/python/tests/test_contract.py` がクライアントと OpenAPI 文書を両方向で突き合わせる
ので、サーバにエンドポイントが増えるとビルドが落ち、「クライアントも持つべきか」を決める
場面になる。

**生成が与えられないのが上の 3 つの判断**で、それがこれの存在理由。

判断の部分はスタブに対して、それがサーバの実際と合っているかは本物の minter と resolver に
対して確かめている。

```bash
uv run pytest -q clients/python/tests          # 速い
uv run pytest -q -m e2e -k python_client       # docker が要る
```

## 他の言語

Python 以外のクライアントはまだ無い。作るなら `docs/assets/openapi-minter.json` から生成し、
**同じ 3 つを手で足す**——採番の冪等鍵、`307` を追わないこと、断りに `ARKHE-xxxx` を載せること。
**識別子を採り直せない台帳に向けるクライアントを安全にしているのはその 3 つ**。
