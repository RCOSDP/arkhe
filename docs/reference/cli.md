# CLI

The tools for building up a ledger. **They call the same `domain.admin_ops` the admin
interface does**, so either way in goes through the same invariants and lands in the
audit log the same way.

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

`--help` on any command gives its arguments.

## Common sequences

### Standing one up

```bash
arkhe naan add 99999 "Your organisation" --policy "NP | NR, OP, CC | 2026 | https://…/policy"
arkhe onboard 99999 "Example University" --shoulder /x9
arkhe client add univ-repo 99999 --manager 1 --scopes "ark:mint ark:update"
arkhe client key univ-repo
```

**An institution and a namespace are always created together** — `onboard` does both.
One without the other is an institution that cannot mint.

### Adding a person

```bash
arkhe client add alice@example.ac.jp 99999 --manager 1 --person
arkhe client passwd alice@example.ac.jp     # when ARKHE_ADMIN_LOGIN=password
```

A `--person` subject **cannot hold a credential**, and a subject without it **cannot be
named through an external login**. See [Authentication](../guides/authentication.md).

### A way out during an incident

```bash
arkhe client breakglass 99999 --days 7
```

Creates a principal reaching everything under the NAAN, **with an expiry**. The expiry
is required so that no permanent master key exists, and **everything this principal
does is recorded**.

### Retiring a namespace

```bash
arkhe shoulder add 99999 /q0 --reserve --note "held for later"
arkhe shoulder status 3 delegated --minter https://mint.partner.example.org
arkhe shoulder status 3 retired --note "migration complete"
```

**`retired` has no way back.** A reservation can only be set at creation: once a
namespace has been mintable, it cannot be called unused again.
