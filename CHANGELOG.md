# Changelog

*[日本語](CHANGELOG.ja.md)*

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/) — see
[the policy](https://rcosdp.github.io/arkhe/project/versioning/) for what counts as
breaking in a system whose identifiers cannot be reissued.

## [Unreleased]

### Fixed

- The entry route claimed "the authorization server" outright. **arkhe never queries
  it**, so it cannot know whether the subject exists there — the demo ledger had two
  subjects registered in arkhe with no Keycloak client, and they looked ready. It now
  says the decision is *delegated* to it, and points at where to check.
- **A correctly configured user looked unconfigured** where authentication is
  delegated: the list said "0 credentials active", which is exactly what a machine
  holding no key looks like under `oidc`. The column now says **how it gets in** — a
  key, the authorization server, an external login, or nothing yet. **A key whose
  mechanism is disabled does not count**: it cannot authenticate, so saying it is there
  would be a lie. A subject that genuinely cannot get in is told what to do about it.

### Added

- The minting form's **type can be picked from a list** (DataCite's
  `resourceTypeGeneral`). **It is not a constraint** — ERC's `what` defines no
  vocabulary, so anything not in the list can still be typed (a `datalist`, so no JS).
- Where only one kind of key can be issued, the page now says **why, and what to add**.
  The compose demo runs `ARKHE_AUTH=apikey,oauth2,oidc`, so both an API key and a
  client_secret can be issued and compared.

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

[Unreleased]: https://github.com/RCOSDP/arkhe/compare/v0.0.4...HEAD
[0.0.4]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.4
[0.0.3]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.3
[0.0.2]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.2
[0.0.1]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.1
