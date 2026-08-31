# Changelog

*[日本語](CHANGELOG.ja.md)*

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/) — see
[the policy](https://rcosdp.github.io/arkhe/project/versioning/) for what counts as
breaking in a system whose identifiers cannot be reissued.

## [Unreleased]

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

[Unreleased]: https://github.com/RCOSDP/arkhe/compare/v0.0.8...HEAD
[0.0.8]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.8
[0.0.7]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.7
[0.0.6]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.6
[0.0.5]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.5
[0.0.4]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.4
[0.0.3]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.3
[0.0.2]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.2
[0.0.1]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.1
