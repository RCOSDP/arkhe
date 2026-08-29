# Succession and departure

Organisations merge, split and leave. **The identifiers must not notice.**

`ark:/99999/x9abc` was handed out. Under NR it cannot be reissued, so it cannot be
replaced by a new name at a new organisation — that would kill the original. What can
change is who mints next, and where the target points.

## Succession — an organisation merges into another

```bash
arkhe succeed 1 2          # organisation 1 is succeeded by organisation 2
```

The shoulders move to the successor. **`Ark` rows are untouched**, so every existing
identifier resolves exactly as before. The predecessor is deactivated, its credentials
are stopped — rows kept, so you can still see whose key it was — and `succeeded_by`
records the lineage.

`--retire` (the default) also stops new minting in the moved namespaces: the successor
mints in its own, and the old namespace becomes read-only.

Succession cannot cross NAANs. Moving between NAANs would change the shape of the
identifier, which is another way of saying it would be a different name.

## Departure — an organisation leaves but still exists

```bash
arkhe depart 1 --resolver 'https://repo.univ.ac.jp/ark/${blade}' \
               --keep-update self-managed
```

**Minting stops; resolution continues forever.** Having handed out
`ark:/<our NAAN>/…`, we cannot reissue those names, so the NAAN holder goes on
answering `302` for them indefinitely.

`--resolver` is the part worth understanding. It rewrites every existing target to the
organisation's own resolver **and** sets the same delegation on the shoulder, so that
even names this ledger never saw are forwarded there. After that, **nothing further is
required of the departed organisation**.

That matters more than it looks. A design that requires the leaver to keep sending us
updates every time something moves is a design that ends in dead links, because
eventually nobody sends them.

`--keep-update` leaves them a credential scoped to `ark:update` alone. **This is where
separating the scopes earns its keep**: they can repoint targets themselves, and
cannot mint anything new.

## What is kept

| | |
| --- | --- |
| `Ark` rows | untouched. Identifiers and their history survive |
| Shoulders | `retired`, never deleted — the names must not be reissued |
| Credentials | deactivated, rows kept, so the record of whose key it was survives |
| `Manager` | deactivated, `succeeded_by` set, so the lineage can be followed |

Everything above is recorded in the audit log.
