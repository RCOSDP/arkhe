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

## Getting into the admin interface

**A browser cannot set an Authorization header.** A bearer token is enough for the
API, but a person needs a different way in. Choose it with `ARKHE_ADMIN_LOGIN`.

| | |
| --- | --- |
| `bearer` | Default. No login screen — for callers that can set a header (curl, automation) |
| `oidc` | arkhe acts as an **OIDC client (relying party)**, runs the authorization code flow with PKCE, and turns the result into a session cookie |
| `proxy` | Trusts a header set by an authenticating proxy in front (oauth2-proxy, nginx with OIDC, …) |

**Being a client is not the same as being an authorization server.** arkhe never
becomes the latter: it issues no tokens and holds no consent. What `oidc` does is
send a person to the authorization server and check the JWT that comes back — work
that stays on the resource side.

⚠️ If you choose `proxy`, **close off any path that reaches arkhe directly.** If one
remains, anyone can forge the header (use a NetworkPolicy on Kubernetes, or listen
only on 127.0.0.1 when running standalone).

Whichever way in, the result is the same `Principal` the API produces, and reach is
judged the same way.

### Adding people

Anyone who signs in to the admin interface through `proxy` or `oidc` is registered as
a **person** subject.

```bash
arkhe client add alice@example.ac.jp 99999 --manager 1 --person \
  --scopes "ark:mint ark:read"
```

Put whatever identifier the authorization server or proxy hands back (an email, an
eppn) in `client_id`. The asserted identity is matched against that value, and an
identity that does not match does not get in.

**No credential is issued.** A person's identity is vouched for elsewhere, so arkhe
holds no key for them — holding one would let that key work after the external
account had been revoked.

> **People and machines are separated by type.** A machine subject — one that
> authenticates with an API key — **cannot be named through the proxy header**. A
> correctly placed proxy would prevent this anyway, but one misconfiguration turning
> into "act as the bulk-import client and rewrite everything" is too sharp an edge,
> so the path itself is closed. The reverse holds too: a person subject cannot
> authenticate with an API key.

### Signing in with an ID and password

A way in for institutions with no external IdP.

```bash
export ARKHE_ADMIN_LOGIN=password
export ARKHE_SESSION_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"

arkhe client add alice@example.ac.jp 99999 --manager 1 --person
arkhe client passwd alice@example.ac.jp     # input is not echoed
```

**Prefer `oidc` or `proxy` where they are available.** Identity then lives in one
place, and someone leaving or moving is handled by the organisation alone.
`password` exists so that an institution without any of that can still stand this up
on its own.

What it holds to:

* Nothing is stored in the clear (Argon2).
* **It does not reveal who exists.** An unknown ID and a wrong password produce the
  same answer in the same amount of time.
* **Brute force is stopped.** Five consecutive failures lock the account for fifteen
  minutes. Publishing a login form without this leaves it plainly open to a
  dictionary attack.
* Only length is required (12 characters). Rules demanding symbols and capitals
  produce strings nobody can remember, which end up written down somewhere.
* Only a person subject can hold a password. Changing it deactivates the old row
  rather than deleting it.

See [`compose/oidc/`](compose/oidc/) for a compose stack that stands up Keycloak
and lets you try `oidc` mode as it actually behaves.

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
carry an attribution in place, and [NOTICE](NOTICE) reproduces the copyright notice
and permission text.

## License

MIT. See [LICENSE](LICENSE).
