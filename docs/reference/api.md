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
| `/ark:99999/x9abc` | `302` to the target, or a description if there is none |
| `/ark:99999/x9abc/page/3` | `302` to *target*`/page/3` — suffix passthrough, no record of its own |
| `/ark:99999/x9abc?` | ERC/ANVL kernel — who, what, when, where |
| `/ark:99999/x9abc??` | The above plus the persistence statement |
| `/ark:99999/x9abc?info` | The same again — as a page, as JSON or as ANVL, by `Accept` |
| `/ark:99999/x9abc?json` | The JSON of `?info`, named directly |
| `/ark:12345/…` (unknown NAAN) | `302` to the global resolver |
| `/.well-known/ark` | `text/plain`: the resolver's root path, ending in `/` |
| `/.well-known/ark` with `Accept: application/json` | What this resolver holds, and where minting happens if elsewhere |

A bare `?` cannot be distinguished from no query string at the protocol level — even
in ASGI. Set `ARKHE_RAW_URI_HEADER` if something in front passes the raw URI.

Every error carries a code (`ARKHE-1011`), an English `message`, and a structured
`detail`. **Match on the code, not on the wording** — see
[Errors](errors.md) for the full list.

### THUMP headers and `where`

Every answer the resolver gives about an identifier — `?`, `??`, `?info`, `?json`, a
description with no target, a hold, a `404` — carries the two headers from §5.2:

```
THUMP-Status: 0.6 404 Not Found
Link: </ark:99999/x9abc>; rel="describes"
```

The `Link` is what tells a recipient who knows nothing about inflections that the
response *describes* the uninflected ARK rather than being a representation of the URL
it fetched. The specification's own example writes it `<…> rel="describes";`; that is
not a valid [RFC 8288](https://www.rfc-editor.org/rfc/rfc8288) link value, so arkhe
emits the well-formed `<…>; rel="describes"` — the same assertion, in a form standard
parsers can read. Redirects carry neither header: a redirect is the access service, not
an answer about the identifier.

In the ERC, **`where` is the ARK, not the target** — §5.1.2 defines it as "the
long-term identifier as opposed to a transient redirect target". Changing where an ARK
points does not change its `where`; that is the whole value of the element. The current
target is published as `redirect`, outside the kernel, and only when there is one.

### `?info` answers in whichever medium you ask for

§5.2 says the form of a THUMP response is **indicated by the returned content type**,
so `?info` negotiates: a page by default, `application/json` for a program,
`text/plain` for the ANVL that `??` returns. The content is the same description and
permanence declaration each time — §5 puts both in one `?info`. `?json` remains as a
way to name the JSON directly, and both carry `Vary: Accept, Accept-Language`.

The page itself is translated (`?info&lang=en`, `Accept-Language`, then the default).
**`?lang=` cannot be used** — on this endpoint the query string *is* the inflection, so
the language goes after an `&`.

### `%`-encoded characters

A reserved character (`%`, `-`, `.`, `/`) may be `%`-encoded **to conceal its reserved
meaning** — `%2F` is the only way to write "there is a slash here, but it does not
separate components". So `ark:99999/x54%2Fc2` and `ark:99999/x54/c2` are **different
identifiers**, and the specification forbids the encoded form from ever appearing
decoded (`draft-kunze-ark-42` §3.2). arkhe reads the still-encoded path from the ASGI
`raw_path` and normalises only the hex case (`%2f` → `%2F`, step 5); it never decodes.

**Anything in front must pass the encoding through.** With nginx, `proxy_pass` without
a URI part (`proxy_pass http://backend;`) — adding a path makes nginx re-encode the
decoded one. With Apache, `AllowEncodedSlashes NoDecode`. Where a proxy normalises
`%2F` anyway, the encoding cannot be recovered and such names will not resolve.

### `/.well-known/ark`

`draft-kunze-ark-42` §5.6 registers `ark` in the Well-Known URIs registry
([RFC 8615](https://www.rfc-editor.org/rfc/rfc8615)) and defines the answer as **plain
text containing the resolver's root path, ending in `/`** — append a compact ARK to it
and you have a resolution request. **A client that sends no `Accept`, or `*/*`, gets
that**; answering such a client with JSON would make the host look like it has no ARK
resolver at all.

```console
$ curl https://ark.example.ac.jp/.well-known/ark
/
```

arkhe's own inventory — the namespaces it holds, delegated shoulders and their
`minter`, and any held namespace — is the JSON representation of the same URL, so ask
for it by name:

```console
$ curl -H 'Accept: application/json' https://ark.example.ac.jp/.well-known/ark
```

Both carry `Vary: Accept`. The path comes from the ASGI `root_path`, so if you mount
arkhe under a prefix, set it (`uvicorn --root-path /pid`) or the answer will point at a
door that is not there.
