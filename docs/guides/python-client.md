# The Python client

`clients/python` in the repository is a Python client for the API this documentation
describes. It covers every endpoint of the minter and the resolver, and it makes three
decisions on your behalf that the API document cannot express.

```bash
pip install ./clients/python
```

Python 3.11 or later, and one dependency, `httpx`.

## Minting

```python
from arkhe_client import Arkhe

with Arkhe("https://mint.example.org", token="arkhe_...") as arkhe:
    ark = arkhe.mint(url="https://repo.example.ac.jp/records/42", title="A dataset")
    print(ark.ark)          # ark:99999/x9tn1qkq2g7
    print(ark.published)    # True — a mint without reserve is published at once
```

`token=` takes an API key or a token from elsewhere. To use arkhe's own token endpoint
instead, give it the client id and secret and it will fetch one when it first needs it,
and again when it expires:

```python
Arkhe("https://mint.example.org", client_id="ops", client_secret="arkhes_...",
      scope="ark:mint ark:read")
```

Which of these works depends on `ARKHE_AUTH`; see [Authentication](authentication.md).

## A lost answer does not cost a number

Minting cannot be undone, so every `mint()` carries an idempotency key and a retry sends
the same one. The server then returns the ARK it minted the first time rather than
minting another:

```python
ark = arkhe.mint(url="https://repo.example.ac.jp/records/42")
ark.resent      # True when this was an earlier minting coming back
```

The key is generated for you, which covers a retry inside the same call. The key worth
passing yourself is one you keep beside the record you are minting for, so that a retry
an hour or a day later is still recognised:

```python
arkhe.mint(url=record.url, request_id=f"record-{record.id}")
```

`mint_many()` puts a key on every row, which is what makes an interrupted batch safe to
send again: the rows that got through come back rather than being minted twice.

Only calls that can be sent twice without acting twice are retried. Anything else raises
`TransportError` and leaves the decision to you, because with no answer at all, whether
the write happened is unknown.

## A delegated namespace is reported, not followed

Where minting is delegated, the server answers `307` with the other minter in
`Location`, as [Delegation](../concepts/delegation.md) describes. This client does not
follow it: your credential belongs to your organisation, and an ARK minted at the other
end is one your ledger knows nothing about.

```python
from arkhe_client import Delegated

try:
    arkhe.mint(url=record.url, shoulder="/z1")
except Delegated as elsewhere:
    elsewhere.minter    # where to go, or None when there is no endpoint to call
    elsewhere.about     # a page for people, when the delegation names one
```

## Refusals carry their code

```python
from arkhe_client import Conflict, Throttled

try:
    arkhe.delete(ark.ark)
except Conflict as refused:
    refused.code        # "ARKHE-1501" — the part that does not change
    refused.detail      # the values behind the wording
except Throttled as capped:
    capped.retry_after  # seconds, when the server said
```

`ArkheError` is the base of them all: `BadRequest`, `Unauthorized`, `Forbidden`,
`Delegated`, `NotFound`, `Conflict`, `Throttled`, `ServerError` and `TransportError`.
The codes are listed under [Errors](../reference/errors.md).

## Resolving

The resolver takes no credential, so it is a separate object:

```python
from arkhe_client import Resolver

with Resolver("https://ark.example.org") as resolver:
    found = resolver.resolve("ark:99999/x9tn1qkq2g7")
    found.target            # where it redirects
    found.description       # or, when it did not redirect, what came back instead
```

A redirect is not the only success. A reserved ARK, one whose redirection is
[held](../reference/configuration.md) and a tombstoned one all resolve to a description,
and `target` is then `None`. `describe()` asks with `?json`, which never redirects, and
`statement()` asks with `??` for what this ledger promises about the name.

## What else there is

| | |
| --- | --- |
| minting | `mint`, `mint_many`, `register` |
| taking in | `import_ark`, `import_many` |
| changing | `update` (replaces), `patch` (only what you pass), `update_many` |
| publication | `publish`, `unpublish`, `delete`, `purge` |
| saying it is gone | `tombstone` |
| stopping redirection | `hold`, `release_hold` |
| reading | `query`, `stats` |
| resolving | `Resolver.resolve`, `describe`, `statement`, `inventory`, `exists` |

`update()` replaces and `patch()` does not, on the same endpoint. `unpublish()`,
`delete()` and `purge()` take `confirm`, and the client never fills it in: the server
compares it with the ARK so that a script walking a list cannot take a published name
down without a second deliberate act.

## Why it is hand-written

The [OpenAPI documents](../reference/api.md) are generated from the implementation, so
they are the one description of the interface, and a generated client would be the
obvious answer. What a generator gives is coverage — and coverage is the part that can
be checked: `clients/python/tests/test_contract.py` compares the client with those
documents in both directions, so an endpoint added to the server fails the build until
someone decides whether the client should carry it.

What a generator cannot give is the three decisions above. They are why this exists.

The client is checked against a stub for what it decides, and against a real minter and
resolver for whether that matches what the server does:

```bash
uv run pytest -q clients/python/tests          # fast
uv run pytest -q -m e2e -k python_client       # needs docker
```

## Another language

There is no client for anything but Python yet. For one, generate it from
`docs/assets/openapi-minter.json` and add the same three things by hand: the
idempotency key on minting, refusing to follow the `307`, and the `ARKHE-xxxx` code on
every refusal. Those are what makes a client safe to point at a ledger whose identifiers
cannot be reissued.
