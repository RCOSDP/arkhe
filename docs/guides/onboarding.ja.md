# はじめて立ち上げるとき

NAAN を持っていない状態から、組織が採番できる状態までの通し。**arkhe の外で
起きることが半分を占める**ので、そこも含めて並べる。

```
① ARK Alliance に NAAN を申請する          arkhe の外
② arkhe を立てる                            → デプロイ
③ NAAN registry に解決先の URL を登録する   arkhe の外
④ arkhe に NAAN を登録し、方針を述べる       arkhe naan add
⑤ 組織を迎え、名前空間を委譲する             arkhe onboard
⑥ 組織の約束の水準を確かめる                 arkhe manager commitment
⑦ 人と機械を登録する                         arkhe client add
⑧ 以後：ローテーション・承継・離脱
```

## ① NAAN を申請する

ARK Alliance から**無償で**交付される。登録組織に払う金も、維持する会員資格も無い。

申請には、その NAAN で何をするつもりかを述べる欄がある。**ここで書いたことが
④ 以降で台帳に載る内容と一致していなければならない。** 別々に考えると、外向きの
宣言と実際の運用がずれる。

## ② arkhe を立てる

[デプロイ](deployment.md)を見ること。**③ の前に立てる**必要がある——③ で登録するのは
このリゾルバの URL だからである。

## ③ NAAN registry に解決先の URL を登録する

**ここが抜けると `n2t.net/ark:/99999/…` は自分のところに届かない。** NAAN の交付は
番号をもらって終わりではなく、registry のエントリに自分のリゾルバの URL を書くまでが
一続きである。

リゾルバの URL が変わったら**そのたびに更新する**。ここは自動では追随しない。

!!! note "自分の側でも公開している"
    arkhe は `/.well-known/ark` で、その NAAN の採番をどこで行っているかを返す。
    registry の代わりにはならない（外から見つけてもらう経路は registry だけ）が、
    採番の窓口が別にある構成では、クライアントがどこへ行けばよいか分かる。

## ④ NAAN を登録し、方針を述べる

```bash
arkhe naan add 99999 "○○大学" \
  --policy "NP | NR, OP, CC | 2026 | https://example.ac.jp/ark-policy"
```

**NAA ポリシーを述べるのはここ。** 事務手続きではなく、arkhe にとって中心的な宣言で
ある——ARK には代わりに永続性を保証してくれる登録組織がいないので、[約束はこちらの
もの](../concepts/ark.md)であり、その中身も自分で述べるしかない。述べていないものは
`??` で答えられない。

`--authoritative`（既定）は「この NAAN の未知の名前には `404` と答えてよい」という
意味である。**採番を他所が続けている NAAN を引き受けた場合は** `--authoritative false`
と `--redirect` を付ける。この 2 つは対で、片方だけでは登録できない。

## ⑤ 組織を迎え、名前空間を委譲する

```bash
arkhe onboard 99999 "○○研究所" --shoulder /x9 --commitment permanent-stable
```

**組織の登録と shoulder の委譲は必ず対で起きる。** 分けられない——名前空間を持たない
組織は採番できないので、台帳に置く意味がない。

shoulder の設計は先に決めておくこと。**一度配ったら取り戻せない**（`NR` を宣言して
いる以上、既存の ARK は解決し続ける）。使わなくなった名前空間は消すのではなく
`retired` にする。

```bash
arkhe shoulder add 99999 /y2 --reserve   # 将来のために押さえるだけ
arkhe shoulder list --naan 99999
```

## ⑥ 約束の水準を確かめる

```bash
arkhe manager commitment --list
arkhe manager list
arkhe manager commitment 1 permanent-stable
```

**管理画面からも変えられる**（一覧の組織行の「操作」）。ここは
[組織管理者自身も変えられる](admin.md#設定を変える)——約束は組織自身のもので、
述べる主体が述べられなければ意味がない。

`--commitment` を付けずに迎えると既定の `permanent-dynamic` が付く。**既定のまま
置いてはいけない。** この値は `?` と `??` でそのまま公開されるので、放置すると
**組織が述べていない約束を、組織の名前で名乗る**ことになる。宣言していないものを
宣言として出すのは、何も出さないより悪い。

水準は NLM の permanence ratings を採っている（`descriptive-only` だけは物理
オブジェクト向けの追加）。

| | |
| --- | --- |
| `not-guaranteed` | 約束しない |
| `permanent-dynamic` | 永続。内容は変わりうる |
| `permanent-stable` | 永続。内容は実質的に変わらない |
| `permanent-unchanging` | 永続。内容は変えない |
| `descriptive-only` | 記述だけ（物理オブジェクトなど、対象がオンラインに無い） |

**水準を下げるのも正当な操作である。** 守れない約束を掲げ続けるより、実態に合わせて
言い直すほうが誠実で、`??` を尋ねる意味も保たれる。

## ⑦ 人と機械を登録する

**この 2 つは混ぜられない。**

| | 名乗り方 | 持てる資格情報 |
| --- | --- | --- |
| 人（組織管理者など） | 外部ログイン（OIDC / proxy）またはパスワード | API キー・client_secret は**持てない** |
| 機械（リポジトリ本体など） | API キー / client_secret | パスワードは**持てない** |

```bash
# 組織管理者。client_id は認可サーバが返す識別子（メール・eppn など）
arkhe client add admin@example.ac.jp 99999 --person --manager 1

# リポジトリ本体。shoulder に固定する
arkhe client add repo-web-api 99999 --shoulder 1 --scopes "ark:mint ark:update"
arkhe client key repo-web-api          # 平文はこの一度だけ
```

人に API キーを配らないのは、**その人が組織を離れても鍵が生き残る**からである。人の
失効は認可サーバ側で行い、arkhe はそれに従う。`arkhe client passwd` は
`ARKHE_ADMIN_LOGIN=password` の構成でだけ使う。

**プロセスごとに鍵を分けること。** リポジトリの web / worker などで共有すると、
(1) どれが採番したか追えない (2) 1 つ漏れたら全部を失効させるしかない
(3) 用途ごとに scope を絞れない。`--shoulder` で固定しておけば、鍵が漏れても他組織の
名前空間には届かない。

最後に設定を確かめる。

```bash
arkhe check
```

### 認可サーバに寄せた構成では、登録が紐付けになる

`ARKHE_AUTH=oidc` の構成では、arkhe は**鍵を持たない**。秘密は認可サーバが作り、
そこで失効させる——失効が 1 か所で効くのがこの形の利点である。

**それでも登録は要る。** 認可サーバで認証できることと、この名前空間を触ってよい
ことは別だからで、台帳に無い主体は正しいトークンを持っていても通らない。

| どこで | 何を |
| --- | --- |
| 認可サーバ | クライアントを作り、秘密を発行・失効させる |
| arkhe | 同じ識別子で利用者を登録し、組織・名前空間・できることを決める |

識別子は**認可サーバが送ってくる文字列そのまま**でなければならない。

| | 照合の順 |
| --- | --- |
| 機械 | `azp` → `client_id` → `sub` |
| 人 | `preferred_username` → `email` → `sub` |

```bash
arkhe client add jc2-web-api 99999 --shoulder 1 --scopes "ark:mint ark:update"
```

**鍵は発行しない。** `arkhe client key` を叩く必要はなく、叩いても
`ARKHE_AUTH` に `apikey` / `oauth2` が無ければその鍵は通らない。

## ⑧ 以後の運用

日々あるのは払い出しだけではない。

```bash
arkhe client key repo-web-api          # 新しい鍵を先に配る
arkhe client revoke <credential_id>    # 切り替わってから古いほうを止める
```

**古い鍵は自動では失効しない。** 並行させて切り替えるためで、失効させても
**行は消さない**（いつ誰の鍵だったかが残る）。

障害対応には期限つきの逃げ道がある。

```bash
arkhe client breakglass 99999 --days 7
```

組織が統合されたり去ったりしたときは[承継と離脱](succession.md)を使う。どちらも
**既存の識別子は解決し続ける**——これを運用手順として持っていないと、`NR` の宣言は
実際には守れない。

## この順番である理由

| 順序 | そうしないと |
| --- | --- |
| ② が ③ より先 | 登録するリゾルバの URL がまだ無い |
| ④ が ⑤ より先 | 方針を述べていない NAAN の下に組織ができる |
| ⑤ は不可分 | 採番できない組織が台帳に残る |
| ⑥ は ⑤ の直後 | 既定値が組織の宣言として公開されたまま動き出す |
