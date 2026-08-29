# Setting up for the first time

From holding no NAAN to an organisation that can mint. **Half of this happens outside
arkhe**, so those steps are listed too.

```
1. Request a NAAN from the ARK Alliance      outside arkhe
2. Stand arkhe up                            → Deployment
3. Register your resolver URL in the         outside arkhe
   NAAN registry
4. Register the NAAN and state your policy   arkhe naan add
5. Onboard an organisation, delegate a        arkhe onboard
   namespace
6. Confirm the organisation's commitment      arkhe manager commitment
7. Register people and machines              arkhe client add
8. From then on: rotation, succession, departure
```

## 1. Request a NAAN

The ARK Alliance issues them **free of charge**. There is no registration agency to
pay and no membership to maintain.

The request asks what you intend to do with the NAAN. **What you write there has to
match what ends up in the ledger from step 4 onwards.** Decided separately, the
outward declaration and the actual operation drift apart.

## 2. Stand arkhe up

See [Deployment](deployment.md). It has to come **before** step 3, because what you
register there is this resolver's URL.

## 3. Register your resolver URL in the NAAN registry

**Skip this and `n2t.net/ark:/99999/…` never reaches you.** Getting a NAAN is not
just receiving a number; it runs through to writing your resolver's URL into the
registry entry.

**Update it whenever that URL changes.** Nothing follows it for you.

!!! note "You also publish this on your own side"
    arkhe answers `/.well-known/ark` with where minting for a NAAN happens. It is no
    substitute for the registry — the registry is the only way to be found from
    outside — but where minting sits elsewhere, it tells clients where to go.

## 4. Register the NAAN and state your policy

```bash
arkhe naan add 99999 "Your University" \
  --policy "NP | NR, OP, CC | 2026 | https://example.ac.uk/ark-policy"
```

**This is where the NAA policy is stated.** It is not paperwork; it is the central
declaration in arkhe, because ARK has no registration agency guaranteeing persistence
on your behalf. [The commitment is yours](../concepts/ark.md), and so is stating what
it consists of. What you have not stated, `??` cannot answer.

`--authoritative` (the default) means "an unknown name under this NAAN may be
answered with `404`". **If you have taken over a NAAN whose minting continues
elsewhere**, pass `--authoritative false` with `--redirect`. The two go together;
neither is accepted alone.

## 5. Onboard an organisation and delegate a namespace

```bash
arkhe onboard 99999 "Example Institute" --shoulder /x9 --commitment permanent-stable
```

**Registering the organisation and delegating the shoulder always happen together.**
They cannot be separated: an organisation with no namespace cannot mint, so there is
no point putting one in the ledger.

Decide the shoulder layout beforehand. **Once handed out it cannot be taken back** —
having declared `NR`, existing ARKs go on resolving. A namespace you stop using is
`retired`, not deleted.

```bash
arkhe shoulder add 99999 /y2 --reserve   # held for later, nothing minted in it
arkhe shoulder list --naan 99999
```

## 6. Confirm the commitment

```bash
arkhe manager commitment --list
arkhe manager list
arkhe manager commitment 1 permanent-stable
```

It can also be changed [from the admin interface](admin.md#changing-settings), where
**the organisation's own administrator may change it** — the commitment is the
organisation's, and a declaration nobody can make is not a declaration.

Onboarding without `--commitment` leaves the default `permanent-dynamic`. **Do not
leave it there.** The value is published verbatim by `?` and `??`, so leaving it
means **claiming, in the organisation's name, a commitment the organisation never
made**. Publishing an undeclared default as a declaration is worse than publishing
nothing.

The levels are the NLM permanence ratings (`descriptive-only` is an addition, for
physical objects).

| | |
| --- | --- |
| `not-guaranteed` | No commitment |
| `permanent-dynamic` | Permanent; content may change |
| `permanent-stable` | Permanent; content substantially unchanged |
| `permanent-unchanging` | Permanent; content not changed |
| `descriptive-only` | Description only — the object is not online |

**Lowering a level is a legitimate operation.** Saying it plainly is more honest than
holding up a promise you cannot keep, and it is what keeps asking `??` worth doing.

## 7. Register people and machines

**These two cannot be mixed.**

| | Identifies itself with | May hold |
| --- | --- | --- |
| A person (an organisational administrator) | External login (OIDC / proxy) or a password | **No** API key or client secret |
| A machine (the repository itself) | API key / client secret | **No** password |

```bash
# An administrator. The client_id is whatever the authorization server returns
# (an email address, an eppn).
arkhe client add admin@example.ac.uk 99999 --person --manager 1

# The repository itself, pinned to a shoulder.
arkhe client add repo-web-api 99999 --shoulder 1 --scopes "ark:mint ark:update"
arkhe client key repo-web-api          # the plaintext is shown once
```

People hold no API keys because **a key outlives the person's departure from the
organisation**. Revoking a person is done at the authorization server, and arkhe
follows. `arkhe client passwd` is for `ARKHE_ADMIN_LOGIN=password` deployments only.

**Give each process its own credential.** Sharing one across a repository's web and
worker processes means (1) you cannot tell which of them minted, (2) one leak forces
you to revoke all of them, and (3) you cannot narrow scope per use. Pinning with
`--shoulder` means a leaked key still cannot reach another organisation's namespace.

Finally, check the configuration:

```bash
arkhe check
```

## 8. From then on

Minting is not the whole of the daily work.

```bash
arkhe client key repo-web-api          # hand out the new key first
arkhe client revoke <credential_id>    # revoke the old one once traffic has moved
```

**Old credentials are not revoked for you.** That is so the two can run in parallel
during a changeover, and revoking **does not delete the row** — whose key it was, and
when it stopped, both remain.

There is a time-boxed way out for incidents:

```bash
arkhe client breakglass 99999 --days 7
```

When organisations merge or leave, use [succession and
departure](succession.md). In both, **existing identifiers go on resolving** — without
that as an operational procedure, a declaration of `NR` cannot actually be honoured.

## Why this order

| Order | Otherwise |
| --- | --- |
| 2 before 3 | There is no resolver URL yet to register |
| 4 before 5 | Organisations appear under a NAAN whose policy is unstated |
| 5 is indivisible | An organisation that cannot mint is left in the ledger |
| 6 right after 5 | A default goes live, published as the organisation's declaration |
