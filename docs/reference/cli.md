# CLI

The tools for building up a ledger. **They call the same `domain.admin_ops` the admin
interface does**, so either way in goes through the same invariants and lands in the
audit log the same way.

| | |
| --- | --- |
| `arkhe onboard` | Onboard an organisation and delegate one namespace to it. **The two always happen together.** |
| `arkhe succeed` | A merger. **Identifiers are not broken** — the namespace moves with them. |
| `arkhe depart` | An organisation leaves. **Minting stops; resolution continues.** |
| `arkhe stat` | **Count the ledger** — ARKs (public and reserved), withdrawn names, shoulders, organisations, clients, holds in force, and minting over the last 24h / 7d / 30d. Only within your reach. `--json` for machines. **Counting is exact, so it costs time proportional to the number of rows** (about 110 ms over 300,000) — not made for polling. |
| `arkhe fingerprint` | **Print the ledger's fingerprint** — prove a restore by its contents, not its row count. Two lines (`arks` and `withdrawn`), because blending them hides where the difference is. `--json` for machines. **Costs time proportional to the number of rows.** |
| `arkhe check` | Validate the configuration. **Fail here rather than at startup.** |
| `arkhe naan add` | Register a NAAN. |
| `arkhe naan list` | List NAANs. Shows **which it holds authority for, and where the rest are delegated**. |
| `arkhe manager list` | List organisations. **The ids are input to other commands.** |
| `arkhe manager commitment` | Restate an organisation's commitment level. **Published verbatim by `??`.** |
| `arkhe manager policy` | Narrow what an organisation may do — ways in, self-registration, scope ceiling. **It can only narrow what the NAAN allows**, never widen it. |
| `arkhe shoulder add` | Carve out a namespace. **The spelling follows the first-digit convention — consonants ending in one digit** (`/x9`; its length fixes [how many there can be](data-model.md#namespace-capacity)). `--reserve` holds one for later. **Prints the id the other shoulder commands take.** |
| `arkhe shoulder status` | Change the status. **There is no way back from retired.** |
| `arkhe shoulder redirect` | Delegate resolution for a shoulder (`$id` / `${blade}` / a leading `303 `). **An empty value clears it.** |
| `arkhe shoulder list` | List shoulders. **The id is the input to the other commands.** |
| `arkhe client add` | Register a principal. |
| `arkhe client key` | Issue a credential. **The plaintext is shown this once and never again.** |
| `arkhe client breakglass` | Create a temporary principal reaching everything under a NAAN. **Time-boxed.** |
| `arkhe client passwd` | Set a password on a person (for local sign-in to the admin interface). |
| `arkhe client revoke` | Revoke. **The row is not deleted** — when it stopped remains. |
| `arkhe client disable` | Stop a principal. **The only way where authentication is delegated.** |
| `arkhe client enable` | Restore one (not if its organisation has left). |
| `arkhe hold add` | Hold redirection for an `ark` / `shoulder` / `naan`. **Resolution is not stopped** — the description keeps answering. An expiry and a reason are required. |
| `arkhe hold release` | Lift a hold before its expiry. |
| `arkhe hold list` | List the holds in force. **What is not visible becomes permanent.** |
| `arkhe ark list` | List minted ARKs. **Stops at 50 by default** — the ledger only grows. `--naan` and `--org` narrow it; `-q` looks at the ARK, its target and its title. `--state public|reserved` keeps only the published or only the reserved ones, and `--older-than N` only those minted more than N days ago — **together they find reservations nobody ever published**. |
| `arkhe ark publish` | **Publish it globally**, including one that was withdrawn from publication. Running it twice is not an error. |
| `arkhe ark unpublish` | **Withdraw it from publication.** The row stays, so `publish` puts it back — **this is the half that comes back.** A reason is required and it asks first (`--yes` skips that). |
| `arkhe ark delete` | **Delete ARKs that are not currently published.** A published one must be unpublished first. **If it has ever been published, a reason is required and it asks first**; several at once go through the batch path, which refuses any name that has ever been public. Give several ARKs, or `-` to read them from standard input. Only the rows go — **the names are never assigned again.** |
| `arkhe ark purge` | **Purge a published ARK** — unpublish and delete in one step, within your own reach. A reason is required and it asks first (`--yes` skips that). **It breaks the promise** — a way out for a removal order, or for what should never have been published |

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

### Holding a redirect

```bash
arkhe hold add ark ark:99999/x9tn1qkq2g7 --days 3 --reason "verifying the target"
arkhe hold add shoulder 3 --days 1 --reason "the delegate's resolver is down"
arkhe hold list
arkhe hold release shoulder 3
```

**Resolution does not stop.** Only the redirect does; `?info` and `??` keep answering.
An expiry is required and lifts itself by the clock alone — **nothing has to remember to
undo it**. Declaring an object lost is a different operation (`tombstone`), with
different meaning and no way back.

### Reserving a name, then publishing it

```bash
curl -X POST /api/mint -d '{"reserve": true}'      # does not resolve yet
arkhe ark list --state reserved
arkhe ark list --state reserved --older-than 365   # abandoned
arkhe ark publish ark:99999/x9tn1qkq2g7            # from here on it resolves
arkhe ark unpublish ark:99999/x9tn1qkq2g7 --reason "published by mistake"
arkhe ark publish ark:99999/x9tn1qkq2g7            # and back again
arkhe ark delete ark:99999/x9tn1qkq2g7 --reason "the deposit was abandoned"

# a whole abandoned batch, asked about once. Look at it first: this cannot be undone
arkhe ark list --state reserved --older-than 365 --limit 1000
arkhe ark list --state reserved --older-than 365 --limit 1000 | awk '{print $1}' | \
  arkhe ark delete - --reason "the review was abandoned"
```

**Ordinary deletion only works before publication.** A published ARK goes only if the
registration authority's operator purges it, with a reason.

```bash
arkhe ark purge ark:99999/x9tn1qkq2g7 --reason "removal order, 2026-09, case …"
```

Either way **the name is never assigned again**, so it cannot come to mean something else
afterwards. See [What is never broken](../concepts/invariants.md#no-delete).

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
