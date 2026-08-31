# コマンド

台帳を組むための道具。**画面と同じ `domain.admin_ops` を呼ぶ**ので、どちらから入っても
同じ不変条件を通り、同じ形で監査に残る。

| | |
| --- | --- |
| `arkhe onboard` | 組織を迎え入れ、名前空間を 1 つ委譲する。**この 2 つは必ず対で起きる。** |
| `arkhe succeed` | 統廃合。**識別子は壊さない**（名前空間ごと承継先に移す）。 |
| `arkhe depart` | 組織の離脱。**新規採番は止め、解決は続ける。** |
| `arkhe check` | 設定を検証する。**起動前に落としたいものをここで落とす。** |
| `arkhe naan add` | NAAN を登録する。 |
| `arkhe naan list` | NAAN を並べる。**権威を持つのか、どこへ委譲しているのか**が出る。 |
| `arkhe manager list` | 組織を並べる。**id は他のコマンドの入力になる。** |
| `arkhe manager commitment` | 組織の約束の水準を言い直す。**`??` でそのまま公開される。** |
| `arkhe manager policy` | 組織にできることを狭める（入り方・自己登録・scope の上限）。**NAAN の決まりから狭めることしかできない**——広げられない。 |
| `arkhe shoulder add` | 名前空間を切り出す。`--reserve` で将来用に確保できる。 |
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
| `arkhe ark list` | 発行した ARK を並べる。**既定で 50 件で打ち切る**（台帳は増える一方なので）。`--naan` `--org` で絞り、`-q` は ARK・行き先・題名を見る。 |

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
arkhe hold add ark ark:/99999/x9abc --days 3 --reason "行き先を確認中"
arkhe hold add shoulder 3 --days 1 --reason "委譲先のリゾルバが落ちている"
arkhe hold list
arkhe hold release shoulder 3
```

**解決は止まらない。** 止まるのは転送だけで、`?info` も `??` も答え続ける。期限は
必須で、切れれば時計だけで戻る——**戻し忘れが残らない**。失われた対象を宣言するのは
これではなく tombstone のほう（意味も可逆性も違う）。

**`retired` からは戻せない。** 予約は作成時にしか指定できない——一度採番できる状態に
した名前空間を、後から未使用扱いにはできないから。

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
