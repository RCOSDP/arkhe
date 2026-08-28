# arkhe

*[日本語版はこちら / Japanese version](README.ja.md)*

Infrastructure for **ARK** identifiers. **Minting and resolution run as separate
processes.**

Unlike DOI and Handle, ARK presumes no paid registration agency and no central
infrastructure. It holds that **persistence is not a property of the string but a
matter of service**. arkhe implements that position: it delegates namespaces to
institutions and lets each of them declare, for itself, the level of commitment it
is prepared to keep.

The name is the Greek ἀρχή — beginning, first principle. The point at which a
reference starts.

Built on FastAPI and SQLAlchemy 2.0. `src/arkhe/arkspec/` (the ARK specification as
pure functions) and `src/arkhe/domain/resolution.py` (the resolution decision logic)
**depend on nothing but the standard library**, so anyone who only wants to check
the specification can read them without installing a thing.

The design notes, acceptance criteria, implementation plan and conformance record
live in the JC2 working repository (`ark_design_policy.md`,
`ark_acceptance_criteria.md`, `ark_implementation_plan.md`,
`ark_conformance_jc2ark.md`, and others).

## Layout

| | |
| --- | --- |
| `src/arkhe/arkspec/` | **The ARK specification as pure functions. No framework, no database.** The hard parts of the spec live here |
| `src/arkhe/domain/` | Resolution, authorization, minting, administrative operations, succession. **Knows nothing about HTTP** |
| `src/arkhe/db/` | SQLAlchemy models and the repository |
| `src/arkhe/auth/` | Three authentication mechanisms (apikey / oauth2 / oidc) and `Principal` |
| `src/arkhe/api/` | FastAPI routers, the admin interface, internationalisation |

Set `ARKHE_RESOLVER=1` to run as a resolver. **A minter has no resolution endpoint,
and a resolver has no minting endpoint** — so the two can be scaled separately and
the resolver can be pointed at a read-only role and a replica.

## Authentication

**Mechanisms are enabled individually, not selected as one exclusive mode.** During
a migration you routinely need to accept both an API key and an OIDC token.

```
ARKHE_AUTH=apikey,oidc
```

| | |
| --- | --- |
| `apikey` | A personal access token. **Self-contained** — arkhe needs nothing external |
| `oauth2` | Issued by arkhe itself. **Client credentials only** — ARK minting is machine-to-machine from an institution's repository, so the situation the authorization code flow exists to solve (a user granting a third-party app the right to act on their behalf) never arises |
| `oidc` | Validates a JWT issued by an external authorization server such as Keycloak. Delegate here when a human has to log in |

Whichever mechanism authenticates, the result collapses into a single `Principal`,
so **the authorization decision is made in one place** rather than branching per
mechanism.

Reach has three tiers — `system`, `naan`, `manager`. **No principal can reach
further than the one that granted it.**

## What the invariants protect

ARK declares that names are never re-assigned. That single commitment is what most
of this codebase is arranged around.

- **An ARK is never deleted.** Deleting the row stops resolution, which breaks the
  identifier. When a target is lost you tombstone it, or empty its target so the
  resolver returns a description instead.
- **A shoulder is never deleted.** Random assignment could hand out the same string
  again. A departed institution's namespace is retired, not removed.
- **A retired shoulder cannot be reactivated.** You cannot rule out that something
  outside used the name in the meantime.
- **Minting never turns into an update.** A primary key collision must fail, not
  silently rewrite where an existing ARK points.

Succession and departure are built on the same commitment: however the custodian
changes, the identifier survives. What changes is who mints next and where the
target points.

## Getting started

```bash
uv venv --python 3.12 && uv pip install -e '.[app,dev]'
python -m pytest -q          # 184 tests
python -m ruff check src tests

# Build up the ledger
arkhe naan add 99999 "National Institute of Informatics"
arkhe onboard 99999 "National Institute for Basic Biology" --shoulder /x9
arkhe client add nibb-web 99999 --manager 1
arkhe client key nibb-web        # the plaintext is shown this once and never again

# Run it
uvicorn arkhe.app:create_app --factory
```

The admin interface is at `/admin/` (Japanese and English). API documentation is at
`/api/docs`.

## Provenance

Part of `src/arkhe/arkspec/` is derived from the Internet Archive's
[arklet](https://github.com/internetarchive/arklet) (MIT). The derived passages
carry an attribution in place, and [LICENSE](LICENSE) reproduces the copyright
notice and permission text.

## License

MIT. See [LICENSE](LICENSE).
