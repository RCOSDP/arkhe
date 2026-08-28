# Quickstart

Two ways in. The compose stack is the fastest way to *see* it; the local install is
the way to *work* on it.

## With Docker

```bash
git clone https://github.com/RCOSDP/arkhe.git
cd arkhe/compose/oidc
docker compose up -d --build
```

That brings up Keycloak, PostgreSQL and arkhe — split into a minter/admin process and
a resolver process, the same way it runs in production — with a ledger already populated.

| | URL |
| --- | --- |
| Admin UI and minting API | <http://localhost:8057/admin/> |
| Resolution (**no authentication**) | <http://localhost:8058/ark:/…> |
| API reference | <http://localhost:8057/api/docs> |
| Keycloak console | <http://localhost:8080/> (`admin` / `admin`) |

Open **<http://localhost:8057/admin/>** and sign in as one of:

| User | Password | Reach |
| --- | --- | --- |
| `ops` | `arkhe-demo-2026` | system administrator, every NAAN |
| `naan-admin` | `arkhe-demo-2026` | NAAN administrator, everything under 99999 |
| `nibb` | `arkhe-demo-2026` | institution administrator, one institution |

Signing in as each in turn is the quickest way to understand what
[reach](concepts/delegation.md) means: `nibb` cannot see the other institutions, and
the audit log answers 403.

Then mint one and resolve it:

```bash
TOKEN=$(curl -s -X POST \
  http://keycloak.localhost:8080/realms/arkhe/protocol/openid-connect/token \
  -d grant_type=client_credentials -d client_id=nibb-invenio \
  -d client_secret=nibb-invenio-secret-for-demo-only | jq -r .access_token)

ARK=$(curl -s -X POST http://localhost:8057/api/mint \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"url": "https://example.org/records/1", "title": "First object"}' | jq -r .ark)

curl -i "http://localhost:8058/$ARK"     # 302 to the URL
curl "http://localhost:8058/$ARK??"      # the record and the policy behind it
```

Stop the authorization server and try both again:

```bash
docker compose stop keycloak
# minting is now 401 — resolution still answers 302
docker compose start keycloak
```

**Minting stops; resolution does not.** Resolution needs no authentication, so the
resolver holds no authentication configuration at all. Identifiers you have already
handed out do not become unresolvable because something else broke.

!!! warning "This stack is for looking at, not for running"
    The secrets are in the compose file in the clear, Keycloak runs in dev mode, and
    the demo passwords are published above. See [Deployment](guides/deployment.md).

## Locally

```bash
git clone https://github.com/RCOSDP/arkhe.git && cd arkhe
uv venv --python 3.12 && uv pip install -e '.[app,dev]'
python -m pytest -q          # 219 tests
```

Stand up a minimal ledger against SQLite:

```bash
export ARKHE_DATABASE_URL="sqlite:///$PWD/arkhe.db"
export ARKHE_AUTH=apikey
alembic upgrade head

arkhe naan add 99999 "Your organisation"
arkhe onboard 99999 "Example University" --shoulder /x9
arkhe client add univ-repo 99999 --manager 1 --scopes "ark:mint ark:update"
arkhe client key univ-repo          # the plaintext is shown once and never again
```

Run it, mint one, resolve it:

```bash
uvicorn arkhe.app:create_app --factory &

curl -X POST http://127.0.0.1:8000/api/mint \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"url": "https://example.org/records/1", "title": "First object"}'
# → {"ark": "ark:/99999/x9…", …}

curl -i "http://127.0.0.1:8000/ark:/99999/x9…"        # 302 to the object
curl    "http://127.0.0.1:8000/ark:/99999/x9…??"      # the persistence statement
```

## What just happened

You minted an identifier that **cannot be taken back**. ARK declares that names are
never re-assigned, so arkhe has no delete: an object that is lost gets a
[tombstone](concepts/invariants.md), not a deletion.

The `??` at the end asked the resolver what it promises about that identifier — a
question you can ask **even when the object itself is gone**.

## Next

- [What ARK is](concepts/ark.md) — the promise the whole design is arranged around
- [Authentication](guides/authentication.md) — three mechanisms for the API, three ways in for people
- [Configuration](reference/configuration.md) — every setting
