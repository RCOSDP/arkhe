# エラー

この API が返す誤りには**符号**が付く。文面は変わりうる（分かりやすく直る、訳が
変わる）が、符号は変わらない。**文面ではなく符号で判定すること。**

```json
{
  "code": "ARKHE-1011",
  "message": "A request holds at most 1000 rows.",
  "detail": {"limit": 1000}
}
```

`detail` には文面を埋めた値が**構造化されたまま**入る。数字を文から切り出させない
ためである。

解決の口は `text/plain` で答える（人も読む）。**符号を行頭に置く。**

```
ARKHE-1403 ark:99999/x9abcd — Check digit mismatch: the identifier looks mistranscribed.
```

2 か所だけ意図して形が違う。**`/oauth/token` は
[RFC 6749](https://www.rfc-editor.org/rfc/rfc6749) §5.2 に従う**——`error` と
`error_description` で読むと決まっており、OAuth のクライアントライブラリもそう
読む——ので、符号はその形を崩さずに併記する。**管理画面**は自前の catalogue から、
**画面の言語**で答える（`?lang=` → cookie → `Accept-Language`）。あちらはブラウザの
画面で、この API ではない。

| 符号 | 状態 | 意味 | 応答本文（英語） |
| --- | --- | --- | --- |
| `ARKHE-1001` | 400 | ARK として読めない。ラベル・NAAN・名前のいずれかが仕様に合わない | Not readable as an ARK: {reason} |
| `ARKHE-1002` | 400 | 修飾子は `/`（包含）か `.`（変種）で始める。ほかの文字では始められない | A qualifier must begin with '/' (a part) or '.' (a variant). |
| `ARKHE-1003` | 400 | 修飾子が base を指していない。base の内側にある部分参照でなければならない | The qualifier does not point inside the base name: {qualifier} |
| `ARKHE-1004` | 400 | 名前が長すぎる。仕様が受け取る側に義務づける 255 オクテットまでを索引できる | The name is {length} octets; at most {limit} are indexed (Base Name plus Qualifier, draft-kunze-ark-42 §3.1). |
| `ARKHE-1005` | 400 | 既に登録済み。**黙って上書きしない**——書き換えるなら update を使う | {ark} is already registered. |
| `ARKHE-1006` | 400 | ブラウザに解釈させると危ないスキームは行き先にできない。`urn:` `doi:` などは通る（空も正当） | A target must not use a scheme a browser would execute ({schemes}). |
| `ARKHE-1007` | 400 | NAAN 単位以上の主体は shoulder を明示する。既定を持たせないのは誤爆を防ぐため | A principal with authority={authority} must name a shoulder. |
| `ARKHE-1008` | 400 | その shoulder は存在しない | No such shoulder: {shoulder} |
| `ARKHE-1009` | 400 | 同じ shoulder が複数の NAAN にある。**どれか 1 つを勝手に選ばない** | Shoulder {shoulder} exists under more than one NAAN; name the naan as well. |
| `ARKHE-1010` | 400 | 組織に default_shoulder が設定されていない | The organisation has no default shoulder. |
| `ARKHE-1011` | 400 | 1 リクエストの件数上限（`ARKHE_BULK_LIMIT`）を超えた | A request holds at most {limit} rows. |
| `ARKHE-1201` | 401 | 資格情報が無い。**公開情報の読取には要らない**ので、これは書き込みの口 | No credentials. |
| `ARKHE-1202` | 401 | 資格情報が受け付けられない。有効な機構は `ARKHE_AUTH` で決まる | Invalid credentials. |
| `ARKHE-1203` | 404 | この構成は自前でトークンを発行しない。**口の無い構成で広告しない**ため 404 | This deployment does not issue tokens itself (see ARKHE_AUTH). |
| `ARKHE-1204` | 400 | 対応していない grant_type。**実装しないものは明示して返す** | Only client_credentials is supported. |
| `ARKHE-1301` | 403 | トークンに要求された scope が無い。**scope は narrow できても広げられない** | The token does not carry the required scope: {scope} |
| `ARKHE-1302` | 403 | 到達範囲の外。範囲は資格情報の登録属性で決まり、リクエストでは広がらない | Outside this principal's registered reach: {target} |
| `ARKHE-1303` | 403 | 主体に有効な組織が紐づいていない | The principal has no active organisation. |
| `ARKHE-1304` | 403 | その shoulder は今の状態では採番できない（`retired` / `reserved` など） | Shoulder {shoulder} has status={status} and cannot be minted into. |
| `ARKHE-1305` | 403 | そのクライアントに許可されていない scope を要求した。**本文は RFC 6749 §5.2 の形**（`error` / `error_description`）で、符号は併記 | Scopes not allowed for this client: {scopes} |
| `ARKHE-1306` | 307 | その shoulder の採番は外に委譲されている。**代理では呼ばない**——応答が失われると「向こうにはあるがこちらは知らない ARK」が生まれる | Minting for shoulder {shoulder} is delegated; go to the minter in Location. |
| `ARKHE-1401` | 404 | 台帳にその ARK が無い（一括操作では 1 件でも欠ければ全体が失敗する） | No such ARK in this ledger. |
| `ARKHE-1402` | 404 | その NAAN はこのリゾルバが権威を持つ。**だから「無い」と言い切れる** | This resolver is authoritative for the NAAN and has no such name. |
| `ARKHE-1403` | 404 | 検査桁が合わない。**打ち間違い・転記ミスの疑い**（NOID の NCDA が単一文字誤りと隣接転置を検出する） | Check digit mismatch: the identifier looks mistranscribed. |
| `ARKHE-1404` | 404 | 知らない NAAN について述べられることは無い。inflection 無しなら上位リゾルバへ取り次ぐ | Metadata for an unknown NAAN is not held by this resolver. |
| `ARKHE-1601` | 429 | 1 日の採番上限に達した（組織ごとの `quota_per_day`） | Daily quota exhausted: {used} of {quota} used in the last 24 hours. |
