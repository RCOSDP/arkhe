# How arkhe compares

There is other software that mints and resolves ARKs. This page says what each one does,
where arkhe sits among them, and what arkhe took from them.

!!! note "What was looked at, and when"

    Checked on **2026-09-19**, against these revisions:
    [arklet](https://github.com/internetarchive/arklet) `08c2a6a` (2026-05-28),
    [arklet-frick](https://github.com/frickdahl/arklet-frick) `4c7045d` (2024-05-01),
    [EZID](https://github.com/CDLUC3/ezid) `78b31db` (2026-08-25). **Other software
    moves**, so anything here may be out of date by the time you read it. Findings
    marked **measured** were produced by running that software; the rest come from
    reading its source.

Each implementation was installed, given its own throwaway PostgreSQL, and driven
through its own views over HTTP. Reading source is how the bugs were suspected; running
it is how they were confirmed.

## arklet (Internet Archive)

Django, about 1,500 lines. Three operations: mint, update, resolve. arkhe's specification
layer is derived from it (see [Provenance](../index.md)), so it is the closest relative.

| Sent | Answered | |
| --- | --- | --- |
| `PUT /update` | **`TypeError: QuerySet.select_for_update() got an unexpected keyword argument 'ark'` → 500** | measured |
| `GET /ARK:/…` | **404** — the label is matched case-sensitively | measured |
| `GET /ark:/99999/x9tn1qkq2g7` with a hyphen inside the name | 302 to the NAAN's own URL, as if the name were unknown — hyphens are not removed | measured |
| `GET …?info` | 302 to the target: there are no inflections | measured |
| `GET …/a-part` | 302 to the target, **the suffix dropped** | measured |
| `POST /mint` | works, and answers the old `ark:/` form | measured |

Its test suite covers minting and nothing else, which is how a broken update reaches a
release. Beyond that: the NAAN is put through `int()`, so betanumeric NAANs and a leading
zero cannot be represented; authorisation is per NAAN, so anyone holding a key can write
any ARK under it; and an older `Key` model that stores the key **in plaintext** is still
accepted alongside the hashed one.

One thing to correct in our own notes: the defect where a primary key collision turned
into an `UPDATE` — the one [the invariants](../concepts/invariants.md) cite — **has since
been fixed upstream**. Current arklet catches `IntegrityError` and draws another name.

## arklet-frick (The Frick Collection)

A fork, about 2,000 lines, and a clear advance on its parent: minter and resolver deploy
separately, there are bulk mint/update/query endpoints, suffix passthrough, `?info` and
`?json`, API keys hashed with Argon2, shoulders that must exist, and a `?json` that
annotates each field with its Dublin Core property.

Four things showed up when it was run:

| What was done | What happened | |
| --- | --- | --- |
| Bulk update of 5 ARKs, sent in the caller's own order | **4 of the 5 took another record's title**, and the answer was `{"num_updated": 5}` | measured |
| Resolve `…/sub/leaf` where both the base name and `…/sub` are registered | The **shortest** ancestor won, not the longest that the specification requires | measured |
| Resolve any ARK | The target gained a trailing `?` | measured |
| Resolve `…??` | 302 to `<target>??` — the persistence statement is never answered | measured |
| Resolve with a hyphen, or with a wrong check digit | Handed on to another resolver as if unknown | measured |

The first one is the serious one: the rows come from `filter(ark__in=…)`, whose order is
not defined, and are then `zip`-ped against the input. It is silent — the response says
every row succeeded. In a ledger whose identifiers cannot be reissued, a write that lands
on the wrong identifier is the worst outcome there is; it is why arkhe's bulk operations
[key every row by its ARK](../reference/api.md) and fail the whole request when one row
is out of reach.

Authorisation is per NAAN, as in the parent, and each request walks every active key for
that NAAN, checking Argon2 against each. That cost is linear in the number of keys, which
is why arkhe [looks the key up by a prefix](../guides/authentication.md) and hashes once.

## The wider field

| | What it is | Language | State |
| --- | --- | --- | --- |
| [EZID](https://github.com/CDLUC3/ezid) (CDL) | An identifier service for ARK **and DOI**, with DataCite and Crossref registration, OAI-PMH, a search interface and batch download | Python/Django, ~42,000 lines | Active. The largest of them |
| [N2T](https://github.com/CDLUC3/N2T) (CDL) | The global resolver, across identifier schemes. Not a minter | Python | Active. It is where arkhe hands on a NAAN it does not hold |
| NOID family ([pynoid](https://github.com/no-reply/pynoid), [noid](https://github.com/emdb-empiar/noid), [noid.js](https://github.com/viaacode/noid.js)) | The minting algorithm alone — no ledger, no resolution | Perl, Python, JS | Libraries, some quiet since 2018 |
| [arks-service](https://github.com/digitalutsc/arks-service) (UTSC) | Minting, bulk binding, resolution, with an interface | PHP, on Noid4Php | Updated 2026-04 |
| [AMS](https://github.com/burgerbibliothek/AMS) (Burgerbibliothek) | Minting, an admin interface, CSV import, ERC metadata | PHP/Laravel | Updated 2026-09, and says it is still changing |
| [greens](https://github.com/uhlibraries-digital/greens) (U. Houston) | Minting and resolution | Ruby/Rails | Last touched 2023 |
| Plugins for Omeka, Drupal, OJS, ArchivesSpace | ARKs inside an existing system | PHP and others | Not infrastructure on their own |

**EZID is the one whose thinking is closest to arkhe's.** Its identifiers are `reserved`,
`public` or `unavailable`; an unavailable one resolves to a tombstone page; and deletion
is refused unless the identifier is reserved (a superuser excepted). That is the same
reasoning as [the publication lifecycle](../concepts/invariants.md) here, arrived at
independently and years earlier.

## Where arkhe sits

**What appears to be arkhe's own**, in that none of the above has it:

- **minting delegated per shoulder, answered with `307`** and never proxied
  ([Delegation](../concepts/delegation.md))
- **holding redirection** with an expiry, without stopping resolution
- **an idempotency key on minting**, so a lost answer costs no number
- **reach in three tiers** — authorisation stops at the organisation, not at the NAAN
- an audit log, and every change of target recorded
- withdrawn names never assigned again
- an OpenAPI document generated from the implementation, and a
  [Python client](../guides/python-client.md) checked against it
- the admin interface and the CLI in two languages
- an end-to-end suite that runs the production shape and drives it over HTTP

**What arkhe followed rather than invented**: the publication lifecycle is EZID's status
model in different words; suffix passthrough and `?info` / `?json` were in arklet-frick
first; the minting algorithm and the check digit come from NOID, by way of arklet.

**What arkhe does not do**: DOIs and registration with DataCite or Crossref, OAI-PMH,
a search interface or batch download, NOID template compatibility, and resolution across
identifier schemes — that last one is N2T's job, and arkhe hands on to it.

## What might be worth taking

- **arklet-frick's `?json`**, which gives each field its Dublin Core property URI.
  arkhe's `?json` returns values only, and a reader outside this ledger has to know what
  `who` and `when` mean.
- **EZID's co-ownership**, where more than one account may write an identifier. arkhe
  binds an ARK to one organisation, which is simpler and stricter; sharing would touch
  the reach model, so it is a decision rather than a feature.
