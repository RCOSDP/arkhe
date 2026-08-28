# コマンド

台帳を組むための道具。**画面と同じ `domain.admin_ops` を呼ぶ**ので、どちらから入っても
同じ不変条件を通り、同じ形で監査に残る。

| | |
| --- | --- |
| `arkhe onboard` | 機関を迎え入れ、名前空間を 1 つ委譲する。**この 2 つは必ず対で起きる。** |
| `arkhe succeed` | 統廃合。**識別子は壊さない**（名前空間ごと承継先に移す）。 |
| `arkhe depart` | 機関の離脱。**新規採番は止め、解決は続ける。** |
| `arkhe check` | 設定を検証する。**起動前に落としたいものをここで落とす。** |
| `arkhe naan add` | NAAN を登録する。 |
| `arkhe naan list` |  |
| `arkhe shoulder add` | 名前空間を切り出す。`--reserve` で将来用に確保できる。 |
| `arkhe shoulder status` | 状態を変える。**retired からは戻せない**（引退した名前空間の再開は NR 違反の芽）。 |
| `arkhe shoulder list` |  |
| `arkhe client add` | 主体を登録する。 |
| `arkhe client key` | 資格情報を発行する。**平文はこの一度しか表示されない。** |
| `arkhe client breakglass` | NAAN 配下すべてに届く一時的な主体を作る。**期限つき。** |
| `arkhe client passwd` | 人の主体にパスワードを設定する（管理画面へのローカルログイン用）。 |
| `arkhe client revoke` | 失効させる。**行は消さない**（いつ失効したかを残す）。 |

`--help` に各コマンドの引数がある。

## よくある流れ

### 立ち上げ

```bash
arkhe naan add 99999 "あなたの組織" --policy "NP | NR, OP, CC | 2026 | https://…/policy"
arkhe onboard 99999 "例大学" --shoulder /x9
arkhe client add univ-repo 99999 --manager 1 --scopes "ark:mint ark:update"
arkhe client key univ-repo
```

**機関と名前空間は必ず対で作られる**（`onboard` が両方やる）。片方だけでは、採番できない
機関を作るだけで意味がない。

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

**`retired` からは戻せない。** 予約は作成時にしか指定できない——一度採番できる状態に
した名前空間を、後から未使用扱いにはできないから。
