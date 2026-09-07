# Changelog

*[日本語](CHANGELOG.ja.md)*

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/) — see
[the policy](https://rcosdp.github.io/arkhe/project/versioning/) for what counts as
breaking in a system whose identifiers cannot be reissued.

## [Unreleased]

### Added

- **`PATCH /api/update` writes only the fields you send.** `PUT` on that path is a
  replacement — omit `title` and it is emptied — which is correct for a replacement and
  wrong for what people do most: move an object. Repointing an ARK no longer costs it
  its description. Sending a field as `""` still clears it, so removing a value remains
  possible; the two cases have to stay distinguishable.

- **`?info` answers in whichever medium the client asks for.** §5.2 says the form of a
  THUMP response is indicated by the returned content type, so `?info` now negotiates:
  a page by default, JSON for `Accept: application/json`, and the ANVL of `??` for
  `Accept: text/plain`. The content is the same description and permanence declaration
  each time — §5 puts both in one `?info`. **`?json` stays** as a way to name the JSON
  directly, and returns exactly what `?info` does under that Accept.

- **The `?info` page is translated.** It is a public endpoint — an ARK is resolved from
  anywhere — and it spoke only Japanese, so the identifier arrived and the explanation
  could not be read. It now takes its words from the same catalogue as the admin
  interface, including the persistence level's display name, which also reaches
  `?json`'s `commitment_label`. **`?lang=` cannot be used** on this endpoint, because the
  query string is the inflection; the language goes after an `&` (`?info&lang=en`), or
  comes from `Accept-Language`.

- **A walkthrough that follows one identifier end to end**, in
  [From minting to resolving, with curl](https://rcosdp.github.io/arkhe/guides/walkthrough/):
  minting, resolution, suffix passthrough, registering one qualified point, moving the
  object, a hold, a tombstone, the error codes, and what the resolver says about itself.
  **Every response on the page was copied from a running instance**, not written by hand.

- **Each operation now states the scope it requires.** The specification said
  `{"oauth2": []}` — that a token gets you in, but **not what it has to carry** — so a
  client generated from it had no choice but to ask for every scope.

      POST /api/mint       {"oauth2": ["ark:mint"]}
      PUT  /api/tombstone  {"oauth2": ["ark:tombstone"]}
      POST /api/query      {"oauth2": ["ark:read"]}

  Only the oauth2 requirement carries scopes: `bearer` is `type: http`, and OpenAPI
  **does not allow scopes on anything but oauth2** (the array must be empty). A test
  holds each declaration to the check performed in the handler.

- **The OpenAPI document now says how to get a token.** There was no
  `clientCredentials` flow in `securitySchemes` — no `tokenUrl`, no scope list — so
  nothing stated in machine-readable form that this is OAuth 2.0. The endpoint's URL
  lived only in the README and the guide, so a client generated from the specification
  had no way to authenticate. Swagger UI's Authorize button now works too.

  **It is advertised only where `ARKHE_AUTH` includes `oauth2`**; advertising an
  endpoint a deployment does not serve would send generated clients into a 404. The
  scope vocabulary comes from `authz.SCOPES`, and the wording from the same terms the
  admin interface uses.

- **How to hold on to a token** is now in
  [the authentication guide](https://rcosdp.github.io/arkhe/guides/authentication/):
  fetch a new one shortly before `expires_in` runs out, **not once per API call** —
  issuing a token verifies `client_secret` with Argon2, so fetching per call pays the
  same cost as `apikey` and adds a round trip on top.

### Changed

- **`/.well-known/ark` now answers `text/plain` by default, as the specification
  requires.** `draft-kunze-ark-42` §5.6 registers `ark` in the Well-Known URIs registry
  (RFC 8615) and defines the answer as **plain text containing the resolver's root path,
  ending in `/`** — append a compact ARK to it and you have a resolution request. arkhe
  had claimed the same path first, for its own JSON inventory, so **a client reading the
  specification would conclude the host has no ARK resolver.**

      $ curl https://ark.example.ac.jp/.well-known/ark
      /

  The inventory — namespaces held, delegated shoulders and their `minter`, held
  namespaces — is now the JSON representation of the same URL: ask for it with
  `Accept: application/json`. **This is a change for anything already reading that JSON
  without an `Accept` header**; the body is otherwise the same, plus `resolver_path`.
  Both representations carry `Vary: Accept`.

  The path comes from the ASGI `root_path`, so a deployment mounted under a prefix must
  set it (`uvicorn --root-path /pid`) or it will publish a door that is not there.

### Fixed

- **The ARK concept page said too little, and pointed nowhere.** Its diagram labelled
  only "NAAN" and "name", which leaves out the label, the shoulder, the blade and the
  qualifiers — the parts that make the string readable without fetching anything. The
  anatomy now follows [arks.org](https://arks.org/), including their locksmithing
  metaphor, and the page says plainly that it is an orientation and that arks.org is
  where the scheme itself lives.

- **The quickstart's local example could not resolve.** It started one process and
  curled `/ark:99999/…` at it, but the resolution endpoint only exists when
  `ARKHE_RESOLVER=1` — a single process answers `404`. That separation is deliberate, so
  the example now starts both. Parse errors also stopped repeating themselves
  (`Not readable as an ARK: Not a valid ARK: missing name part`), and an empty NAAN no
  longer claims to be too long.

- **A link inside the Japanese invariants page was dead.** `#ark` pointed at nothing;
  the heading it meant is `#ark-は削除しない`. mkdocs reports a broken in-page anchor as
  `INFO`, so `--strict` never stopped it — the link had been quietly dead since the
  heading was written. `check.sh` and `deploy-docs.sh` now fail on it, because to a
  reader it is the same broken link as any other.

- **The admin interface switches languages, but its refusals did not.** The screen
  picks `?lang=` → cookie → `Accept-Language`, yet fifteen refusals — "outside your
  reach", "needs NAAN-wide authority", the login screen's "wrong ID or password" — were
  hardcoded Japanese, so an English session **fell back to Japanese at exactly the moment
  it was already stuck**. They now come from the same catalogue as the screen, which
  means a missing translation fails at start-up like every other key.

- **Start-up configuration errors are English.** `Settings.check()` refuses a
  half-configured deployment before it serves anything; those messages go to an
  operator's console, alongside the container logs, and are now in the same language as
  the rest of what arkhe prints there.

- **Errors now carry a code, and their bodies are English.** The wording of a message
  changes — it gets clearer, it gets translated — so a client that matched on text was
  building on sand. Every error the API and the resolver return now looks like

      {"code": "ARKHE-1011",
       "message": "A request holds at most 1000 rows.",
       "detail": {"limit": 1000}}

  with `detail` holding the values that filled the message, **still structured**, so a
  number never has to be cut back out of a sentence. Resolution answers `text/plain`
  with the code first (`ARKHE-1403 ark:99999/x9abcd — Check digit mismatch: …`).

  The full list is [the errors reference](https://rcosdp.github.io/arkhe/reference/errors/),
  generated from one registry (`arkhe.errors`) that holds the code, the status, the
  English message and a Japanese explanation together — a test fails if a code is
  missing from either page, is reused, or has only one of the two languages.

  **`/oauth/token` keeps its own shape on purpose**: RFC 6749 §5.2 (`error` /
  `error_description`, which is what OAuth libraries read), with `code` added alongside.
  The admin interface keeps its own catalogue, because it answers in the language of the
  screen rather than in the language of this API.

- **The published OpenAPI document was in Japanese.** FastAPI and Pydantic turn a
  handler's or a model's docstring into the `description`, and this codebase comments in
  Japanese — so the specification did too, for readers who are outside this ledger and
  cannot be assumed to read it.

  Every string the document publishes is now English: the overview, the tag
  descriptions, each endpoint, each response code, the request schemas and their fields,
  and both security schemes. **The docstrings stay in Japanese** — they are for people
  reading the implementation, a different audience — so the English text is passed
  explicitly (`description=` on the route, `model_config` on the model), which FastAPI
  and Pydantic prefer over the docstring.

  A test walks the generated document for both roles and fails on any CJK character, so
  a new endpoint cannot leak its docstring into the specification by being forgotten.

- **The label was matched case-sensitively by the router.** `parse_ark` had always been
  case-insensitive, as §3.2 step 3 requires, but the HTTP routes were literal, so
  `/ARK:/99999/x9abc` never reached the resolver and came back `404`. The label — those
  five characters only — is now normalised before routing. **The name's case is left
  alone**, because it is part of the identifier (step 5).

- **The THUMP response headers were missing.** §5.2 shows `THUMP-Status` and a `Link`
  header on an inflection response, and says what the latter is for: telling a recipient
  who knows nothing about inflections that the response *describes* the uninflected ARK.
  Both are now on every answer the resolver gives about an identifier (`?`, `??`,
  `?info`, `?json`, a description, a hold, a `404`), and on none of the redirects.

  The `rel` is written `<…>; rel="describes"` rather than the specification example's
  `<…> rel="describes";`, which is not a valid [RFC 8288](https://www.rfc-editor.org/rfc/rfc8288)
  link value — the same assertion, in a form standard parsers can read.

- **The ERC `where` held the redirect target instead of the identifier.** §5.1.2 defines
  it as "the long-term identifier as opposed to a transient redirect target"; arkhe had
  it the other way round, with the ARK only as a fallback when no target was set. Since
  a description answers *what this identifier denotes*, a value that moves when the
  target moves cannot be quoted. `where` is now the compact ARK — repointing an ARK no
  longer changes it — and the current target is published as `redirect`, outside the
  kernel and only when there is one. **This changes `?`, `??`, `?json` and the `?info`
  page**; anything reading a target out of `where` must read `redirect`.

- **New ARKs were generated in the old `ark:/` label form.** §2.2 asks implementations
  to **generate the new form** (`ark:99999/x9abc`) while continuing to recognise both
  *in perpetuity*. arkhe recognised both — but everything it emitted carried the old
  label, so the strings it handed out became the next implementation's input and the
  old form never shrank.

  Every generated ARK is now new-form: the `ark` field of every API response, the ERC
  `where` and `about`, `?json`, the 404 body, the `Location` when forwarding to another
  resolver or to N2T, the CLI's `ark list`, and the admin interface. The label is
  chosen in one place (`arkspec.naming.compact_ark`) so it cannot drift apart again.

  **Reception is unchanged and will not narrow**: `ark:`, `ark:/` and a bare
  `99999/x9abc` all still address the same identifier, and a test holds that open.

  This changes the shape of published output — anything parsing `ark:/…` out of an API
  response or CLI line must accept `ark:…`. **A ledger is not touched**: the stored key
  has never included the label.

- **Two field widths sat below what the specification obliges a receiver to accept.** A
  NAAN was rejected above 10 octets and a name was stored in `varchar(100)`, while
  `draft-kunze-ark-42` requires support for **16 octets of NAAN** (§2.3) and **255
  octets of Base Name plus Qualifier** (§3.1).

  The NAAN limit had a reason, but not one that applies here: arklet passes the NAAN to
  `int()` and guarded the conversion with `len(naan) > 10`, and the constant came across
  with the rest of the parsing. **arkhe decided the opposite in N2** — the NAAN is kept
  and compared as a string, never integerised, so that `ark:/099999/…` and
  `ark:/99999/…` stay distinct — which left the guard with nothing to guard.

  `naan.naan` is now `varchar(16)`, `ark.assigned_name` `varchar(255)`, and the ledger
  key `ark.ark` `varchar(272)` (16 + `/` + 255); every column holding a NAAN or an ARK
  moved with them. On PostgreSQL this is a metadata-only change — no table rewrite, no
  index rebuild. A name longer than 255 is now refused with a `400` naming the limit
  rather than failing in the database.

- **`%2F` in a name was silently turned into a component separator.** ASGI decodes the
  request path before the application sees it, so `ark:/99999/x54%2Fc2` arrived as
  `x54/c2` — **a different identifier**. A reserved character may be `%`-encoded
  precisely *to conceal its reserved meaning* (`draft-kunze-ark-42` §3.2), so `%2F`
  means "a slash that does not separate components"; decoding it made suffix
  passthrough inherit an unrelated record's target, and forwarded a rewritten ARK to
  the global resolver. The same applied to `%7D`, whose decoded form `}` is not even in
  the ARK character repertoire (§3.1) — the encoding is the only legal way to carry it.
  The specification states it plainly: *no %-encoded character should ever appear in an
  ARK in its decoded form.*

  Resolution now reads the still-encoded path from the ASGI `raw_path`, and hex case is
  normalised (`%2f` → `%2F`, normalisation step 5) on both the resolving and the
  registering side, so a qualifier registered as `/a%2fb` is found when requested as
  `/a%2Fb`. **A proxy in front must pass the encoding through** — see
  [the API reference](https://rcosdp.github.io/arkhe/reference/api/) for nginx and
  Apache.

- **Bulk minting returned a 500 when one request carried the same `request_id` twice.**
  A receipt is unique per (client, request_id), so writing the second one raised an
  IntegrityError and **nothing was minted at all**. The same `request_id` means the same
  single request, so one ARK is now minted and returned for both rows — the promise that
  covers resends now holds inside a batch too.

- **Response codes and media types were missing from the specification.** The 200
  returned on a resend (`POST /api/mint` and `/api/mint/bulk`) and resolution's 3xx, 400
  and 404 were not declared, so generated clients treated them as unknown responses.
  Resolution's 200 also declared only `application/json`, **omitting ANVL
  (`text/plain`) and the HTML of `?info`**. A redirect is one of 301, 302, 303 or 307 —
  a shoulder's delegation template may name the code. Tests now hold the declaration and
  the implementation together.

- **The published API specification had no description for minting or resolution.**
  FastAPI turns a handler's docstring into the OpenAPI `description`, and three
  handlers had none — `POST /api/mint`, `POST /api/mint/bulk` and `GET /ark:…` (four
  operations). The other nine were documented, so it was exactly the two most-used
  endpoints that were blank. They now describe replay handling (201 vs 200), the
  all-or-nothing rule for bulk minting, and when resolution answers with something
  other than a 302.

- **`arkhe naan list` and `arkhe shoulder list` had no description**, leaving those two
  rows blank in `--help` and in the CLI reference, where the other 22 commands are
  filled in for both languages.

- **The `ark:hold` scope had no label in either language, so the admin interface showed
  the raw key `sc.ark:hold`.** It was missed when the scope was added in 0.0.9. The
  existing check for missing translations compares the two catalogues against each
  other, so a term absent from **both** passes it. The labels are in, and a check now
  requires every entry of `SCOPES` to have one.

- **An internal knob, `read_only`, was exposed as a query parameter on every endpoint.**
  FastAPI publishes a dependency's arguments as query parameters, so declaring
  `get_session(*, read_only=…)` as a dependency meant a caller could send
  `POST /api/mint?read_only=true` and **point a minting write at the read replica**
  (only harmful where `ARKHE_READ_DATABASE_URL` is set). The argument is gone; the
  connection is now chosen by the **process's role** (`ARKHE_RESOLVER`), read from
  **the settings the app was actually built with** — reading the cached
  `get_settings()` directly would let it diverge from what `create_app(settings=…)`
  was given, so router mounting and connection routing would consult different
  configuration.

  With it, `ARKHE_READ_DATABASE_URL` **takes effect for the first time**. The setting
  was read, but nothing ever passed `read_only=True`, so the resolver was reading from
  the write engine — a replica was never actually used.

## [0.0.9] — 2026-08-31

**The release that can stop a redirect without killing the identifier.** A delegate's
resolver goes down, a wrong URL goes out, a takedown is requested — each wants stopping
quickly, and yet `404` would be a lie and `503` makes a permanent identifier look broken.
What stops is **redirection only**; resolution and descriptions carry on. It also
documents running several arkhe instances together (closed PIDs and open PIDs included),
and replaces CI with local scripts for checking and publishing.

### Added

- **A guide to running several arkhe instances**
  ([Running several arkhe](https://rcosdp.github.io/arkhe/guides/federation/)): dividing
  by NAAN, dividing by shoulder under one NAAN, and putting an arkhe inside a closed
  network whose namespace alone is known above — plus the option of connecting nothing.
  **What may be divided is the namespace, never the authority over a single namespace**:
  splitting the ledger moves several invariants out of the code and into the hands of
  operators, so the guide tabulates which ones. It also states why a delegate must
  produce check digits (resolution verifies the check digit before it looks at the
  shoulder delegation) and **what does not exist yet** — no endpoint for importing an ARK
  minted elsewhere, no CLI for `shoulder.redirect`, no cross-ledger listing or audit.
  Twelve Mermaid diagrams.

- **Closed PIDs and open PIDs**, on the same page: how to hand out identifiers for
  material that cannot be published, so that **when the embargo lifts, publication is one
  change of target** — written out as ledgers and commands. What is divided is the
  shoulder, **never the shape of the identifier**: if the shape changed, every reference
  handed out while it was closed would die at the moment of publication. What outsiders
  can see is set out in three levels (invisible / described / with a door), and **the
  most common one — "available on request" — is built by pointing `url` at the
  application form**. It also states that **arkhe does no access control**: a closed PID
  is closed because its target is, not because arkhe turns anyone away.

- **[STATUS.md](https://github.com/RCOSDP/arkhe/blob/main/STATUS.md)**, collecting the
  version, the state of the checks and the known gaps in one place. **Procedure lives in
  AGENTS.md, current position in STATUS.md** — kept apart because duplicating them
  guarantees one of the two goes stale.

- **Checks and publishing consolidated into local scripts; GitHub Actions removed.**
  `.github/workflows/{ci,docs,release}.yml` are gone and the same work moved into three
  scripts under `scripts/` — **nothing that was being watched is watched any less**.

    * `check.sh` — sync (`--frozen`) → ruff → pytest → **a disposable PostgreSQL with the
      migrations round-tripped** (plus `alembic check`) → OpenAPI drift → `mkdocs --strict`
    * `deploy-docs.sh` — check, build, publish to gh-pages
    * `release.sh` — version match, changelog sections in both languages, `check.sh`,
      `dist/`; it creates a tag and a GitHub release only with `--publish`

  **One system rather than two.** Split between a laptop and CI, a change that "passes on
  one side" appears and before long nobody looks at the other side. **A check whose
  tooling is missing prints SKIP instead of passing quietly** — "it passed because it
  wasn't installed" is the dangerous outcome. `deploy-docs.sh` takes over what checkout
  did in CI: it stops on uncommitted changes and warns when HEAD is not on the remote,
  both to prevent **content that is on the site but cannot be traced in the repository**,
  which is exactly what loosens when publishing happens from a laptop. Dependabot's
  `github-actions` ecosystem was dropped along with the workflows it watched.

### Fixed

- **The committed OpenAPI specs had fallen behind the implementation**
  (`docs/assets/openapi-*.json` still said `version: 0.0.1`). The published spec was
  regenerated on every build, so nothing shipped wrong, but the repository disagreed with
  itself. The check script **caught this on its first run**, and now fails when the two
  drift apart.

- **The icons in "Where to start" on the front page were not rendering** — the literal
  string `:material-api:` was being published, because `pymdownx.emoji`, the extension
  that turns those into SVG, was not configured. **An unknown shortcode passes through as
  plain text**, so nothing warns and `mkdocs build --strict` cannot catch it.

- The README's link to the ER diagram pointed at a location the page had moved from
  (`docs/data-model.md`); reference pages live under `docs/reference/`. The test count
  quoted there was updated too.

## [0.0.8] — 2026-08-29

**The most common way to get stuck in an OIDC deployment now shows itself.** A
`client_id` off by one character produced a silent 401; the ledger now keeps what it
rejected, so it can be registered without retyping. The demo ledger also stops carrying
real institutions' names.

### Added

- **Subjects that arrived from the authorization server with no registration are now
  shown.** One wrong character in a `client_id` produces a 401, silently — the most
  common way to get stuck in this configuration. **At the moment of rejection arkhe
  already holds the right string** (`azp` has passed signature verification), so it is
  kept, listed, and can be registered from there without retyping. No credentials for
  the authorization server are involved. **Disabled subjects are not mixed in**: listing
  a deliberately stopped principal as "not registered" would mean registering it again
  to clear the list.

### Changed

- **Real institution names and NAANs are out of the demo ledger** (`seed_demo.py`,
  `realm-arkhe.json`). Real names read as if those institutions were users. The sign-ins
  are `ops` / `naan-admin` / `org-admin`, the organisations are illustrative, and the
  NAANs are `99999` (reserved for testing by the specification) plus `12345` / `54321`.

- **The admin interface's strings are split by screen** (`api/i18n/`). 288 entries in
  one file meant reading the whole file to find one word. **Split by screen, not by
  language** — separate files per language put the pair out of sight, and adding one
  side only stops showing up in the diff. The catalogues are byte-identical before and
  after; nothing on screen changed.

## [0.0.7] — 2026-08-29

**Two things the ledger could do that the terminal could not, and a piece of
documentation that was telling people the wrong thing.** Neither is a change to how
identifiers behave.

### Added

- **`AGENTS.md`.** The working procedure and **the traps actually hit during
  development**. People and coding agents get the same document — a rule written for
  only one of them is broken by the other.
- **A check that the reference pages have not fallen behind the code**
  (`tests/test_docs.py`). Contributing claimed the configuration and CLI pages were
  generated; they are not, and **two settings and one command had gone undocumented**
  because of it (`ARKHE_TRUSTED_PROXIES`, `ARKHE_LOG_LEVEL`, `arkhe manager policy`).
  The claim is corrected, the gaps are filled, and the gap cannot reopen silently.

- **`arkhe ark list`.** The admin screen listed minted ARKs; the CLI could not. Both
  now go through the same query (`domain/queries.py`) — **write reach in two places and
  the two drift**. It stops at 50 by default and says so on stderr, with the `--offset`
  to continue from; silence would read as "that is all of them".

## [0.0.6] — 2026-08-29

**A build-only release: the same commit now builds into the same thing.** Nothing under
`src/` was touched, so no behaviour changed. The reason to take it is that from here on,
an image rebuilt from a given tag holds what that tag was tested with.

### Changed

- **Dependencies are pinned in `uv.lock`.** The declarations carry only lower bounds,
  so without it **the same commit builds into something different** each time — the
  image changes under a rebuild and "when did this break" becomes unanswerable. CI and
  the image build use `uv sync --frozen`, which fails if the lock and `pyproject.toml`
  disagree. **No upper bounds**: with a lock they are unnecessary, and they make the
  package harder to live with as a dependency. Dependabot proposes grouped updates
  weekly, and only ever moves the lock: raising the declared floor to whatever happens
  to be installed would assert that older versions do not work, without checking.

## [0.0.5] — 2026-08-29

**One vulnerability on the public surface closed, and the `NR` claim made checkable.**
Both concern identifiers already handed out, so they are cut as their own release.

Most of this came out of reading the code through; the rest came out of actually using
the interface.

### Added

- **The rules of a namespace now live on the NAAN** (ways in, self-registration, scope
  ceiling). They could only be set per organisation, which **stops being practical as
  organisations grow** — nobody applies the same restriction to 800 institutions one at
  a time. A per-organisation setting can only **narrow** the namespace rule. The
  composed result is decided in one place and used at issuance, registration **and
  authentication**.
- **A record of where an ARK used to point** (`ark_change`). Without it the previous
  target could not be recovered, so a system declaring `NR` gave its users no way to
  check that claim. It is separate from the audit log, which keeps only what reaches
  NAAN scope — and **minting and repointing are done by organisations**.
- **A list of the ARKs issued**, filtered by reach, filterable by organisation, with a
  detail page showing everything `?` and `??` publish. **Search and paging are there
  from the start**, because the count only ever grows.
- **Users can be registered and keys issued and revoked from the interface.** The
  "Open" and "Register a user" buttons pointed at routes that did not exist. **People
  are offered no key** — one would outlive the person's departure.
- `arkhe client disable` / `enable` and the same control in the interface. **Where
  authentication is delegated this is the only way to stop a user from arkhe's side.**
- **Structured logs, a request id and `/readyz`.** There was no way to investigate an
  incident but to read the database, and sharing `/healthz` meant a pod **stayed Ready
  while its database was unreachable**. Authentication failures are recorded
  server-side only.
- **Signing in and out are audited**, without the reach filter: **a failed sign-in is
  the entry you want to see before the successful ones**.
- The minting form offers resource types (DataCite's `resourceTypeGeneral`). **Not a
  constraint** — ERC's `what` defines no vocabulary, so anything can still be typed.
- A logo: the **α** of ἀρχή, drawn as paths, also used as the favicon.

### Fixed

- **A stored XSS on the public resolver.** Targets had no scheme restriction, so
  `javascript:` could be minted — and `?info` needs no authentication, so anyone
  holding `ark:mint` could get a script running in the resolver's origin on someone
  else's browser. **Registration itself is not narrowed**: an ARK can name a physical
  object or another identifier, so `urn:`, `doi:` and `ark:` are legitimate. Only
  schemes that execute in a browser are refused, and **whether a browser may be sent
  there is decided separately**. The pages carry a CSP.
- **Prepared the lists for the scale that breaks them.** The organisations page
  aggregated the whole `ark` table on every load (300k rows read → 7,500 under the same
  conditions). Search and paging were added to the users list and the audit log, which
  **stopped at the most recent 200 entries**.
- **Buttons and links that would only be refused are no longer shown.** A test walks
  every link shown to each kind of principal and asserts none is refused.
- Where authentication is delegated, **a correctly configured user looked
  unconfigured** — it holds no key, so the list said "0 credentials active". The column
  now says how it gets in, and **a key whose mechanism is disabled does not count**.
- **Keys could be issued that the deployment would never accept.**
- The per-organisation restrictions **looked as though they could not be applied**,
  sharing a card with the commitment level the organisation declares for itself.
- An expired sign-in round trip answered with bare text and **no way back**.
- On a phone the **tables were cut off** and **logging out was impossible** (the
  control lived in a sidebar that folds away).
- Logging out was a GET; `SameSite=Lax` **does send the cookie on a top-level GET**.
- Anchors for Japanese headings were `_1`, `_2`, … so **deep links did not work**.
- A foreign key that was declared but never created: `use_alter` inside
  `create_table` does not become a deferred ALTER, so `alembic check` was right.

### Changed

- `api/admin.py`, 1,100 lines, split by screen (316 at most). **Lines were moved;
  nothing was rewritten.**
- Scopes and the organisation restrictions are chosen with checkboxes from a single
  vocabulary. Free text let you **register spellings that are never checked**.

## [0.0.4] — 2026-08-29

Only what came out of actually using the admin interface. **Buttons that do nothing
when pressed**, and **a principal that could not be stopped** — both cases of the
interface saying one thing while the implementation did another.

### Added

- **Users can be registered and keys issued and revoked from the interface.** The
  "Open" and "Register a user" buttons pointed at routes that did not exist and
  returned 404. The plaintext appears only in the response to the issuing request
  (a redirect would lose it). **People are offered no key**: one would outlive the
  person's departure from the organisation. An organisation's own administrator can
  manage its users.
- `arkhe client disable` / `enable`, and the same control in the interface.

### Changed

- The user page under a delegated authentication setup shows **where that
  authorization server is** (the issuer). Saying the secret is created at the
  authorization server is no help if the page does not say which one.
- The language switcher on the sign-in and notice pages is now **the same icon control
  as the admin interface**. A row of segments breaks as soon as a third language is
  added.
- The setup guide gained the procedure for creating a key at the authorization server
  (the Keycloak console and its Admin API) and a table of where to rotate and where to
  stop.

### Fixed

- **Where authentication is delegated, there was no way to stop a user from arkhe's
  side.** Under `oidc` arkhe holds no credential, so `revoke` has nothing to act on,
  and nothing anywhere cleared `Client.active` — a token the authorization server kept
  issuing kept working. Having said that authenticating and being allowed into the
  namespace are different questions, arkhe could not take back its answer to the
  second. **A principal of an organisation that has left cannot be restored**, so an
  individual restore cannot undo a departure.
- Under a delegated setup, "Register a user" did not say **what the operation is
  for.** No key is issued, so it looks as though nothing happens — but **this
  registration is what ties a subject at the authorization server to a reach in
  arkhe**, and without it even a valid token is refused. The page now says which claim
  to enter (`azp` → `client_id` → `sub` for a machine, `preferred_username` → `email`
  → `sub` for a person).
- **Keys could be issued that the deployment would never accept.** `authenticate` only
  tries the mechanisms listed in `ARKHE_AUTH`, so a `client_secret` issued where
  `oauth2` is not enabled goes nowhere — which was the case in the compose demo. The
  kinds on offer are now derived from the enabled mechanisms.
- **Buttons and links that would only be refused are no longer shown.** An
  organisation's administrator was shown the audit log link, which answered 403 when
  pressed, and the minting link appeared for principals without `ark:mint`. The
  visibility test is the same expression the route uses — written separately, it turns
  into the opposite hole. A test walks every link shown to each kind of principal and
  asserts none is refused.
- When a sign-in round trip expired, the response was bare text with **no way back —
  the user had to edit the URL by hand**. It is now a page sharing the sign-in layout,
  with a "Sign in again" button.
- On a phone the **tables overflowed and the right-hand columns could not be read**.
  The card's `overflow: hidden` meant the page did not widen; the content was simply
  **cut off**. Below 640px each row is folded into a card with a label before every
  value.
- **Logging out was impossible on a narrow screen.** The control was an unlabelled
  icon at the foot of the sidebar, and the sidebar is folded away below 860px. It has
  moved into the header.
- Anchors for Japanese headings were `_1`, `_2`, … The default slugify drops
  non-ASCII, so **deep links into Japanese pages did not work**, and adding one
  heading shifted the numbers so existing links silently pointed elsewhere.
- Writing a changelog entry did not update the published site: the `docs` workflow's
  path filter did not include `CHANGELOG*.md`, which the pages pull in with `--8<--`.
- The versioning page hard-coded the current version and had gone stale at 0.0.1.
  **Anything that goes stale at every release does not belong in the prose.**

## [0.0.3] — 2026-08-29

The admin interface went from a page that only mints to one that **builds the
ledger**. As in 0.0.2, every defect here was found by actually using the interface;
none of them showed up in the test suite.

### Added

- **The admin interface can now build the ledger.** The four buttons on the overview
  — register a NAAN, onboard an organisation, carve out a shoulder, manage one —
  **pointed at routes that did not exist and returned 404**. They now work, and
  settings pages for NAANs, organisations and shoulders were added alongside them.
- **The commitment level can be set** (`arkhe manager commitment`,
  `arkhe onboard --commitment`, and the admin interface). It was published by `?` and
  `??` but could not be set, so every organisation silently carried the default
  `permanent-dynamic` — claiming, in the organisation's name, a commitment it never
  made. **Publishing an undeclared default as a declaration is worse than publishing
  nothing.** Onboarding without `--commitment` now says so on stderr, and unknown
  levels are refused. **An organisation's own administrator may change theirs**: the
  commitment is the organisation's, and a declaration nobody can make is not a
  declaration.
- `arkhe manager list`. Organisation ids are input to other commands, but nothing
  listed them.
- `set_quota`, so a minting limit can be changed after onboarding rather than only at
  it. An organisation cannot change its own: a limit the receiving side can lift is
  not a limit.
- **The CLI speaks Japanese and English.** The language is decided from the
  environment at startup — `ARKHE_LANG`, then `LC_ALL` / `LC_MESSAGES` / `LANG` in
  POSIX order, defaulting to `ja` as the admin interface does. Typer assembles its
  help at import time, so a runtime `--lang` cannot work.
- **A guide for setting up from scratch**, in both languages, covering the steps that
  happen **outside** arkhe as well — requesting a NAAN, and registering your
  resolver's URL in the NAAN registry. Miss the latter and `n2t.net/ark:/99999/…`
  never reaches you.
- `compose/oidc/lan.yml`, for viewing the demo from another machine on the LAN.
  Publishing on `0.0.0.0` is not enough on its own: the issuer and redirect_uri have
  to be the URL the browser actually types, so they are parameterised by
  `ARKHE_DEMO_HOST` and the redirect is registered at startup rather than baked into
  the realm JSON. The default binding stays on `127.0.0.1` — this stack carries its
  secrets in the clear.

### Changed

- **The interface is written for someone opening the ledger for the first time.** The
  overview is called **Organisations** rather than "Delegation". Buttons say what they
  do: "Add an organisation", not "Onboard an organisation"; "Add a namespace", not
  "Carve out a shoulder". The form for adding an organisation says up front that it
  hands over a namespace at the same time. "Principals & credentials" is now "Users &
  keys" — what is listed there is not the organisations themselves but their systems
  and their people — and the minting form asks for a *namespace to mint in*, since
  what is chosen there is a NAAN and a shoulder together, not a shoulder alone.
  Commitment levels no longer appear as bare machine values.
- **The terms are kept, in parentheses**: "namespace (shoulder)", "Permanent; content
  may change (permanent-dynamic)". The plain wording comes first and the term follows,
  so a newcomer can read it as it stands and someone who knows the term can line it up
  with the specification, the CLI and the API.
- The word for the entity a namespace is delegated to is now **organisation**
  throughout, and a NAAN is an "organisation number (NAAN)" — it is a *Name Assigning
  Authority Number*, and the number belongs to the organisation.
- The documentation states that "users" in the interface and "principals" in the API
  and CLI are the same thing. **The two words stay**, because the readers differ.

### Fixed

- **Logging out did not log you out.** The session cookie was cleared, but the
  authorization server's session was left standing, so opening the interface again
  signed you straight back in without asking. Under OIDC the logout now ends that
  session too (RP-Initiated Logout). No `id_token_hint` is sent: carrying the ID token
  in the cookie would push it past 4 KB where claims are numerous, and **the browser
  would silently drop it, breaking sign-in instead**. Authorization servers with no
  `end_session_endpoint` fall back to a local logout.
- **The NAA policy could be rewritten by an organisation's administrator.** It is the
  declaration of the side handing namespaces out and covers every organisation under
  the NAAN, so one of them must not be able to restate it for the others. It now
  requires NAAN scope or wider. What an organisation states about itself is its
  commitment level, which its own administrator *can* change — the split follows ARK's
  delegation structure rather than a permissions table.
- The NAAN settings page could be opened by an organisation's administrator, who was
  then refused on save. A form that looks editable but is not is the same defect as a
  hidden button whose URL still works; the condition to open it now matches the
  condition to save it.

## [0.0.2] — 2026-08-28

Everything here was found by putting 0.0.1 on Kubernetes and in the compose stack.
None of it showed up in the test suite, because all four defects live in the gap
between *the code is correct* and *the code can be deployed*.

### Fixed

- `/healthz` is now served in every mode. It only existed on the resolve router, so a
  minter or an admin process answered 404 to its liveness probe and was killed and
  restarted forever.
- A resolver no longer demands authentication settings. It serves no authenticated
  route and mounts no admin interface, yet startup required `ARKHE_SESSION_SECRET`
  and the OIDC configuration — which meant handing a session signing key to every
  resolver node that would never use it.
- A subject pinned to a shoulder now inherits that shoulder's organisation. Passing
  `--shoulder` without `--manager` produced a subject that was rejected at the
  authorization gate every time, in the confusing shape of *the shoulder is right but
  it still will not go through*. A `manager` that contradicts the shoulder is
  refused rather than silently overridden.
- Labels are unique only when there is a label. The `(manager_id, label)` unique
  index covered the empty string, so one organisation could hold only one unlabelled
  subject — which made the ordinary arrangement of one credential per process
  (`web-api`, `web-ui`, `worker`) impossible and pushed towards sharing one key.
  Migration `56e5e54db345`.
- The compose quickstart's browser login failed with
  `invalid_scope: openid profile email`. Declaring `clientScopes` in a realm import
  replaces Keycloak's built-in set rather than adding to it, so `profile` and `email`
  did not exist in the realm at all.

### Changed

- The demo realm no longer puts `arkhe-api` in `defaultDefaultClientScopes`. As a
  realm default, **any** client created there later could obtain a token that claims
  to be for arkhe. An audience is a statement about which API a token is for; it is
  not something to hand out by default.
- The compose stack runs the resolver as its own service on `:8058`, matching how it
  is deployed. Stopping Keycloak now visibly leaves minting at 401 while resolution
  keeps answering 302.

## [0.0.1] — 2026-08-28

First tagged version. Pre-release: **the minor number carries breaking changes while
the version starts with `0`.**

### Added

- ARK minting and resolution, with `?`, `??`, `?info` and `?json` inflections, suffix
  passthrough, check digits, and forwarding of unknown NAANs to a global resolver.
- Delegation in three tiers — `system`, `naan`, `manager` — mirroring how ARK hands
  namespaces down. No principal reaches further than the one that granted it.
- Three authentication mechanisms for the API (`apikey`, `oauth2`, `oidc`), enabled
  individually rather than chosen exclusively, all resolving to one `Principal`.
- Four ways into the admin interface (`bearer`, `password`, `oidc`, `proxy`).
- An operation-shaped admin interface in Japanese and English.
- Succession and departure, both of which leave existing identifiers resolving
  untouched.
- Idempotent minting: a repeated `request_id` returns the ARK already minted.
- A documentation site, bilingual, generated in part from the implementation.

### Notes

- Rewritten from Django onto FastAPI and SQLAlchemy 2.0. The specification layer
  (`arkspec/`, `domain/resolution.py`) moved untouched — 97 tests came across
  unmodified.
- `arkspec/` derives in part from the Internet Archive's arklet (MIT); see NOTICE.

[Unreleased]: https://github.com/RCOSDP/arkhe/compare/v0.0.9...HEAD
[0.0.9]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.9
[0.0.8]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.8
[0.0.7]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.7
[0.0.6]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.6
[0.0.5]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.5
[0.0.4]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.4
[0.0.3]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.3
[0.0.2]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.2
[0.0.1]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.1
