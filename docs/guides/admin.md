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

**Delegation** — the ledger itself, as a nesting: NAAN → institution → shoulder. ARK
is a scheme of handed-down namespaces, so the shape of the delegation *is* the
content.

**Mint an ARK** — for the times one is needed by hand: a migration edge case, a
physical object, a smoke test. Institutions normally mint through the API.

**Principals and credentials** — who may mint, with which key, reaching how far.

**Audit log** — restricted to NAAN scope and wider. Who did what is information
belonging to whoever holds the namespace; an institution's administrator has no
business reading another's.

## Reach shapes the page

**The same decision drives what is displayed and what is permitted.** Splitting them
creates the hole where a button is hidden but the URL still works.

| Signed in as | Sees | Audit log |
| --- | --- | --- |
| system administrator | every NAAN | yes |
| NAAN administrator | one NAAN, all its institutions | yes |
| institution administrator | one institution | **403** |

## Getting in

Set `ARKHE_ADMIN_LOGIN`; see [Authentication](authentication.md). In `bearer` mode
there is no login screen at all — that is the choice "no browser access".

Irreversible actions are marked as such in the interface, because they are: an ARK
cannot be un-minted, and a retired namespace cannot be revived.

## Internationalisation

Japanese and English, switched from the globe in the header. The language is decided
by `?lang=`, then a cookie, then `Accept-Language`.

Catalogues are plain Python dicts rather than gettext, so adding a language is one
module and no build step. **A missing translation stops the process at startup**,
which is how you find out you added a key to one catalogue and not the other.
