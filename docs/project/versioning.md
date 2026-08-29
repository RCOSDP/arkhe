# Versioning

arkhe follows [Semantic Versioning 2.0.0](https://semver.org/): `MAJOR.MINOR.PATCH`.

Current version: **0.0.1** — see [Before 1.0](#before-10).

## What the version covers

SemVer is only meaningful once you say what the public surface is. For a piece of
infrastructure rather than a library, it is broader than "the functions we export".

| Part of the contract | Example of a breaking change |
| --- | --- |
| **Resolution behaviour** | An inflection stops answering; a status code changes; suffix passthrough stops resolving through an ancestor |
| **REST API** | A field is removed or renamed; a request that used to succeed now fails |
| **Environment variables** | A setting is renamed or removed; a default changes in a way that alters behaviour |
| **CLI** | A command or option is removed or renamed; output that scripts parse changes shape |
| **Database schema** | A migration that cannot be applied to an existing ledger, or that loses data |
| **The invariants** | Any of them weakening. See below |

Not covered: internal module layout, the admin interface's markup, log formats, and
anything under `compose/` (those are demonstrations).

## The invariants are part of the contract

[These refusals](../concepts/invariants.md) are what arkhe is for. Weakening one is a
**major** change even if no signature moves:

- an ARK or a namespace becomes deletable
- `retired` becomes reversible
- minting can silently become an update
- reach becomes widenable by a request
- a person subject can hold an API key, or a machine subject can be named through an
  external login

A release that did any of those quietly would be worse than one that broke a function
signature, because the damage would be to identifiers rather than to a build.

## Migrations

**A minor release may add a migration; it must never lose data.** Every migration is
run `upgrade → downgrade → upgrade` against PostgreSQL in CI, because SQLite accepts
schemas PostgreSQL rejects.

The ledger cannot be rebuilt. Under NR a lost ARK cannot be minted again, so "restore
from the source system" is not available to us the way it is to most services.

## Before 1.0

While the version starts with `0`, **the minor number carries breaking changes**:
`0.1.0 → 0.2.0` may break, `0.0.1 → 0.0.2` should not.

1.0 will be tagged when:

- the ARK conformance record has no outstanding gaps,
- the schema has been stable across at least one real migration, and
- an organisation other than the first is running it.

Until then, pin an exact version.

## Releasing

```bash
# 1. Update the version and the changelog
vim pyproject.toml CHANGELOG.md CHANGELOG.ja.md
# 2. Tag
git tag -a v0.0.2 -m "v0.0.2" && git push origin v0.0.2
```

The tag triggers the release workflow, which runs the tests, builds the artefacts and
publishes the documentation for that version. The version reaches the code from
`pyproject.toml` alone — the package, the OpenAPI document and the admin footer all
read it from there, so there is nothing else to remember to update.
