# Invariants

Most of arkhe's design is refusals. They all follow from one commitment: **a name,
once given out, never comes to mean something else.**

These are enforced in the code, not in a policy document. A rule that depends on
everyone remembering it will be broken eventually — usually at 2 a.m., by someone
fixing something else.

## A published ARK is never deleted {#no-delete}

Deleting the row stops resolution, and an identifier that no longer resolves is a
broken identifier. `Ark` refuses deletion at the ORM level.

When an object is genuinely gone, you **tombstone** it: the identifier and its
description stay, only reachability goes.

```bash
arkhe … # or
curl -X PUT /api/tombstone -d '{"ark": "ark:99999/x9…", "commitment": "withdrawn"}'
```

The resolver then returns the description instead of a redirect — which is
[FAIR A2](https://www.go-fair.org/fair-principles/): *metadata should be accessible
even when the data are no longer available*.

### Before it goes out, it can still be taken back {#before-publication}

**What NR binds are the names that went out into the world.** A name is not bound the
moment it is minted: numbers are routinely reserved for objects that are still drafts,
and when such a deposit is abandoned, leaving a number that points at nothing forever is
not keeping the promise either.

So an ARK can be minted **reserved**. Until it is published **a public resolver does not
resolve it** — it answers as it does for a name it has never seen — and it can be deleted.

**A resolver inside a closed network is another matter** (`ARKHE_RESOLVE_UNPUBLISHED=1`):
a name minted inside that network is worthless if the network's own resolver will not
resolve it. **Whether an ARK resolves is decided by the ARK's state and by which resolver
is answering** — see [Running it distributed](../guides/federation.md#closed-resolver).

```bash
curl -X POST /api/mint    -d '{"reserve": true}'        # does not resolve yet
curl -X POST /api/publish -d '{"ark": "ark:99999/x9…"}' # from here on it resolves
curl -X POST /api/delete  -d '{"ark": "ark:99999/x9…", "reason": "abandoned"}'
```

There is **one boundary and it only goes one way**. Publishing cannot be undone: if it
could, deleting before publication would mean nothing. A published ARK answers `409` to
`/api/delete`.

**The name is not freed.** It moves to a ledger of withdrawn names and is never assigned
again, by minting or by import — so withdrawing one that was resolving inside a closed
network cannot make that name mean something else; a stale reference simply gets `404`,
which is what `NR` actually protects — a reserved identifier has usually already been handed to
someone (that is what reserving is *for*), and re-using it would be indistinguishable,
from outside, from breaking NR.

## What stops is redirection, never resolution

When a target can no longer be trusted — the delegate is down, a wrong URL went out, a
takedown was requested — **it has to stop quickly, and the identifier must not die.**

`404` would be a lie: the identifier exists. `503` says "not right now", but a permanent
identifier still looks broken. arkhe answers `200` with a **description** instead — the
same path as [A published ARK is never deleted](#no-delete), so the identifier stays
alive while only the redirect stops.

```bash
arkhe hold add ark ark:99999/x9tn1qkq2g7 --days 3 --reason "verifying the target"
arkhe hold add shoulder 7 --days 1 --reason "the delegate's resolver is down"
```

Do not confuse this with a tombstone. **That is a permanent declaration that the object
is gone**; this is **a dated measure saying the object is there but its address cannot be
given out**. So a hold keeps the previous target and expires by the clock alone — nothing
has to remember to undo it.

Neither `?info` nor `??` is stopped: silencing them would withdraw the persistence
promise itself. The reason and the expiry are published there instead.

## A namespace is never deleted either

Deleting a shoulder would let random assignment hand out a string that was already
used. Set `status=retired` instead; existing ARKs keep resolving.

A `delegated` shoulder especially cannot be removed — an external minter may be
creating names in it that this ledger has never seen.

## Minting never becomes an update

This was **the worst defect in arklet**: a primary key collision was absorbed by
`save()` and silently became an `UPDATE`, quietly rewriting where an existing ARK
pointed. arkhe confines minting to one code path where a collision fails, is counted,
and is retried with a new name.

The collision count is returned rather than swallowed, because a rising collision
rate is how you find out a namespace is filling up.

## Reach cannot be widened by a request

`authority`, `manager_id`, `shoulder_id` and `allowed_scopes` are attributes of the
registration. A request may *name* a shoulder, and the answer is only ever whether
that shoulder is already inside the principal's reach.

A token can **narrow** the scopes it carries. It can never add one.

## People and machines are different kinds

A `machine` subject authenticates with a key and **cannot be named through an
external login**; a `person` subject is vouched for elsewhere and **cannot hold an API
key**.

A correctly configured proxy would prevent impersonation anyway — but one
misconfiguration turning into "act as the bulk-import client and rewrite everything"
is too sharp an edge to leave in place.

## Recording outlives the recorded

`AuditEvent` has no foreign keys into the rest of the schema. A record should survive
what it describes, and referential integrity would push the other way: it makes
deleting the record the convenient answer.

Everything that reaches NAAN scope or wider is recorded, because the wider the reach,
the more it matters that you can trace who did what.

## Where these live

| Invariant | Enforced by |
| --- | --- |
| No deletion of a **published** ARK, or of a shoulder | `before_delete` events in `db/models.py` |
| A withdrawn name is never assigned again | `WithdrawnName`, checked in `domain/minting.py` |
| A hold stops redirection only | `hold_of` / `effective_hold` in `domain/resolution.py` |
| `retired` is one-way | the transition table in `domain/admin_ops.py` |
| Minting cannot become an update | the single INSERT path in `domain/minting.py` |
| Reach is a registration attribute | `domain/authz.py`, one decision point |
| People vs machines | `subject_type` checks in `auth/apikey.py` and `auth/login.py` |

Each has a test that fails if it is removed. See `tests/test_models.py` and
`tests/test_authz.py`.
