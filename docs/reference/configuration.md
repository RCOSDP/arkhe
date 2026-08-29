# Configuration

Everything is an environment variable prefixed `ARKHE_`, or an entry in a `.env`
file. `arkhe check` validates a configuration and stops on anything missing.

!!! danger "Secrets have no defaults, on purpose"
    `ARKHE_TOKEN_SECRET`, `ARKHE_SESSION_SECRET` and `KC_ADMIN_PASSWORD` will refuse
    to start rather than fall back to a value. A default that works is a default that
    ships to production unnoticed.

## Role

| | Default | |
| --- | --- | --- |
| `ARKHE_RESOLVER` | `false` | Run as a resolver. **A minter has no resolution endpoint and a resolver has no minting endpoint** — so the two scale separately and the resolver can point at a read-only replica |
| `ARKHE_DEBUG` | `false` | |
| `ARKHE_ALLOWED_HOSTS` | `*` | Comma-separated |

## Database

| | Default | |
| --- | --- | --- |
| `ARKHE_DATABASE_URL` | `postgresql+psycopg://arkhe@localhost/arkhe` | |
| `ARKHE_READ_DATABASE_URL` | — | Read-only connection for the resolver. Falls back to the above |

!!! warning "Verify migrations on PostgreSQL"
    SQLite tolerates things PostgreSQL does not — notably the circular reference
    between `manager` and `shoulder`, and the order in which tables are created. Both
    slipped through a SQLite-only check during development.

## Authentication — API

| | Default | |
| --- | --- | --- |
| `ARKHE_AUTH` | `apikey,oidc` | **Combinable**, tried in order. `apikey` / `oauth2` / `oidc` |
| `ARKHE_TOKEN_SECRET` | — | Signing key for `oauth2`. **32 bytes or more** (RFC 7518 §3.2) |
| `ARKHE_TOKEN_TTL` | `3600` | |
| `ARKHE_TOKEN_ISSUER` | — | |
| `ARKHE_OIDC_ISSUER` | — | Required for `oidc` |
| `ARKHE_OIDC_AUDIENCE` | — | Audience required of **API access tokens**. Not the ID token's — those carry `admin_client_id` |
| `ARKHE_OIDC_JWKS_URL` | — | Discovered from the issuer if unset |

See [Authentication](../guides/authentication.md) for which mechanism suits what.

## Authentication — the admin interface

| | Default | |
| --- | --- | --- |
| `ARKHE_ADMIN_LOGIN` | `bearer` | `bearer` / `password` / `oidc` / `proxy` |
| `ARKHE_SESSION_SECRET` | — | Required for anything but `bearer`. 32 bytes or more |
| `ARKHE_SESSION_TTL` | `28800` | Eight hours |
| `ARKHE_SESSION_SECURE` | `true` | Leave on when serving over HTTPS |
| `ARKHE_ADMIN_CLIENT_ID` | — | Required for `oidc` |
| `ARKHE_ADMIN_CLIENT_SECRET` | — | |
| `ARKHE_ADMIN_SCOPE` | `openid profile email` | |
| `ARKHE_PROXY_USER_HEADER` | `X-Forwarded-User` | For `proxy` |

!!! danger "`proxy` mode requires closing the direct path"
    If anything can reach arkhe without passing the proxy, anyone can forge the
    header. Use a NetworkPolicy on Kubernetes, or listen only on 127.0.0.1.

## Resolution

| | Default | |
| --- | --- | --- |
| `ARKHE_GLOBAL_RESOLVER` | `https://n2t.net` | Where an unknown NAAN is forwarded (D2) |
| `ARKHE_RAW_URI_HEADER` | — | Header carrying the raw request URI, so a bare `?` can be detected. A `?` with no query string is indistinguishable otherwise — even in ASGI |

## Minting

| | Default | |
| --- | --- | --- |
| `ARKHE_BULK_LIMIT` | `1000` | Rows per bulk request. Split larger loads and use `request_id` so a broken batch can simply be resent |

## Behind a proxy

| | Default | |
| --- | --- | --- |
| `ARKHE_TRUSTED_PROXIES` | `0` | How many proxies in front to believe. **`X-Forwarded-For` is a header anyone can set**, so by default it is ignored and the peer address is recorded — recording a forged value is worse than recording a coarse one, because an audit log full of attacker-written strings is the worst outcome. With `n` proxies in front, set `n`: the **n-th value from the right** is taken. Never the leftmost — that one the client wrote |
| `ARKHE_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING`. Logs are JSON lines carrying the request id |
