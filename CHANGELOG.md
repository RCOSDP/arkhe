# Changelog

*[日本語](CHANGELOG.ja.md)*

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/) — see
[the policy](https://rcosdp.github.io/arkhe/project/versioning/) for what counts as
breaking in a system whose identifiers cannot be reissued.

## [Unreleased]

### Added

- The word for the entity a namespace is delegated to is now **organisation**
  throughout the interface and the documentation, and a NAAN is an "organisation
  number (NAAN)" — it is a *Name Assigning Authority Number*, and the number belongs
  to the organisation.
- The CLI speaks Japanese and English. The language is decided from the environment
  at startup — `ARKHE_LANG`, then `LC_ALL` / `LC_MESSAGES` / `LANG` in POSIX order,
  defaulting to `ja` as the admin interface does. Typer assembles its help at import
  time, so a runtime `--lang` cannot work.
- The admin interface can now build the ledger, not only mint. **Four buttons on the
  overview — register a NAAN, onboard an organisation, carve out a shoulder, manage
  one — pointed at routes that did not exist and returned 404.** They now work, and
  NAAN and organisation settings pages were added alongside them.
- `arkhe manager list` and `arkhe manager commitment`, and `--commitment` on
  `arkhe onboard`. The commitment level was published by `?` and `??` but **could not
  be set** — every organisation silently carried the default `permanent-dynamic`. That
  meant claiming, in the organisation's name, a commitment it never made; publishing an
  undeclared default as a declaration is worse than publishing nothing. Onboarding
  without `--commitment` now says so on stderr. Unknown levels are refused.
- `set_quota`, so a minting limit can be changed after onboarding rather than only at
  it. An organisation cannot change its own: a limit the receiving side can lift is not
  a limit.
- The overview page is called **Organisations** rather than "Delegation", and its
  explanation is written for someone opening the ledger for the first time. The terms
  are kept in parentheses — "namespace (shoulder)", "Permanent; content may change
  (permanent-dynamic)" — so the plain wording reads on its own while still lining up
  with the specification, the CLI and the API. Commitment levels no longer appear as
  bare machine values. Buttons say what they do: "Add an organisation", not "Onboard an
  organisation"; "Add a namespace", not "Carve out a shoulder". The form for adding an
  organisation now says up front that it hands over a namespace at the same time.
  (Registering a NAAN keeps its own name: there is no plainer word for it than the
  term itself.) "Principals & credentials" is now "Users & keys" — what is listed
  there is not the organisations themselves but their systems and their people — and
  the minting form asks for a *namespace to mint in*, since what is chosen there is a
  NAAN and a shoulder together, not a shoulder alone. A NAAN's name field is now
  "Organisation" rather than "Organisation".
- `compose/oidc/lan.yml`, for viewing the demo from another machine on the LAN.
  Publishing on `0.0.0.0` is not enough on its own: the issuer and redirect_uri have
  to be the URL the browser actually types, so they are parameterised by
  `ARKHE_DEMO_HOST` and the redirect is registered at startup rather than baked into
  the realm JSON. The default binding stays on `127.0.0.1` — this stack carries its
  secrets in the clear.
- A guide for setting up from scratch, covering the steps that happen **outside**
  arkhe as well — requesting a NAAN, and registering your resolver's URL in the NAAN
  registry. Miss the latter and `n2t.net/ark:/99999/…` never reaches you.

### Fixed

- Logging out did not log you out. The session cookie was cleared, but **the
  authorization server's session was left standing**, so opening the interface again
  signed you straight back in without asking. Under OIDC the logout now ends that
  session too (RP-Initiated Logout). No `id_token_hint` is sent: carrying the ID token
  in the cookie would push it past 4 KB where claims are numerous, and **the browser
  would silently drop it, breaking sign-in instead**. Authorization servers with no
  `end_session_endpoint` fall back to a local logout.
- The NAAN settings page could be opened by an organisation's administrator, who was
  then refused on save. A form that looks editable but is not is the same defect as a
  hidden button whose URL still works; the condition to open it now matches the
  condition to save it.
- The NAA policy could be rewritten by an organisation's administrator. It is the
  declaration of the side handing namespaces out and covers **every organisation under
  the NAAN**, so one of them must not be able to restate it for the others. It now
  requires NAAN scope or wider. What an organisation states about itself is its
  commitment level, which its own administrator *can* change — the split follows ARK's
  delegation structure rather than a permissions table.

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

[Unreleased]: https://github.com/RCOSDP/arkhe/compare/v0.0.2...HEAD
[0.0.2]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.2
[0.0.1]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.1
