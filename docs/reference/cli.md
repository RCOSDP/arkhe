# CLI

The tools for building up a ledger. **They call the same `domain.admin_ops` the admin
interface does**, so either way in goes through the same invariants and lands in the
audit log the same way.

| | |
| --- | --- |
| `arkhe onboard` | Onboard an organisation and delegate one namespace to it. **The two always happen together.** |
| `arkhe succeed` | A merger. **Identifiers are not broken** — the namespace moves with them. |
| `arkhe depart` | An organisation leaves. **Minting stops; resolution continues.** |
| `arkhe check` | Validate the configuration. **Fail here rather than at startup.** |
| `arkhe naan add` | Register a NAAN. |
| `arkhe naan list` |  |
| `arkhe manager list` | List organisations. **The ids are input to other commands.** |
| `arkhe manager commitment` | Restate an organisation's commitment level. **Published verbatim by `??`.** |
| `arkhe shoulder add` | Carve out a namespace. `--reserve` holds one for later. |
| `arkhe shoulder status` | Change the status. **There is no way back from retired.** |
| `arkhe shoulder list` |  |
| `arkhe client add` | Register a principal. |
| `arkhe client key` | Issue a credential. **The plaintext is shown this once and never again.** |
| `arkhe client breakglass` | Create a temporary principal reaching everything under a NAAN. **Time-boxed.** |
| `arkhe client passwd` | Set a password on a person (for local sign-in to the admin interface). |
| `arkhe client revoke` | Revoke. **The row is not deleted** — when it stopped remains. |

`--help` on any command gives its arguments.

What the commands call a *principal* is called a **user** in the admin interface
([Admin interface](../guides/admin.md)). They are the same thing.

The whole sequence, including the steps that happen outside arkhe — requesting a NAAN
and registering your resolver — is in [Setting up for the first
time](../guides/onboarding.md).

## Common sequences

### Standing one up

```bash
arkhe naan add 99999 "Your organisation" --policy "NP | NR, OP, CC | 2026 | https://…/policy"
arkhe onboard 99999 "Example University" --shoulder /x9 --commitment permanent-stable
arkhe client add univ-repo 99999 --manager 1 --scopes "ark:mint ark:update"
arkhe client key univ-repo
```

**An organisation and a namespace are always created together** — `onboard` does both.
One without the other is an organisation that cannot mint.

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

## The language of the commands

`arkhe`'s help and output exist in Japanese and English. **The language is decided
from the environment at startup** — Typer assembles its help at import time, so a
runtime switch like `--lang` cannot work.

| | |
| --- | --- |
| `ARKHE_LANG` | `ja` / `en`. **Takes precedence over everything** |
| `LC_ALL` → `LC_MESSAGES` → `LANG` | Read in POSIX order. `C` and `POSIX` mean "no language information" and are skipped |
| Default | `ja`, matching the admin interface |

```bash
ARKHE_LANG=en arkhe --help
```
