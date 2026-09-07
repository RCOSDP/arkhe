# Errors

Every error this API returns carries a **code**. The wording of a message can change —
it gets clearer, it gets translated — but the code does not, so **match on the code, not
on the text**.

```json
{
  "code": "ARKHE-1011",
  "message": "A request holds at most 1000 rows.",
  "detail": {"limit": 1000}
}
```

`detail` carries the values that filled the message, **still structured**, so a client
never has to cut a number back out of a sentence.

Resolution answers in `text/plain` (a person reads it too), with the code first:

```
ARKHE-1403 ark:99999/x9abcd — Check digit mismatch: the identifier looks mistranscribed.
```

Two places keep a different shape on purpose. **`/oauth/token` follows
[RFC 6749](https://www.rfc-editor.org/rfc/rfc6749) §5.2** — `error` and
`error_description`, which is what OAuth client libraries read — and adds `code`
alongside. **The admin interface** answers from its own catalogue, in the language of the screen
(`?lang=` → cookie → `Accept-Language`); it is a browser surface, not this API.

| Code | Status | Message |
| --- | --- | --- |
| `ARKHE-1001` | 400 | Not readable as an ARK: {reason} |
| `ARKHE-1002` | 400 | A qualifier must begin with '/' (a part) or '.' (a variant). |
| `ARKHE-1003` | 400 | The qualifier does not point inside the base name: {qualifier} |
| `ARKHE-1004` | 400 | The name is {length} octets; at most {limit} are indexed (Base Name plus Qualifier, draft-kunze-ark-42 §3.1). |
| `ARKHE-1005` | 400 | {ark} is already registered. |
| `ARKHE-1006` | 400 | A target must not use a scheme a browser would execute ({schemes}). |
| `ARKHE-1007` | 400 | A principal with authority={authority} must name a shoulder. |
| `ARKHE-1008` | 400 | No such shoulder: {shoulder} |
| `ARKHE-1009` | 400 | Shoulder {shoulder} exists under more than one NAAN; name the naan as well. |
| `ARKHE-1010` | 400 | The organisation has no default shoulder. |
| `ARKHE-1011` | 400 | A request holds at most {limit} rows. |
| `ARKHE-1012` | 400 | Check digit mismatch: {ark} was not minted by a NOID minter, or was mistyped. |
| `ARKHE-1013` | 400 | The name {name} does not fall inside a shoulder of NAAN {naan}. |
| `ARKHE-1201` | 401 | No credentials. |
| `ARKHE-1202` | 401 | Invalid credentials. |
| `ARKHE-1203` | 404 | This deployment does not issue tokens itself (see ARKHE_AUTH). |
| `ARKHE-1204` | 400 | Only client_credentials is supported. |
| `ARKHE-1301` | 403 | The token does not carry the required scope: {scope} |
| `ARKHE-1302` | 403 | Outside this principal's registered reach: {target} |
| `ARKHE-1303` | 403 | The principal has no active organisation. |
| `ARKHE-1304` | 403 | Shoulder {shoulder} has status={status} and cannot be minted into. |
| `ARKHE-1305` | 403 | Scopes not allowed for this client: {scopes} |
| `ARKHE-1306` | 307 | Minting for shoulder {shoulder} is delegated; go to the minter in Location. |
| `ARKHE-1307` | 403 | Shoulder {shoulder} has status={status}; only a delegated shoulder can be imported into. |
| `ARKHE-1308` | 403 | This resolver is not authoritative for NAAN {naan}; it cannot take custody of names in it. |
| `ARKHE-1309` | 403 | Minting for shoulder {shoulder} happens elsewhere and is not reachable from here. See {about} |
| `ARKHE-1401` | 404 | No such ARK in this ledger. |
| `ARKHE-1402` | 404 | This resolver is authoritative for the NAAN and has no such name. |
| `ARKHE-1403` | 404 | Check digit mismatch: the identifier looks mistranscribed. |
| `ARKHE-1404` | 404 | Metadata for an unknown NAAN is not held by this resolver. |
| `ARKHE-1601` | 429 | Daily quota exhausted: {used} of {quota} used in the last 24 hours. |
