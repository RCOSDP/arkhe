# Changelog

The authoritative record is the [commit
history](https://github.com/RCOSDP/arkhe/commits/main); commit messages here carry the
reasoning, not just the change.

## Unreleased

### Rewritten on FastAPI

6,371 lines of Django became 4,106 of FastAPI and SQLAlchemy 2.0, with 209 tests
passing.

**The parts that matter for the specification moved untouched.** `arkspec/` and
`domain/resolution.py` — 680 lines — depend on nothing but the standard library and
reach the database through a repository protocol, so only their imports changed. 97
tests came across unmodified, which is the clearest evidence that separating those
layers was worth it.

The invariants Django held structurally are held structurally here too: minting
confined to a single INSERT path, rotation expressed as a partial index, and deletion
of an ARK or a shoulder refused at the ORM.

### Authentication

Three mechanisms for the API, enabled individually rather than chosen exclusively —
during a migration, accepting both an API key and an OIDC token is the normal case.
Whichever authenticates, the result is one `Principal` and the authorisation decision
stays in one place.

Reach became three tiers — `system`, `naan`, `manager` — mirroring how ARK delegates:
no principal reaches further than the one that granted it.

### Admin interface

Operation-shaped rather than table-shaped, in Japanese and English, with four ways in
(`bearer`, `password`, `oidc`, `proxy`).

### Fixes worth naming

- **Assigning to an ORM relationship in a view** set `naan` to NULL on every
  institution filtered out of the display. A read path was corrupting data.
- **A machine subject could be named through the proxy header**, so a misconfigured
  front end would have let anyone act as the bulk-import client. People and machines
  are now separate types.
- **Two migration bugs that only appear on PostgreSQL**: a circular reference between
  `manager` and `shoulder`, and table creation order. SQLite accepted both.
- **`oauth2` mode had no token endpoint** — verification existed, issuance did not, so
  the standalone configuration was unusable in practice.
