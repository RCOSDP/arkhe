# コマンド

台帳を組むための道具。**画面と同じ `domain.admin_ops` を呼ぶ**ので、どちらから入っても
同じ不変条件を通り、同じ形で監査に残る。

| | |
| --- | --- |
| `arkhe onboard` | 組織を迎え入れ、名前空間を 1 つ委譲する。**この 2 つは必ず対で起きる。** |
| `arkhe succeed` | 統廃合。**識別子は壊さない**（名前空間ごと承継先に移す）。 |
| `arkhe depart` | 組織の離脱。**新規採番は止め、解決は続ける。** |
| `arkhe stat` | **台帳を数える**——ARK（公開／公開前）、取り下げた名前、shoulder、組織、主体、今かかっている保留、直近 24h ／ 7 日 ／ 30 日の採番。届く範囲の内側だけ。機械で読むなら `--json`。**数えるのは行数に比例して重い**（30 万件で約 110 ms）ので、繰り返し叩く用途には向かない。 |
| `arkhe fingerprint` | **台帳の指紋を出す**——復元できたことを、件数ではなく中身で確かめる。2 行（`arks` と `withdrawn`）に分けてあるのは、潰すと「どこが違うか」が消えるため。機械で読むなら `--json`。**行数に比例して重い。** |
| `arkhe check` | 設定を検証する。**起動前に落としたいものをここで落とす。** |
| `arkhe naan add` | NAAN を登録する。 |
| `arkhe naan list` | NAAN を並べる。**権威を持つのか、どこへ委譲しているのか**が出る。 |
| `arkhe manager list` | 組織を並べる。**id は他のコマンドの入力になる。** |
| `arkhe manager commitment` | 組織の約束の水準を言い直す。**`??` でそのまま公開される。** |
| `arkhe manager policy` | 組織にできることを狭める（入り方・自己登録・scope の上限）。**NAAN の決まりから狭めることしかできない**——広げられない。 |
| `arkhe shoulder add` | 名前空間を切り出す。**綴りは first-digit 規約——子音の並び＋末尾に数字 1 桁**（`/x9`。桁数が[切り出せる数](data-model.md#名前空間の容量)を決める）。`--reserve` で将来用に確保できる。**以降の shoulder コマンドが取る id を表示する。** |
| `arkhe shoulder status` | 状態を変える。**retired からは戻せない**（引退した名前空間の再開は NR 違反の芽）。 |
| `arkhe shoulder redirect` | shoulder 単位で解決を委譲する（`$id` / `${blade}` / 先頭の `303 `）。**空文字を渡せば外す。** |
| `arkhe shoulder list` | shoulder を並べる。**id は他のコマンドの入力になる。** |
| `arkhe client add` | 主体を登録する。 |
| `arkhe client key` | 資格情報を発行する。**平文はこの一度しか表示されない。** |
| `arkhe client breakglass` | NAAN 配下すべてに届く一時的な主体を作る。**期限つき。** |
| `arkhe client passwd` | 人の主体にパスワードを設定する（管理画面へのローカルログイン用）。 |
| `arkhe client revoke` | 失効させる。**行は消さない**（いつ失効したかを残す）。 |
| `arkhe client disable` | 主体を止める。**認可サーバに寄せた構成ではこれが唯一の止め方。** |
| `arkhe client enable` | 止めた主体を戻す（去った組織の主体は戻せない）。 |
| `arkhe hold add` | 転送を一時的に止める（`ark` / `shoulder` / `naan`）。**解決は止めない**——記述は答え続ける。期限と理由は必須。 |
| `arkhe hold release` | 期限を待たずに保留を外す。 |
| `arkhe hold list` | 今かかっている保留を並べる。**見えないと恒久化する。** |
| `arkhe ark list` | 発行した ARK を並べる。**既定で 50 件で打ち切る**（台帳は増える一方なので）。`--naan` `--org` で絞り、`-q` は ARK・行き先・題名を見る。 `--state public|reserved` で公開したものだけ・公開前のものだけを引け、`--older-than N` で採番から N 日より古いものだけにできる——**重ねると、誰も公開しないまま残った予約が拾える。** |
| `arkhe ark publish` | **グローバルに公開する。** 取り下げたものを出し直すのも同じ口。二度実行しても落ちない。 |
| `arkhe ark unpublish` | **公開を取り下げる。** 行は残るので `publish` で出し直せる——**戻せるのはこちらだけ。** 理由が必須で、確認を訊く（`--yes` で省ける）。 |
| `arkhe ark delete` | **公開していない ARK を消す。** 公開中のものは先に取り下げる。**一度でも公開した名前なら理由が必須で、確認を訊く。** 消えるのは行だけで、**その名前は二度と採られない。** |
| `arkhe ark purge` | **公開した ARK を一手で破棄する**（取り下げと削除をまとめる）。届く範囲の内側だけ。理由が必須で、確認を訊く（`--yes` で省ける）。**約束を破る操作**——削除命令や、公開してはならなかったものへの逃げ道 |

`--help` に各コマンドの引数がある。

コマンドが言う「主体（principal）」は、**管理画面では「利用者」**と呼んでいる
（[管理画面](../guides/admin.md)）。同じものである。

通しの手順は[はじめて立ち上げるとき](../guides/onboarding.md)にある——**NAAN の申請と
registry への登録という、arkhe の外で起きる手順も含めて**並べてある。

## よくある流れ

### 立ち上げ

```bash
arkhe naan add 99999 "あなたの組織" --policy "NP | NR, OP, CC | 2026 | https://…/policy"
arkhe onboard 99999 "例大学" --shoulder /x9 --commitment permanent-stable
arkhe client add univ-repo 99999 --manager 1 --scopes "ark:mint ark:update"
arkhe client key univ-repo
```

**組織と名前空間は必ず対で作られる**（`onboard` が両方やる）。片方だけでは、採番できない
組織を作るだけで意味がない。

### 人を足す（管理画面にログインさせる）

```bash
arkhe client add alice@example.ac.jp 99999 --manager 1 --person
arkhe client passwd alice@example.ac.jp     # ARKHE_ADMIN_LOGIN=password のとき
```

`--person` を付けた主体は**資格情報を持てず**、`--person` の無い主体は
**外部ログインで名乗れない**。[認証](../guides/authentication.md)を参照。

### 障害時の逃げ道

```bash
arkhe client breakglass 99999 --days 7
```

NAAN 配下すべてに届く主体を**期限つきで**作る。恒久的な万能鍵にしないため期限は必須で、
この主体の操作は**全件が監査に残る**。

### 名前空間を止める

```bash
arkhe shoulder add 99999 /q0 --reserve --note "将来用に確保"
arkhe shoulder status 3 delegated --minter https://mint.partner.example.org
arkhe shoulder status 3 retired --note "移行完了"
```

### 転送を止める

```bash
arkhe hold add ark ark:99999/x9tn1qkq2g7 --days 3 --reason "行き先を確認中"
arkhe hold add shoulder 3 --days 1 --reason "委譲先のリゾルバが落ちている"
arkhe hold list
arkhe hold release shoulder 3
```

**解決は止まらない。** 止まるのは転送だけで、`?info` も `??` も答え続ける。期限は
必須で、切れれば時計だけで戻る——**戻し忘れが残らない**。失われた対象を宣言するのは
これではなく tombstone のほう（意味も可逆性も違う）。

**`retired` からは戻せない。** 予約は作成時にしか指定できない——一度採番できる状態に
した名前空間を、後から未使用扱いにはできないから。

### 名前を先に押さえ、後から公開する

```bash
curl -X POST /api/mint -d '{"reserve": true}'      # まだ解決しない
arkhe ark list --state reserved
arkhe ark list --state reserved --older-than 365   # 放置を拾う
arkhe ark publish ark:99999/x9tn1qkq2g7            # ここから解決を始める
arkhe ark unpublish ark:99999/x9tn1qkq2g7 --reason "誤って公開した"
arkhe ark publish ark:99999/x9tn1qkq2g7            # 出し直す
arkhe ark delete ark:99999/x9tn1qkq2g7 --reason "登録が取りやめになった"
```

**そのまま消せるのは、今 公開していないものだけ。** 公開中の ARK は、先に
`arkhe ark unpublish` で取り下げるか、`arkhe ark purge` で一手に破棄する
——どちらも**届く範囲の内側**で、理由と確認を要求する。

```bash
arkhe ark purge ark:99999/x9tn1qkq2g7 --reason "2026-09 削除命令（事件番号 …）"
```

どちらの場合も**取り下げた名前は二度と採られない**ので、消した後にその名前が別のものを
指すことはない。[壊さないもの](../concepts/invariants.md#no-delete)を参照。

## コマンドの言語

`arkhe` の help と出力は日本語と英語を持つ。**言語は起動時に環境から決まる**——
Typer が help を組み立てるのが import の時点なので、`--lang` のような実行時の
切り替えは作れない。

| | |
| --- | --- |
| `ARKHE_LANG` | `ja` / `en`。**すべてに優先する** |
| `LC_ALL` → `LC_MESSAGES` → `LANG` | POSIX の順で見る。`C` と `POSIX` は「言語の情報が無い」の意味なので飛ばす |
| 既定 | `ja`（管理画面と揃えてある） |

```bash
ARKHE_LANG=en arkhe --help
```
