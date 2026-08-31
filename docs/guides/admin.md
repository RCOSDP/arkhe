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

## Getting in

Set `ARKHE_ADMIN_LOGIN`; see [Authentication](authentication.md). In `bearer` mode
there is no login screen at all — that is the choice "no browser access".

Irreversible actions are marked as such in the interface, because they are: an ARK
cannot be un-minted, and a retired namespace cannot be revived.

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
