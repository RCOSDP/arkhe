# Admin interface

The admin is **operation-shaped, not table-shaped**. There is no generic row editor.

That is a deliberate refusal. Editing rows directly would let the interface do things
the domain forbids — move a shoulder back out of `retired`, rewrite an `ark` primary
key, delete a namespace. Auto-generated CRUD (sqladmin and friends) is a nicer
database browser, and a database browser is exactly the wrong tool for a ledger whose
value is in what it will not do.

Every page calls `domain.admin_ops` or `domain.minting` — the same functions the CLI
uses. There is no path through the interface that skips an invariant.

## What it shows

**Organisations** — the ledger itself, as a nesting: organisation number (NAAN) → organisation →
namespace. ARK is a scheme of handed-down namespaces, so the shape of what was handed
down *is* the content.

The page is called "Organisations" rather than "Delegation". It is the first page
someone opens, so **its heading is not a word the reader does not have yet**.

The terms are kept, in parentheses: "namespace (shoulder)", "number (the NAAN)",
"Permanent; content may change (permanent-dynamic)". The plain wording comes first and
the term follows, so a newcomer can read it as it stands and someone who knows the
term can line it up with [the specification](../concepts/ark.md), the CLI and the API.
**Drop the terms and this page ends up speaking a different language from everything
else.**

**Mint an ARK** — for the times one is needed by hand: a migration edge case, a
physical object, a smoke test. Organisations normally mint through the API.

**Users and keys** — who may mint, with which key, reaching how far. What is listed
is **not the organisations themselves** but their systems and their people.

!!! note ""Users" on screen is "principals" in the API and CLI"
    **The readers differ, so the words do.** The interface is read by whoever operates
    the service; the API and the CLI are read by whoever writes against them.

    | Interface | API, CLI, data model |
    | --- | --- |
    | User | Principal (`Client`) |
    | Key | Credential |

    "Principal" is the access-control term, which is also where the `Subject` column
    (machine / person) comes from.

**Held redirects** — which identifiers and namespaces currently have **redirection
stopped**. Holds expire on their own, but **what is not visible becomes permanent**: the
person who set one may forget, and this list is how someone else notices. Only the
redirect is stopped; resolution continues ([Invariants](../concepts/invariants.md)).

**Audit log** — restricted to NAAN scope and wider. Who did what is information
belonging to whoever holds the namespace; an organisation's administrator has no
business reading another's.

## Reach shapes the page

**The same decision drives what is displayed and what is permitted.** Splitting them
creates the hole where a button is hidden but the URL still works.

| Signed in as | Sees | Audit log |
| --- | --- | --- |
| system administrator | every NAAN | yes |
| NAAN administrator | one NAAN, all its organisations | yes |
| organisation administrator | one organisation | **403** |

## Who can do what

**Three things bind an action**, and they are independent — being allowed by one does not
excuse the others:

1. **Reach** — the three tiers above. It comes from the client's registration, never from
   the request body or the token; a token can only *narrow* what a client may do.
2. **Scope** — the key for that kind of action (`ark:mint`, `ark:unpublish`, …).
3. **Ceremony** — a reason, and the ARK retyped, for anything that has ever been
   published. **This follows the name's history, not the actor's rank.**

### An ARK: all three tiers, each inside its own reach

Every row here goes through the same reach check, so the tiers differ only in *how far*
they reach — never in *what* they may do.

| Action | Scope | System | NAAN | Organisation |
| --- | --- | --- | --- | --- |
| Mint, in bulk, register a qualifier | `ark:mint` | every NAAN | its NAAN | its own shoulder |
| Import a name minted elsewhere | `ark:import` | ” | ” | ” |
| Update, update in bulk | `ark:update` | ” | ” | ” |
| Read (`/api/query`) | `ark:read` | ” | ” | ” |
| **Publish**, and publish again | `ark:mint` | ” | ” | ” |
| **Withdraw from publication** | `ark:unpublish` | ” | ” | ” |
| **Delete** (not currently published) | `ark:delete` | ” | ” | ” |
| **Purge** (both steps at once) | `ark:purge` | ” | ” | ” |
| Tombstone | `ark:tombstone` | ” | ” | ” |
| Hold redirection for one ARK | `ark:hold` | ” | ” | ” |

**The ceremony applies to withdrawing, deleting and purging anything that has ever been
published** — see [Invariants](../concepts/invariants.md#before-publication).

### A client is not a tier: it is a combination

The three tiers are only one axis. **What a client actually is** is a combination of
three, and the most common client in practice is not a tier at all:

| Axis | What it decides |
| --- | --- |
| `authority` | how far it reaches — the three tiers |
| `scopes` | what it may do; **independent of the tier** |
| `shoulder_id` | pins an organisation's client to a single shoulder |

**A mint-only client** — a repository that just asks for identifiers — is
`authority=manager`, pinned with `shoulder_id`, holding `ark:mint` alone. That key opens
exactly four doors:

```
POST /api/mint        POST /api/mint/bulk
POST /api/register    POST /api/publish        ← publishing is part of ark:mint
```

Two things follow, and both are deliberate:

* **It can put names into the world and take none of them back.** Withdrawing, deleting
  and purging are behind `ark:unpublish`, `ark:delete` and `ark:purge`, and it holds none
  of them. Handing out a minting key does not hand out the power to stop a name.
* **It cannot read its own ARKs back** (`/api/query` needs `ark:read`). Resolution needs
  no authentication, so the identifiers themselves still work — this is about the ledger,
  not about the names.

Publishing sits with `ark:mint` because **it is the second half of minting**: a caller
that reserved a name has to be able to put it out, or every draft would need a second
key.

### The guest: everyone who has no client at all

**Resolution needs no authentication, and that is the point** — an identifier nobody can
resolve without a key is not a persistent identifier. The unauthenticated caller reaches:

| Open to anyone | What it gives |
| --- | --- |
| `GET /ark:/…` and `GET /ark:…` | resolution, and the inflections `?` `??` `?info` `?json` |
| `GET /.well-known/ark` | which namespaces this service is responsible for |
| `GET /healthz`, `GET /readyz` | liveness and readiness |
| `POST /oauth/token` | the door into becoming one of the actors above (credentials still required) |

Everything else needs a client.

**This actor is why the reserved/published distinction exists at all.** `?info` and `??`
answer without a key, so if a public resolver served ARKs that have not been published, the
existence, title and target of an unpublished object would go straight out to anyone who
guessed the name. That is why **the default does not serve them**, and why serving them
is a property of *where a resolver stands* (`ARKHE_RESOLVE_UNPUBLISHED`, for a resolver
inside a closed network) rather than a property of the ARK.

To the guest, a reserved ARK and one that was never minted are **the same 404**. A
withdrawn one is too — and it stays a 404 forever, because the name is never assigned to
anything else.

### A namespace: NAAN administrator and above

| Action | System | NAAN | Organisation |
| --- | --- | --- | --- |
| Add a shoulder, change its status, delegate resolution | yes | yes | **no** |
| Hold redirection for a shoulder or a whole NAAN | yes | yes | **no** |
| Namespace policy, quota, commitment statement | yes | yes | **no** |
| Onboard an organisation | yes | yes | **no** |
| **Register a NAAN** | yes | **no** | **no** |

Holding a shoulder or a NAAN stops a whole namespace, so it is kept above the
organisations: **one organisation's judgement must not sweep in another's identifiers.**

### Clients and organisations: an organisation may act inside itself

| Action | System | NAAN | Organisation |
| --- | --- | --- | --- |
| Register a client | yes | its NAAN | **its own organisation** |
| … one with `authority=system` | yes | no | no |
| … one with `authority=naan` | yes | yes | no |
| Issue and revoke credentials, set a password, disable/enable | yes | its NAAN | **its own organisation** |
| Set a successor, carry out succession | yes | its NAAN | **its own organisation** |
| Depart (`arkhe depart`) | yes | yes | **no** |

**The CLI always acts as the system administrator.** Anyone with a shell on the server
can reach the database anyway, so narrowing it by permission would not be a defence —
**instead every operation is audited.**

## Getting in

Set `ARKHE_ADMIN_LOGIN`; see [Authentication](authentication.md). In `bearer` mode
there is no login screen at all — that is the choice "no browser access".

Irreversible actions are marked as such in the interface, because they are. **Publication
is not one of them** — it can be withdrawn and taken up again — but **deleting a record
is**, and so is retiring a namespace. A name that has been used is never assigned to
anything else, whichever way it went.

## Changing settings

**Only declarations and operational settings can be changed here.** Neither an ARK
row nor a shoulder's spelling can be edited from the interface — if they could, names
could be reissued in a system that declares `NR`.

| What | Who |
| --- | --- |
| NAA policy (the NAAN's declaration) | NAAN scope or wider |
| Where minting happens (`/.well-known/ark`) | System administrator |
| Commitment level (the organisation's declaration) | **The organisation itself**, and wider |
| Minting limit per day | NAAN scope or wider |
| Shoulder status and delegation | NAAN scope or wider |

This split is not a permissions table; it is **ARK's delegation structure showing
through**. The NAA policy is the declaration of the side handing namespaces out and
covers every organisation beneath it, so one organisation's administrator cannot change
it. The commitment level is what the receiving side states about itself, and **a
declaration nobody can make is not a declaration** — so an organisational administrator
can change theirs.

The minting limit is the exception an organisation cannot change itself: a limit
imposed by the side handing the namespace out means nothing if the side receiving it
can lift it.

The decisions live only in `domain.admin_ops`. The interface calls the same
functions, so **there is no case where a button is hidden but the URL still works.**

## Internationalisation

Japanese and English, switched from the globe in the header. The language is decided
by `?lang=`, then a cookie, then `Accept-Language`.

Catalogues are plain Python dicts rather than gettext, so adding a language is one
module and no build step. **A missing translation stops the process at startup**,
which is how you find out you added a key to one catalogue and not the other.
