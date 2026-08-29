# Changelog

*[日本語](CHANGELOG.ja.md)*

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/) — see
[the policy](https://rcosdp.github.io/arkhe/project/versioning/) for what counts as
breaking in a system whose identifiers cannot be reissued.

## [Unreleased]

### Added

- The CLI speaks Japanese and English. The language is decided from the environment
  at startup — `ARKHE_LANG`, then `LC_ALL` / `LC_MESSAGES` / `LANG` in POSIX order,
  defaulting to `ja` as the admin interface does. Typer assembles its help at import
  time, so a runtime `--lang` cannot work.
- The admin interface can now build the ledger, not only mint. **Four buttons on the
  overview — register a NAAN, onboard an institution, carve out a shoulder, manage
  one — pointed at routes that did not exist and returned 404.** They now work, and
  NAAN and institution settings pages were added alongside them.
- `arkhe manager list` and `arkhe manager commitment`, and `--commitment` on
  `arkhe onboard`. The commitment level was published by `?` and `??` but **could not
  be set** — every institution silently carried the default `permanent-dynamic`. That
  meant claiming, in the institution's name, a commitment it never made; publishing an
  undeclared default as a declaration is worse than publishing nothing. Onboarding
  without `--commitment` now says so on stderr. Unknown levels are refused.
- `set_quota`, so a minting limit can be changed after onboarding rather than only at
  it. An institution cannot change its own: a limit the receiving side can lift is not
  a limit.
- A guide for setting up from scratch, covering the steps that happen **outside**
  arkhe as well — requesting a NAAN, and registering your resolver's URL in the NAAN
  registry. Miss the latter and `n2t.net/ark:/99999/…` never reaches you.

### Fixed

- The NAA policy could be rewritten by an institution's administrator. It is the
  declaration of the side handing namespaces out and covers **every institution under
  the NAAN**, so one of them must not be able to restate it for the others. It now
  requires NAAN scope or wider. What an institution states about itself is its
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
- A subject pinned to a shoulder now inherits that shoulder's institution. Passing
  `--shoulder` without `--manager` produced a subject that was rejected at the
  authorization gate every time, in the confusing shape of *the shoulder is right but
  it still will not go through*. A `manager` that contradicts the shoulder is
  refused rather than silently overridden.
- Labels are unique only when there is a label. The `(manager_id, label)` unique
  index covered the empty string, so one institution could hold only one unlabelled
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
