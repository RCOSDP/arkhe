# arkhe-client

A Python client for [arkhe](https://github.com/RCOSDP/arkhe): mint, update and resolve
ARK identifiers.

```python
from arkhe_client import Arkhe, Resolver

with Arkhe("https://mint.example.org", token="arkhe_...") as arkhe:
    ark = arkhe.mint(url="https://repo.example.ac.jp/records/42", title="A dataset")
    print(ark.ark)                      # ark:99999/x9tn1qkq2g7

with Resolver("https://ark.example.org") as resolver:
    print(resolver.resolve(ark.ark).target)
```

## Installing

```bash
pip install ./clients/python          # from a checkout
```

Python 3.11 or later, and one dependency: `httpx`.

## Getting in

Two ways, and the server decides which it accepts (`ARKHE_AUTH`):

```python
Arkhe("https://mint.example.org", token="arkhe_...")            # an API key, or a token
Arkhe("https://mint.example.org", client_id="ops",              # client_credentials at
      client_secret="arkhes_...", scope="ark:mint ark:read")    # arkhe's own /oauth/token
```

With a client id and secret the token is fetched on the first call and replaced before
it expires. A token that stopped working is fetched again once, since a rejected request
did nothing.

## The three things this does for you

Everything else here is the API with Python names on it. These three are decisions, and
they are the reason this exists rather than a generated stub.

**Minting carries an idempotency key.** Minting is the one call that cannot be taken
back, so a lost answer must not leave a number spent with nobody holding it. Every
`mint()` sends a `request_id`, generated here when you do not supply one, and a retry
sends the same one: the server returns the ARK it minted the first time.

```python
ark = arkhe.mint(url="https://repo.example.ac.jp/records/42")
ark.resent      # True when the server returned an earlier minting rather than a new one
```

The key worth using is one you keep beside the record you are minting for — a row id, a
job id — so that a retry days later is still recognised as the same request:

```python
arkhe.mint(url=record.url, request_id=f"record-{record.id}")
```

`mint_many()` puts a key on every row unless you pass `request_ids=False`, which is what
makes an interrupted batch safe to send again: the rows that got through are returned
rather than minted twice.

**The pointer to another minter is not followed.** When a namespace's minting is
delegated, the server answers `307` with the other minter in `Location`. Following it
would send your credential to another organisation's endpoint, which will not accept it,
and an ARK minted over there is one your ledger knows nothing about. You get told where
to go instead:

```python
from arkhe_client import Delegated

try:
    arkhe.mint(url="https://repo.example.ac.jp/records/42", shoulder="/z1")
except Delegated as sent_elsewhere:
    sent_elsewhere.minter    # https://mint.partner.example.org/api/mint, or None
    sent_elsewhere.about     # a page for people, when there is no endpoint to call
```

**Refusals carry their code.** Wording changes with a translation or a change of tone;
`ARKHE-1005` does not.

```python
from arkhe_client import ArkheError, Conflict, Throttled

try:
    arkhe.delete(ark.ark)
except Conflict as refused:
    refused.code        # "ARKHE-1501"
    refused.detail      # the structured values behind the wording
except Throttled as capped:
    capped.retry_after  # seconds, when the server said
```

`ArkheError` is the base of all of them: `BadRequest`, `Unauthorized`, `Forbidden`,
`Delegated`, `NotFound`, `Conflict`, `Throttled`, `ServerError` and `TransportError`.
The codes are listed at
[Errors](https://rcosdp.github.io/arkhe/reference/errors/).

`TransportError` is separate from `ServerError` on purpose: with no answer at all,
whether the write happened is unknown. That is the case `request_id` exists for. Only
calls that can be sent twice without acting twice are retried — a `GET`, or a mint
carrying a key. Anything else is handed back to you, because whether to repeat it is
your decision.

## What you can call

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

`update()` replaces: what you leave out is cleared. `patch()` changes only what you
pass. Both are the same endpoint, and mixing them up is quiet, so the difference is
checked against a real server in the end-to-end suite.

`unpublish()`, `delete()` and `purge()` take `confirm`, and this client never fills it
in. The server compares it with the ARK; the check exists so that a script walking a
list cannot take a published name down without a second deliberate act, and filling it
in here would remove exactly that.

## Why it is written by hand

The OpenAPI documents are generated from the server's implementation and committed, and
`check.sh` fails when they drift — they are the one description of the interface. What a
generator adds is coverage, and coverage is the part that can be checked, so
`tests/test_contract.py` compares this client with those documents: every endpoint has a
method, every method names an endpoint that still exists, and the fields of `Ark` are the
fields of `ArkOut`. An endpoint added to the server fails that file, which is the moment
to decide whether this client should carry it.

What a generator cannot add is the three decisions above.

## Checking it

```bash
uv run pytest -q clients/python/tests          # against a stub, fast
uv run pytest -q -m e2e -k python_client       # against a real minter and resolver
```

The second one needs docker: it builds the ledger with `scripts/seed_e2e.py` and runs
two `uvicorn` processes, as the server's own end-to-end suite does. A client that is
right about an imagined server is worth nothing.

## Version

This library has its own version and does not follow the server's. The API is what the
two sides agree on, and any arkhe that still serves it will work.

MIT — National Institute of Informatics.
