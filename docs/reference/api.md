# API

The specification below is **generated from the implementation** at build time, so it
cannot drift from what the server actually does.

A running instance also serves it: Swagger UI at `/api/docs`, ReDoc at `/api/redoc`,
and the raw document at `/api/openapi.json`.

## The endpoints a role exposes

**A minter has no resolution endpoint, and a resolver has no minting endpoint.** They
are separate processes so they can scale separately and the resolver can be pointed at
a read-only replica.

=== "minter + admin"

    <div class="api-frame" markdown>
    <iframe src="../../assets/swagger.html?spec=openapi-minter.json" loading="lazy"></iframe>
    </div>

    [Open the raw document](../assets/openapi-minter.json)

=== "resolver"

    <div class="api-frame" markdown>
    <iframe src="../../assets/swagger.html?spec=openapi-resolver.json" loading="lazy"></iframe>
    </div>

    [Open the raw document](../assets/openapi-resolver.json)

## What the schema will not tell you

**Minting is idempotent if you ask it to be.** Send a `request_id` and a repeat of the
same request returns the ARK you already have, rather than minting another. Loading
tens of thousands of records means a connection will break somewhere; without a
receipt, resending would leave behind identifiers nobody points at — and ARK does not
allow those to be reclaimed.

**The shoulder in a request cannot widen anything.** Omit it and the organisation's
default is used; name one and the only question asked is whether it is already inside
your reach.

**A delegated shoulder answers 307, not a proxied mint.** If minting for that
namespace happens elsewhere, you are told where to go. arkhe does not call the other
minter for you: a lost response would leave an ARK minted over there that this ledger
has never seen.

**Bulk operations do not partially apply.** If one row in a bulk update is missing or
out of reach, the whole request fails. arklet zipped an unordered query result against
the input and could write one record's values onto another.

## Resolution

Resolution is not in the OpenAPI document in a useful form — it is one route with
behaviour that depends on the suffix.

| Request | Answer |
| --- | --- |
| `/ark:/99999/x9abc` | `302` to the target, or a description if there is none |
| `/ark:/99999/x9abc/page/3` | `302` to *target*`/page/3` — suffix passthrough, no record of its own |
| `/ark:/99999/x9abc?` | ERC/ANVL kernel — who, what, when, where |
| `/ark:/99999/x9abc??` | The above plus the persistence statement |
| `/ark:/99999/x9abc?info` | The same for a human being |
| `/ark:/99999/x9abc?json` | The same for a program |
| `/ark:/12345/…` (unknown NAAN) | `302` to the global resolver |
| `/.well-known/ark` | What this resolver holds, and where minting happens if elsewhere |

A bare `?` cannot be distinguished from no query string at the protocol level — even
in ASGI. Set `ARKHE_RAW_URI_HEADER` if something in front passes the raw URI.
