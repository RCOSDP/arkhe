# Changelog

*[日本語](CHANGELOG.ja.md)*

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/) — see
[the policy](https://rcosdp.github.io/arkhe/project/versioning/) for what counts as
breaking in a system whose identifiers cannot be reissued.

## [Unreleased]

### Added

- **A tool that builds the ledger for the end-to-end suite** (`scripts/seed_e2e.py`). It
  creates the NAANs, organisations, principals with their keys and the admin password, and
  `--arks N` fills the ledger with **ARKs in mixed states** (published, reserved, held,
  tombstoned, qualified, withdrawn).

  **`tests/e2e/` calls it.** Writing the same setup inside the suite would leave one of the
  two stale — and **because the suite calls it, the tool cannot rot either**. Checking by
  hand starts from the same ledger; the keys are printed as they are issued.

  **The setup goes through the CLI** — a path operators do not use is not a check of
  anything. **It can also top up a half-built ledger**, because a suite that fails stops
  halfway and "the NAAN exists but no organisation does" is an ordinary state.

- **The end-to-end suite went from 13 checks to 54** (`tests/e2e/`). Same shape as before
  (PostgreSQL in docker, a minter and a resolver under `uvicorn`), **a much wider surface**:

  | | what it watches |
  | --- | --- |
  | `test_shape` | the split of roles, `/healthz` and `/readyz`, `.well-known/ark`, the CLI and the API agreeing on the count |
  | `test_resolution` | inherited qualifiers, label case, hyphens, `?info` and `??`, **a delegated NAAN going to its delegate and an unknown one to the global resolver**, the CSP on the public page |
  | `test_lifecycle` | reserved → published → withdrawn → republished → deleted, update, bulk, an explicitly registered qualifier, hold, tombstone |
  | `test_authz` | outside the scope, **no reach into another organisation**, a stopped principal, the daily quota, `client_credentials` |
  | `test_admin_ui` | **signing in with a password and withdrawing, then republishing, from the form**; refusals that do not differ on whether the user exists |
  | `test_hardening` | **`ARKHE_ALLOWED_HOSTS`**, a closed resolver (which resolves the unpublished) |
  | `test_concurrency` | 32 simultaneous sends of one `request_id`, 32 simultaneous mints, simultaneous withdrawals |

  **It was verified to bite.** Remove the `ARKHE_ALLOWED_HOSTS` middleware from
  `create_app` and `test_許していない_Host_は断る` fails — **that setting was dead until
  0.9.2** (declared, documented, read by nothing). The rest of the suite assembles the app
  by hand, so **a missing middleware is invisible to it.**

- **What did not reproduce is written down too.** Firing 32 resends of one `request_id`
  from pre-opened sockets (1.3 ms of spread) does **not** open the `_commit_or_replay`
  race — **the first commits before any other reaches `_replay`**, with four workers as
  well. Reverting the fix does not fail the check, and the check says so, so that **nobody
  reads it as the guard for that race**. A check that cannot fail is not counted as cover.

### Fixed

- **Three remaining `count(*)` calls are gone** (the minting quota, the check for part
  references, the admin overview). **The counted column is named** — `count(*)` counts
  rows, so an index alone cannot answer it, and it costs more as the ledger grows. When
  `domain.stats` was fixed this way in 0.6.0, **these three were left behind.**

  **A check now watches for it** (`test_数える列は必ず名指しする`). Fixing the three that
  exist today is not enough; the next person writes `func.count()` again.

## [0.11.0] — 2026-09-19

**The release that measured first, then ran what it had written down.**

The knobs shipped in the previous release were rebuilt on the recommended values and
re-measured. **Workers double up to 4, then give about 10%.** **A pool 30× larger changes
nothing.** Exactly **one** knob made a difference, and it was invisible in rps —
**counting the round trips is what made it decisive**.

Along the way: **a restore procedure written that same day did not start**, and
**`/readyz` probed a database the resolver does not read**. Both pass every check that
exists. **This is the release that found what only running things finds** — and then **made the
running into a check**: an end-to-end suite that builds the production shape and drives
it over HTTP.

### Added

- **An end-to-end check** (`tests/e2e/`, `uv run pytest -m e2e`). It **builds the
  production shape and drives it over plain HTTP**: PostgreSQL in docker, **a minter and
  a resolver started separately under `uvicorn`**, the ledger built **through the CLI**,
  and minting and resolution done with the key that CLI printed.

  The rest of the suite calls the app directly with `TestClient`, on SQLite, with
  authentication substituted — faster, and a finer net for authorisation. **What this
  catches is what passes through that net**: that the app is a factory (`arkhe.app:app`
  does not start), that the minter has no resolution route and **the resolver has no
  minting route**, and that **the resolver never touches the write database**.

  **The resolver's write URL points nowhere.** Touch it and the check fails — reverting
  this release's `/readyz` fix does exactly that, which was verified.

  It is step 5 of `check.sh`, and **prints SKIP when docker is missing** rather than
  passing quietly.

- **Figures re-measured on the recommended settings**, in
  [Deployment](https://rcosdp.github.io/arkhe/guides/deployment/). A ledger of one million
  ARKs, four resolver workers, `POOL_SIZE 3` and `MAX_OVERFLOW 2`: **resolution reaches 938
  rps at concurrency 8, p50 6.5 ms**.

  Three things came out of it. **Throughput flattens at concurrency 8** and beyond that only
  latency grows. **Only 16 connections are ever open** (20 available, 179 still free of
  `max_connections=200`) — **the recommended pool is not too tight**. And minting's 59.7 ms
  is **almost entirely Argon2**, which is why **bulk is 55 times faster**: one
  authentication divided across a thousand rows, not a faster database.

- **How it scales out, and what jams first**, measured and written up in
  [Deployment](https://rcosdp.github.io/arkhe/guides/deployment/).

  **Workers double up to four** (352 → 718 → 1,413 rps) and buy about ten per cent after
  that. **A thirtyfold sweep of the pool moves the rps not at all** — it moves only how
  many connections are held, because resolution is one short query with nothing to hoard.
  What jams next is **PostgreSQL's CPU** (roughly 1.4 : 1 against the app).

  **A section on proving you are measuring the server comes first.** `bench.py` tops out
  near 2,200 rps per process (the GIL), so **anything above that describes the client** —
  four processes in parallel reach 9,017 rps.

  It also records that **repeating the same configuration varies by ±20%**, and that **a
  difference smaller than that band is not a difference.**

- **`ARKHE_DB_PRE_PING` — the liveness check on a pooled connection can now be turned
  off** (it stays on by default).

  **Turning it off roughly halves the database round trips per resolution**: measured
  **1.60 → 0.82** (counting `xact_commit + xact_rollback` against a million-ARK ledger).
  A resolution reads **one index**, so **the extra verification round trip is heavy in
  relative terms**.

  **The rps never showed it** — it drowned in the noise. **Counting made it decisive.**

- **A sweep of the database and application knobs, and what did nothing**, in
  [Deployment](https://rcosdp.github.io/arkhe/guides/deployment/). `uvloop` /
  `httptools`, `shared_buffers` at 128MB / 512MB / 2GB, a thirtyfold pool sweep,
  `synchronous_commit=off` for minting — **none of them moved the number**.

  **The default 128MB of `shared_buffers` already gives 99.95% cache hits.** A resolution
  touches one index and one row, so **the general "25% of RAM" buys nothing here**. Same
  for `synchronous_commit`: **53 of the 60 ms a mint takes is Argon2** — **if giving up
  durability buys nothing, there is no reason to give it up.**

- **What a replica actually does**, measured and written up in
  [Deployment](https://rcosdp.github.io/arkhe/guides/deployment/).

  **The rps does not go up** (1,433 → 1,307 — on one host a replica adds no CPU). **What
  grows is the primary's headroom**: the read load leaves it entirely (136% → 0% CPU). A
  replica buys not speed but **minting not being dragged down when reads get rough**.
  **Resolution also survives the primary being stopped** (`302`, `?info` still `200`).

  **Replication lag from minting to being resolvable was 3–5 ms median** (`replay_lag`
  1.3 ms even under write load), and **all 50 attempts resolved on the very first
  request** — the `404` warned about in the monitoring section **never once happened under
  these conditions**. The warning stays, with the conditions that would produce it spelled
  out (another machine, a replica busy with reads, a large ingest).

- **Three procedural notes for following a procedure** (`.claude/skills/`):
  `release` (the six steps of cutting a version), `measure` (how to measure), `chaos`
  (breaking it on purpose).

  **What they record is mistakes.** Appending a version section to an already-released
  one, measuring the client instead of the server, re-`apply`ing an expired chaos object
  and reading "no effect" — each happened. **`AGENTS.md` is the source of truth**; these
  are notes for carrying it out.

### Changed

- **The step for whoever embeds arkhe was removed from `AGENTS.md`.** Advancing a
  submodule pointer is **the embedder's procedure**, and **this document is arkhe's
  guide**. Written in two places, one of them goes stale.

### Fixed

- **The start-up command in the restore procedure did not work.** It said
  `uvicorn arkhe.app:app`, but **the app is a factory** (`arkhe.app:create_app --factory`)
  and will not start that way — **found by actually running the procedure written moments
  earlier**. Everywhere else (Quickstart, the federation guide, the Dockerfile, compose)
  was right.

- **`scripts/bench.py` sent fewer requests than `-n`.** Integer division by the concurrency
  meant `-n 3000 -c 16` sent 2992. **Compared against `-n`, the status breakdown looks like
  eight failures** — which is exactly how it was misread. The remainder is now distributed,
  so what it counts matches what it said it would send.

- **`/readyz` probed a database the role does not read.** A resolver reads from
  `ARKHE_READ_DATABASE_URL` (the replica), yet the probe went to the **primary** — so
  **with the replica down and resolution returning `500`, it kept answering Ready** as
  long as the primary was alive, and a load balancer kept sending traffic.

  Found by actually stopping the replica. **It now probes the side the role reads** (the
  read connection for a resolver, the write one for a minter).

## [0.10.0] — 2026-09-18

**The release that noticed the recommended shape does not run on defaults.**

  2 resolvers × 4 workers × 15 connections = 120
  PostgreSQL default max_connections = 100 (97 after the superuser reserve)

Connections per process **multiply by the worker count**. The guide recommended that shape
without saying it jams there — **and offered no way to tune the pool**, leaving operators
to cut workers instead.

The knobs are there now, and the recommended values are **only what the measurements call
for**. No recommended value without a source.

### Added

- **Knobs for the connection pool** (`ARKHE_DB_POOL_SIZE`, `ARKHE_DB_MAX_OVERFLOW`,
  `ARKHE_DB_POOL_RECYCLE`). **On defaults, the shape this guide recommends does not run**:

  ```
  2 resolvers × 4 workers × 15 connections = 120
  PostgreSQL default max_connections = 100 (97 after the superuser reserve)
  ```

  SQLAlchemy's default of `pool_size 5 + max_overflow 10 = 15` per process **multiplies by
  the worker count**. **Resolution is one short query** (a primary-key index lookup,
  0.03 ms), so there is nothing to hoard — **two or three per worker is usually enough.**

  The defaults are unchanged, so behaviour is as before. Where something upstream drops
  idle connections, set `ARKHE_DB_POOL_RECYCLE` below that timeout: `pool_pre_ping` catches
  it, **but spends a round trip every time it does.**

- **Recommended middleware settings** in
  [Deployment](https://rcosdp.github.io/arkhe/guides/deployment/): the arithmetic for
  connection counts, PostgreSQL (`shared_buffers` sized **to hold the indexes**, `work_mem`
  left alone — resolution is one index lookup and almost nothing sorts or joins), worker
  counts, and **a 1 MB request limit upstream** (`BULK_LIMIT` is 1000 rows, and nginx's
  default `client_max_body_size 1m` is the edge).

  **Only what the measurements call for.** No recommended value without a source.

## [0.9.2] — 2026-09-18

**Two things that looked guarded and were not.** Both came out of a security-focused sweep,
and **neither was exploitable** — but both were the kind of thing an operator would count
as handled.

`ARKHE_ALLOWED_HOSTS` **was used by nothing**. The setting existed and was documented, but
no check on the `Host` header was ever installed — **a security setting that does nothing
is worse than no setting**, because without it you would have done something else.

The target-URL check lived **only in the API schema**, and the admin form went straight
past it. Redirects and links are guarded by an allow-list so no harm followed, but **a
guard at the point of use and a guard at the point of entry are different things.**

### Fixed

- **`ARKHE_ALLOWED_HOSTS` was never used by anything.** The setting was declared and
  documented, but **nothing checked the `Host` header** — an operator who narrowed it was
  counting it as handled while it was not. **A security setting that does nothing is worse
  than no setting.**

  It now rejects mismatched hosts when narrowed (the default `*` installs nothing — where
  a proxy terminates, it usually checks this already, and **rejecting twice makes failures
  harder to attribute**).

- **The admin form bypassed the target-URL check.** The validator that refuses
  `javascript:` and `data:` lives in the API schema, and **the screen took a raw string
  and minted with it** — "no difference between the screen and the API" was broken by
  where the validation sat.

  **It was not exploitable.** Redirects and links are guarded by an **allow-list** (`http`
  and `https` only), so such a value is neither followed nor linkified. **But that is a
  guard at the point of use; the point of entry needs its own** — the day the allow-list
  is loosened, whatever is already in the ledger starts to matter. The refusal now lives
  in the ORM (the same shape as the guard on deletion), and the screen gives a readable
  refusal too.

## [0.9.1] — 2026-09-18

**A release that brings the documentation back level with the implementation.** Three
findings from a mechanical sweep of the whole repository, **all of them changes made
today that had not reached the prose.**

The heaviest: **the invariants page was two releases behind** — the page that states what
this system promises was **out of date about its central promise**.

Twice today it turned out that putting something in the runbook was not enough, so the
version and the migration head named in STATUS.md are now checked by a test.

### Fixed

- **The invariants page was two releases behind.** Its section "a published ARK is never
  deleted" **knew about neither `purge` (0.3.0) nor withdrawing from publication
  (0.4.0)** — meaning **the page that states what this system promises** was out of date
  about its central promise.

  It now says there are two ways out (withdrawing comes back; deleting and purging do
  not), that the ORM guard keys on **whether the name was ever published** rather than on
  whether it is published now, and that **`NR` holds either way**: a name that went out
  and was removed answers `404` forever and never comes to mean something else. The same
  wording survived in the Quickstart, the federation guide, the data model and the CLI
  reference, and was corrected there too.

- **[The versioning policy](https://rcosdp.github.io/arkhe/project/versioning/) did not
  know what had happened to it.** It listed "a published ARK becomes deletable" as an
  example of a major change — **and 0.4.0 did exactly that**. The line is redrawn: what
  counts as weakening is not removal itself but removal **without a reason, without the
  ARK retyped, or from outside the caller's reach**.

- **STATUS.md named a migration head one behind.** `alembic check` compares the schema
  with the models but **never reads the documentation**. A test now checks that the
  version and the head named there match reality — the second time today that putting
  something in the runbook turned out not to be enough.

## [0.9.0] — 2026-09-18

**The release in which reservations nobody came back to can be found.** Reserved ARKs
accumulate if left alone — numbers pointing at nothing, unnoticed by anyone.

**A count cannot raise an alarm.** Ten reserved yesterday is normal; one reserved three
years ago is abandoned. So the signal is **age**.

**Nothing is deleted on a timer.** A reserved name is usually already in someone's hands,
and expiring it would **quietly make a name they still meant to use unmintable forever** —
**an irreversible operation should not be fired by a clock.**

With this, every open item STATUS.md listed on arkhe's side is closed. **What remains is
operational work.**

### Added

- **Abandoned reservations can now be found.**

  `arkhe stat` reports **the oldest ARK still reserved** (date and age), and
  `arkhe ark list` takes `--older-than N`, which together with `--state reserved` pulls
  out **reservations nobody ever published**.

  **A count cannot raise an alarm.** Ten reserved yesterday is normal; one reserved three
  years ago is abandoned — **piling up shows in the age, not the number.**

  **Nothing is deleted on a timer.** A reserved name is usually **already in someone's
  hands** — stamping it on a draft is what reserving is *for* — and expiring it would
  **quietly make a name they still meant to use unmintable forever**. **An irreversible
  operation should not be fired by a clock**: whether to drop it belongs to the
  organisation holding the reservation.

  `--older-than` is orthogonal to `--state`: there will be a day for finding **published**
  ARKs minted three years ago and never touched since.

### Fixed

- **`arkhe stat` crashed on SQLite.** SQLite has no timezone type, so a column declared
  `DateTime(timezone=True)` **comes back naive** there while PostgreSQL returns it aware.
  **The type depended on the engine**, and the subtraction raised `TypeError` on one of
  them.

  The domain now attaches UTC before returning — **fixing only the CLI would leave the
  same hole in the API and the admin page**. Attaching it is not a guess: the ledger only
  ever writes `utcnow()`.

## [0.8.0] — 2026-09-18

**The release that lets you notice a delegate has gone down.** Delegating a namespace hands
the life of the identifiers beneath it to someone else — **and arkhe does not know how they
are doing**: it answers with a redirect and never fetches the target.

**The list to watch was missing the worst failure.** `/.well-known/ark` published delegated
*minting* but not delegated *resolution*. When a `minter` dies, minting stops; when a
`redirect` dies, **every ARK beneath it stops resolving**.

**arkhe is still not made to probe.** Making no outbound calls is what keeps failures easy
to attribute, and that is too expensive to trade away for monitoring — **noticing lives
outside, stopping lives inside.**

### Added

- **`/.well-known/ark` now carries where resolution was delegated (`redirect`) and each
  shoulder's `status`.**

  It used to list only `minter` (delegated minting) and `about`. **The failure that hurts
  most was the one missing**: when a `minter` dies, minting for that namespace stops; when
  a `redirect` dies, **every ARK beneath it stops resolving**. The first thing to watch
  from outside cannot be watched if it is not published.

  **The list no longer filters on `status=delegated` alone.** A `redirect` can be set
  independently of `status`, so **a shoulder that mints locally but delegates resolution
  was dropping out of the list** — and nobody would notice when it failed.

- **How to watch a delegate from outside**, in
  [Deployment](https://rcosdp.github.io/arkhe/guides/deployment/).

  **arkhe is not made to do the probing.** This ledger makes **no outbound calls at all**
  (even an unknown NAAN just gets a `302`; nothing is fetched) — a property that makes
  failures easy to attribute, and **too expensive to trade away for monitoring**. It
  publishes the list instead.

  **Noticing lives outside; stopping** — a hold — **lives inside.**

## [0.7.0] — 2026-09-18

**The release that says what to watch in order to claim the promise is being kept.** The
promise is a single one — a name you handed out never points at something else and never
stops resolving — so the monitoring is derived backwards from it.

**One discarded signal was picked up.** Minting has always counted its collisions, and
every caller threw the count away. It is **the only sign that the namespace is quietly
filling up**, so it is now recorded when it happens.

**Replication lag is written up as a correctness problem, not a performance one.** If an
ARK answers `404` right after it was handed out, "wait a moment" is not an answer.

### Added

- **Minting collisions are now recorded** (`mint_collision`).

  `mint()` has always counted collisions and returned the count, and its docstring said
  the point was **to catch a namespace quietly filling up**. But **all three call sites
  threw it away** with `ark, _ =` — counted, and nobody receiving it.

  One collision does no harm (it retries and succeeds), but **a rising rate is the signal
  to add digits**, and nobody notices that unless someone is looking. **Nothing is logged
  when there are no collisions** — a line per mint and people stop reading the log.

- **A monitoring design** in
  [Deployment](https://rcosdp.github.io/arkhe/guides/deployment/). What to watch follows
  from what was promised, so the table is derived backwards from **the signs that the
  promise is starting to break**.

  **Replication lag is written up as a correctness problem, not a performance one.** With
  minting on the primary and resolution from a replica, **an ARK resolved right after it
  was handed out can answer `404`** — in most systems that is "wait a moment", but **here
  the person concludes the identifier does not exist**.

  **No metrics endpoint.** You already have somewhere logs go, and one pipeline is better
  than two.

## [0.6.0] — 2026-09-18

**The release in which you can prove it comes back.** After restoring from a backup, the
ledger can be checked **by its contents, not its row count** — the counts can agree while
every target has moved, and then every identifier is broken.

The check used to be SQL pasted into a runbook. **A mis-paste still reads as "they
match"**, so it is a command now.

Alongside it, **a restore and a point-in-time recovery were actually carried out**, and the
procedure, the daily and monthly backups, and how to notice that backups have stopped are
written down in [Deployment](https://rcosdp.github.io/arkhe/guides/deployment/). The
recommended architecture and the redundancy decisions are there too — **each one exercised
before it was written.**

### Added

- **`arkhe fingerprint` — prove a restore by its contents, not its row count.** Run it on
  the restored ledger and compare against the value from before: the counts can agree
  while every target has moved, and then every identifier is broken.

  ```
  arks       c5e54e5af778420832800a7dc9104eee  53 rows
  withdrawn  e3b0c44298fc1c149afbf4c8996fb924  0 rows
  ```

  **Two lines, because blending them hides where the difference is.** Losing `withdrawn`
  (the names never to be assigned again) **does not stop minting**: with a single number
  you would never see it, and half of what makes `NR` hold would be gone while everything
  appeared to work.

  **Holds are excluded on purpose.** They change on their own as deadlines pass, so a
  difference would not mean "broken" — **an alarm that is always ringing stops being
  read.** Titles and descriptions are excluded too: losing them hurts, but **not in the
  way an identifier pointing elsewhere hurts**, and mixing them flattens a grave
  difference and a mild one into the same value.

  [Deployment](https://rcosdp.github.io/arkhe/guides/deployment/) used to carry the
  `md5(string_agg(...))` SQL inline. **A mis-pasted check still reads as "they match"**,
  so it is a command now — and one that does not depend on the database's dialect.

## [0.5.1] — 2026-09-18

**One fix, found while working through redundancy.** The same `request_id` arriving **at
the same time** returned `500` — which is what a load balancer's retry, or a caller that
gave up waiting and resent, actually looks like when it lands on another minter.

**The ledger was never wrong** (the uniqueness constraint on the receipt held). What was
wrong was the answer: to the caller it reads as "**I do not know whether it minted**", and
resending under a fresh `request_id` then puts two ARKs on one object.

**The promise that a resend gets the same answer has to hold whether the resends are
sequential or simultaneous.**

### Fixed

- **The same `request_id` arriving at the same time returned `500`.** Between checking
  for a replay and writing the receipt there is a gap, and **a load balancer's retry — or
  a caller that gave up waiting and resent — lands on another minter at the same moment**:
  both see nothing, both write. The guard itself lives in the database
  (`one_ark_per_request_id`), so **the ledger was never wrong**, but the loser got a `500`
  (102 of 200 requests, measured).

  To the caller that reads as "**I do not know whether it minted**", which is the worst
  possible answer: **resending under a fresh `request_id` then double-mints**. The loser
  now returns the ARK the winner recorded — **the promise that a resend gets the same
  answer has to hold whether the resends are sequential or simultaneous.**

  Bulk minting (`/api/mint/bulk`) had the same gap and now **rebuilds the batch once**: the
  winner's receipts are visible by then, so every row comes back as a replay and nothing is
  minted twice. A bulk request creates nothing unless every row succeeds, so **there is no
  reason for it to fail on a race.**

## [0.5.0] — 2026-09-18

**The release in which the ledger can be counted.** How many there are, where they are
concentrated, how much has been minted lately — the figures an operational conversation
needs first are now available **in the same shape from the CLI, the API and the admin
interface**.

**Counting happens in exactly one place.** If the three entrances each wrote their own
aggregate, **the same "count" would differ depending on where you looked** — the worst
kind of drift.

**Totals are limited by reach too**: an organisation sees its own shoulders, a NAAN
administrator its NAAN, because **a total is itself a disclosure**. And **what was removed
after publication is counted apart from the total** — that is the number of times the
promise was broken, and it does not belong buried inside a sum.

### Added

- **A way to see the ledger's numbers** (`arkhe stat`, `GET /api/stats` with `ark:read`,
  and a Statistics page at `/admin/stats`):
  ARKs (public and reserved), withdrawn names, shoulders by status, organisations,
  clients, holds in force, minting over the last 24h / 7 days / 30 days, the first and
  last mint, and **a breakdown per shoulder**. The CLI takes `--json` for machines.

  **Counting happens in one place** (`domain/stats.py`). If the screen, the CLI and the
  API each wrote their own aggregate, **the same "count" would differ depending on where
  you looked** — the worst kind of drift. It is the same reason the filters live in
  `queries.py`, and a test holds the three entrances to the same numbers.

  **The admin page is not a dashboard.** This interface is a ledger, and what it owes the
  reader is not a big number — it carries no charts, and the space goes to **keeping what
  was removed after publication apart from the total**.

  **Totals are limited by reach too.** An organisation sees its own shoulders, a NAAN
  administrator its NAAN, the registration authority everything — **a total is itself a
  disclosure**, since how many identifiers an organisation holds is that organisation's
  business. `--naan` and `--org` only layer on the same filters the listing uses; they
  **never widen the range**.

  **Withdrawn names are counted with those removed after publication kept separate.**
  Retracting a reservation nobody saw and removing a name that was out in the world are
  different acts, and **the second is the number of times the promise was broken.** That
  does not belong buried inside a total.

  **The cost is stated honestly.** It costs time proportional to the number of rows —
  unlike the listing, which avoids counting by fetching one extra row, because there only
  the existence of more matters while here the number *is* the answer. **What can be
  avoided is the number of passes**: the published split, the first and last mint, the
  three windows and the holds are all aggregates over the same set, so conditional
  aggregation gathers them **in a single pass** (seven reads of `ark` written naively,
  two as written). That is not only for speed — **counts taken separately drift apart as
  rows arrive**, and a 24-hour figure that exceeds the 7-day one destroys trust in the
  whole page. Measured at about 110 ms over 300,000 ARKs: **not an endpoint to poll.**

## [0.4.0] — 2026-09-18

**The release in which publication can be withdrawn, and taken up again.** In 0.3.0
`published_at` went one way only and "there is no way to unpublish" was written down as a
decision. It is reversed because **the judgement about whether something should be out
belongs with whoever holds the object**: the people who notice that something should never
have been published are the depositors, not the registration authority, and making them go
up and back means **it stays out in the meantime**. **A stop that is too far away does not
stop anything.**

**Everyone acts inside their own reach** — an organisation within its own shoulder, a NAAN
administrator within its NAAN, the registration authority everywhere. That is not
loosened; loosening it would just be hijacking.

**What changed instead is where the weight sits**: the ceremony now follows the name's
history, not the actor's rank. Deleting a reservation nobody ever saw stays light, while
**anything that has ever been out in the world needs a reason and the ARK retyped**. The
dangerous question is not *who deletes* but *what disappears*.

**`NR` is not broken.** A withdrawn name belongs to nobody and nothing reassigns it. A
stale reference gets `404` — what breaks is "keeps resolving", not "never means something
else".

### Added

- **Publication can now be withdrawn.** In 0.3.0 `published_at` went one way only, and
  "there is no way to unpublish" was written down as a decision. It is reversed because
  **the judgement about whether something should be out belongs with whoever holds the
  object** — the people who notice that something should never have been published are
  the depositors, not the registration authority, and making them go up and back means
  **it stays out in the meantime**.

  - `POST /api/unpublish` (`ark:unpublish`) — the row stays, the ARK stops resolving
  - `POST /api/publish` — the same endpoint **puts it back**
  - `arkhe ark unpublish`, and the same actions on the admin ARK page

  **Each caller acts inside their own reach**: an organisation within its own shoulder, a
  NAAN administrator within its NAAN, the registration authority everywhere — the same
  three-tier check (`authz.assert_may_touch`) that update and tombstone already use.

- **A new `ark:unpublish` scope.** Being able to publish and being able to take back are
  different decisions. It is separate from `ark:delete` too: **withdrawing comes back,
  deleting does not**, and one key for both hands the irreversible half to anyone who
  only wanted the reversible one.

### Changed

- **The weight of the ceremony now follows the name's history, not the actor's rank.** A
  new column `ark.first_published_at` records when it first went out and is **one-way**:
  withdrawing does not unmake having been out in the world.

  Deleting a reservation nobody ever saw stays as light as before. **Withdrawing or
  deleting anything that has ever been published requires a `reason` and `confirm`
  repeating the ARK** (`ARKHE-1017` / `ARKHE-1018`). **The dangerous question is not who
  deletes but what disappears**: the registration authority dropping a reservation nobody
  saw is light, an organisation taking back a name cited for three years is heavy, and
  ranking the actors gets those two backwards.

- **`/api/purge` is no longer restricted to `authority=system`** — reach and scope bind
  it, as they bind everything else. Once publication can be withdrawn, **`unpublish` then
  `delete` reaches the same result in two steps**; restricting only the one-step form by
  rank guards nothing. The reason, the retyped ARK, the audit trail and never freeing the
  name are all unchanged.

- **`/api/delete` refuses a published ARK differently** (`ARKHE-1501`): instead of "a
  published ARK is never deleted", it now says **unpublish it first**, or purge it in one
  step.

- **Every existing ARK migrates as having been published** (`published_at` is copied into
  `first_published_at`). Publication could not be undone before, so that is what they are
  — **without this, every existing published ARK would count as never having gone out and
  could be deleted with no reason and no confirmation.**

BREAKING CHANGE: `ark` gains `first_published_at`. The `ark:unpublish` scope is new, and
`ARKHE-1310` (purging is for the registration authority alone) is gone.

## [0.3.0] — 2026-09-17

**The release in which a minted name can still be deleted, until it is published.**
There was no delete anywhere before — this is a system that declares `NR` (never
reassign). But **`NR` binds the names you have handed out**, not a name at the instant
it is minted. Numbering a draft object ahead of time is ordinary practice, and when that
registration is called off, **leaving a number nothing points at in the ledger forever**
is not what keeping the promise looks like.

The boundary is a single `Ark.published_at`, and it is **one-way**: once published, it
cannot be deleted — except through `POST /api/purge`, which the registration authority's
operator may use and which always leaves a trace. **The default is still "publish on
mint"**, so existing callers need no change, and every existing ARK migrates as
published.

**Also fixed: `alembic upgrade head` did not run on SQLite.** The exact steps in the
Quickstart had been stopping partway for three releases — because **we had only ever
round-tripped on PostgreSQL**.

### Added

- **An ARK can be deleted before it is published.** There used to be no delete anywhere:
  declaring `NR` (no re-assignment) means resolution must never stop. But **what `NR`
  binds are the names that went out into the world**, not every name the moment it is
  minted. Reserving a number for an object that is still a draft is ordinary practice,
  and when such a deposit is abandoned, **a number that points at nothing forever** is
  not keeping the promise either.

  So `Ark.published_at` was added. `null` means "not published yet": the ARK **does not
  resolve** — the resolver answers as it does for a name it has never seen — and it
  **can be deleted**.

  - `POST /api/mint` with `{"reserve": true}` — mint it without publishing
  - `POST /api/publish` — publish it globally. **From here on it cannot be deleted**
  - `POST /api/delete` — withdraw one that was never published (a published one is `409`)
  - `arkhe ark publish` / `arkhe ark delete`, and the same two actions on the ARK page of
    the admin interface
  - `ARKHE_RESOLVE_UNPUBLISHED` — a resolver inside a closed network resolves them

  **The boundary only goes one way.** Publishing cannot be undone; if it could, deleting
  before publication would mean nothing. **The default still mints and publishes in one
  step**, so existing callers need no change, and every existing ARK migrates as
  published.

  **Whether it resolves is not decided by the ARK's state alone** — it depends on which
  resolver is answering. A resolver started with `ARKHE_RESOLVE_UNPUBLISHED=1`, inside a
  closed network, **does resolve reserved ARKs**: a name minted in that network is
  worthless if the network's own resolver will not resolve it, which would defeat the
  point of giving closed objects the same shape of PID. **The default does not**, because
  `?info` and `??` need no authentication and the safe side belongs in the default.

  **A withdrawn name is not freed.** It moves to `withdrawn_name` and is never assigned
  again, by minting or by import: a reserved identifier has usually already been handed
  to someone — that is what reserving is *for* — and re-using it would be
  indistinguishable, from outside, from breaking `NR`. Deletion also has its own scope,
  `ark:delete`; being able to mint and being able to withdraw are different decisions.

- **One narrow way out for a published ARK** (`POST /api/purge`, `arkhe ark purge`,
  `ark:purge`).
  Everything here exists so that a published identifier keeps resolving, and **a
  published ARK not being deletable** is the centre of that. The door is nonetheless
  open because **reality sometimes brings a demand that outweighs an identifier** — a
  removal order, personal data that should never have been published, a mass ingest
  that went in wrong. **Without a way out, someone ends up deleting rows straight from
  the database, and a deletion that leaves no trace is the worst kind.**

  So it is not made impossible; it is made narrow and recorded:

  - **the registration authority's operator only** (`ark:purge` **and**
    `authority=system`) — never a NAAN administrator, never an organisation;
  - **a reason is required** — a purge that leaves nothing behind is the same as one
    that never happened;
  - **`confirm` must repeat the ARK**, so a script walking a list cannot empty the
    ledger by accident;
  - **the name is not freed** — it moves to `withdrawn_name` and is never assigned
    again;
  - **the whole thing is audited.**

  The last two are what survive. **The target and the description go, but the name can
  never come to mean something else**: a stale reference gets `404`, never a different
  object. `NR` holds; what breaks is "keeps resolving".

  The ORM enforces it too. **A published row cannot be deleted unless the session has
  named that one ARK as the one being purged** (`models.sanctioned_purge`). A global
  flag would get left raised, and **you would find out only after a row that must not
  disappear had disappeared.**

### Changed

- **An invariant is stated more narrowly.** "An ARK is never deleted" is now "a
  **published** ARK is never deleted". Nothing that was protected has been given up — a
  name that went out still cannot go — but the promise has been rewritten to say exactly
  what it covers, and [the versioning
  policy](https://rcosdp.github.io/arkhe/project/versioning/) was updated to match.

### Fixed

- **`alembic upgrade head` did not run on SQLite.** The steps written in the Quickstart
  (`ARKHE_DATABASE_URL=sqlite:///…`, then `alembic upgrade head`) stopped at the third
  migration with `NotImplementedError`. **SQLite has no `ALTER` that adds or drops a
  constraint**, so `create_foreign_key` and `drop_constraint` have to go through batch
  mode — the copy-and-move strategy — and a partial index's `where` clause has to be
  `sa.text()` rather than a bare string.

  It had been broken for three releases. **Round-tripping only against PostgreSQL hid
  it**: that stays the authoritative check, but **the steps the documentation gives have
  to be known to work** on their own. `tests/test_migrations.py` now runs
  `upgrade → downgrade base → upgrade` on SQLite and compares the migrated schema's
  tables and columns against what the models declare.

  PostgreSQL behaviour is unchanged — `batch_alter_table` emits the same plain `ALTER`
  there. **The widening migration still does nothing on SQLite**, which does not enforce
  varchar lengths; rebuilding tables that carry primary and foreign keys to change a
  number SQLite ignores is not worth the risk (`alembic check` against SQLite reports
  exactly that difference).

- **The example ARKs in the documentation were not identifiers this ledger can mint.**
  The reference and concept pages showed `ark:99999/x9abc` — a three-character blade, no
  check digit, and an `a`, which betanumeric does not contain. Only the walkthrough
  showed a real one (`ark:99999/c7w545sj4z5`), so the pages disagreed with each other
  about how long a name is. **Readers learn the shape from the examples**, and the shape
  being taught was one `mint` cannot produce.

  Every example is now a shoulder plus eight betanumeric characters plus a check digit,
  computed with the implementation's own `noid_check_digit`. `ark:99999/x9tn1qkq2g7` —
  the name the walkthrough actually mints — now runs through the whole site, and the
  mistranscription example is one character away from it (`…g8`), so why `ARKHE-1403` is
  a different answer from "no such ARK" can be read off the example itself. The examples
  inside the OpenAPI descriptions moved with them.

  **A test holds the line** (`test_docs`): every `ark:99999/…` in the documentation and
  in the generated OpenAPI must be betanumeric and must verify. The two deliberately
  wrong ones are listed with the reason each exists, and the test also checks that they
  still fail and are still in the documentation — a stale allowance cannot open a hole
  quietly.

## [0.2.0] — 2026-09-07

**The release that lets a closed ledger hand its names to a public one.** An ARK minted
inside a network the outside cannot reach can now be taken into the public ledger and
published under **the same identifier** — until now, opening an embargoed object meant
issuing a different ARK, and every reference handed out while it was closed died. That
was the largest gap in running arkhe on both sides of a boundary.

Delegation was reworked around the same case: **`minter` had been carrying two
incompatible meanings**, and the constraint that forced it to carry them is gone. Sizing
is now measured rather than asserted.

### Added

- **Sizing, measured rather than guessed.** [Deployment](https://rcosdp.github.io/arkhe/guides/deployment/#sizing)
  now carries throughput and latency for resolution and minting, and
  [the data model](https://rcosdp.github.io/arkhe/reference/data-model/#on-capacity)
  carries bytes per ARK with the queries to measure your own. Everything came off one
  machine against a ledger of a million ARKs, and the pages say so — they are a shape to
  reason with, not a guarantee.

  The two findings worth knowing before capacity planning: **resolution does not care how
  large the ledger is** (one index scan; a million rows resolve like a thousand, and
  throughput follows the worker count), and **minting one at a time is bound by Argon2**,
  not by the database — 53 ms of the 82 is verifying the API key, which is why bulk
  minting is twenty times faster and the only sane way to ingest at scale.

- **`scripts/bench.py`** — the load harness those numbers came from. `check.sh` does not
  call it: a benchmark depends on the machine and the hour, so it cannot be spoken about
  in green and red. It warms up before measuring, and the documentation says to check
  `/healthz` first, because a client that saturates before the server is measuring itself.

- **Section 10 of the walkthrough now builds both ledgers from scratch.** The public and
  the closed side are **operated separately** — no shared database, no replication, no
  sync — so the example starts where that starts: `arkhe naan add`, `onboard`,
  `shoulder add`, and the `delegated` / `redirect` pair that tells the outside a namespace
  is closed. Namespace allocation is CLI work, not REST, and the page now says so.

  It then mints on each side with curl — the open shoulder the ordinary way, the closed
  one refused by the public minter with a `307` at the delegate — and resolves the same
  name on both resolvers before and after it is handed over. Two ledgers, four processes,
  **one transcript from one run**.

- **A worked closed-then-published example**, as section 10 of
  [the walkthrough](https://rcosdp.github.io/arkhe/guides/walkthrough/): mint inside a
  closed network, see what the public resolver says before and after, import the name
  with a description and no target, raise it to an application form and then to the
  object, and the refusals. Two ledgers, four processes, **every response copied from a
  running pair**.

- **`POST /api/import` and `/api/import/bulk` take in an ARK minted elsewhere**, one at a
  time or a whole delegated shoulder at once. This was the largest gap in running a closed
  arkhe underneath a public one: names minted inside the closed network could never reach
  the public ledger, so opening an embargoed object meant issuing a *different* ARK — and
  every reference handed out while it was closed died. Now the same identifier is
  published by [one change of target](https://rcosdp.github.io/arkhe/guides/federation/#pid).

  **Importing is not minting**, and it carries its own scope (`ark:import`): minting hands
  you a name, importing asserts one. Three checks, none waivable — the shoulder is
  **delegated**, the name falls inside it, and the **check digit verifies**, which for a
  name arriving from outside is the only evidence that it was not mistyped. The ledger
  must also be **authoritative for the NAAN**; taking custody of names in a namespace you
  merely forward would be claiming to be its keeper. Reach follows the usual rule —
  **higher authority covers lower** — and the bulk form creates nothing at all if any row
  fails, because names that did land cannot be taken back.

### Fixed

- **Delegation no longer requires a destination at all.** Splitting `minter` from
  `about` fixed which field to write in, but left the pressure that put the wrong value
  there in the first place: a `CHECK` constraint dating from the initial schema demanded
  that a delegated shoulder name *somewhere*. For a namespace delegated into a closed
  network there is nowhere to name, so the constraint could only be satisfied by writing
  something untrue — an internal hostname, or a page for people in a field that promises
  an API.

  **Delegation records that this ledger does not mint here**; publishing where minting
  happens is a separate, optional thing. A minting request against a shoulder with
  neither is answered `403 ARKHE-1309` — "minting happens elsewhere" — with no invented
  URL. `about` appears in `detail` only when there is one.

- **`shoulder.minter` was carrying two incompatible meanings.** It is published in
  `/.well-known/ark` and used as the `Location` of the `307` that answers a minting
  request — both of which claim, in machine-readable form, "call this to mint". For a
  namespace delegated into a closed network there is no such endpoint an outsider can
  call, and the guidance was to write a human explanation page there instead. **That makes
  the claim false**: a client follows the `307` and `POST`s to a web page, and nothing in
  the response distinguishes an API from a page.

  `shoulder.about` now holds the page for people. A delegated shoulder needs one or the
  other (the check constraint moved from `minter <> ''` to `minter <> '' OR about <> ''`),
  and a minting request is answered:

      minter present  →  307, Location: the minter          (unchanged)
      about only      →  403, ARKHE-1309, the URL in the body

  **The 403 branch already existed** in the exception handler and could never be reached,
  because delegation required a `minter`. `/.well-known/ark` now reports the two fields
  separately, so a client can tell a callable endpoint from a page. Existing rows are left
  alone — which `minter` values are really explanation pages is not something the ledger
  can know.

- **"A typo lands on the same page" was wrong.** The check digit is verified *before* the
  shoulder is consulted, so a mistyped identifier under a delegated shoulder answers
  `404 ARKHE-1403`, not the explanation page. What is actually indistinguishable is a name
  that exists from one that never did — which is the property that matters, and the guides
  now say that instead.

- **`arkhe shoulder add` and `arkhe onboard` now print the id they created.** Every other
  shoulder command — `status`, `redirect`, `hold add shoulder` — takes that id, and the
  command that made the thing was the one place not telling you it. Finding it meant
  running `shoulder list` afterwards, which the documentation's own examples quietly did.

- **The English federation guide still listed a CLI for `shoulder.redirect` as missing.**
  `arkhe shoulder redirect` exists and is in the CLI reference; the Japanese page had
  been corrected and the English one had not.

- **The walkthrough now warns that the tail is concatenated as it stands.** Suffix
  passthrough appends what follows the name to the target, so a target carrying a query
  string ends up with the tail inside it (`…/view?id=1` + `/page/3` →
  `…/view?id=1/page/3`). The behaviour is unchanged; it was simply not written down.

- **The federation guide still listed holds as missing.** "A way to suspend redirection
  temporarily" sat under *What does not exist yet* — it shipped in 0.0.9, per ARK, per
  shoulder and per NAAN, with the reason and the expiry published and the clock lifting
  it. The bullet was simply not removed at the time.

## [0.1.0] — 2026-09-07

**The release that closes the gap with the specification, and stops speaking Japanese to
the outside.** Every known deviation from `draft-kunze-ark-42` is gone — four MUSTs and
three SHOULDs — and everything arkhe publishes beyond its own ledger is now English:
the OpenAPI document, and error bodies that carry a stable code so a client never has to
match on a sentence. The admin interface and the `?info` page answer in the language of
the screen instead.

**This is the first release that breaks published output.** The shapes that changed are
listed under Changed and Fixed below; the ledger itself is untouched, and the one
migration only widens columns.

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

- **Redirection can be held, with a deadline** (`arkhe hold add`, `arkhe hold list`,
  `arkhe hold release`, `PUT /api/hold` and `/api/hold/release`, `ark:hold`, and a
  **Held redirects** page in the admin interface).

  **Only redirection stops; resolution does not.** A `404` would be a lie — the
  identifier exists — and a `503` makes the identifier look broken. The answer is `200`
  and the description. There are three grains (`ark`, `shoulder`, `naan`) and **the
  narrower one wins**. **A deadline is required** (capped by `ARKHE_HOLD_MAX_DAYS`): being
  temporary is not left to anyone's memory. That something is held is published, in
  `?json` and in `/.well-known/ark`.

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
- `arkhe client disable` and `arkhe client enable`, and the same control in the interface.

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
- **Operational commands** (`arkhe`), going through the same `domain` as the screens:
  `arkhe check` (validate the configuration), `arkhe succeed` and `arkhe depart`
  (succession and departure), `arkhe shoulder status`, `arkhe client add`,
  `arkhe client key`, `arkhe client passwd`, `arkhe client revoke`, and
  `arkhe client breakglass` for a **time-limited** emergency principal.

### Notes

- Rewritten from Django onto FastAPI and SQLAlchemy 2.0. The specification layer
  (`arkspec/`, `domain/resolution.py`) moved untouched — 97 tests came across
  unmodified.
- `arkspec/` derives in part from the Internet Archive's arklet (MIT); see NOTICE.

[Unreleased]: https://github.com/RCOSDP/arkhe/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/RCOSDP/arkhe/releases/tag/v0.11.0
[0.10.0]: https://github.com/RCOSDP/arkhe/releases/tag/v0.10.0
[0.9.2]: https://github.com/RCOSDP/arkhe/releases/tag/v0.9.2
[0.9.1]: https://github.com/RCOSDP/arkhe/releases/tag/v0.9.1
[0.9.0]: https://github.com/RCOSDP/arkhe/releases/tag/v0.9.0
[0.8.0]: https://github.com/RCOSDP/arkhe/releases/tag/v0.8.0
[0.7.0]: https://github.com/RCOSDP/arkhe/releases/tag/v0.7.0
[0.6.0]: https://github.com/RCOSDP/arkhe/releases/tag/v0.6.0
[0.5.1]: https://github.com/RCOSDP/arkhe/releases/tag/v0.5.1
[0.5.0]: https://github.com/RCOSDP/arkhe/releases/tag/v0.5.0
[0.4.0]: https://github.com/RCOSDP/arkhe/releases/tag/v0.4.0
[0.3.0]: https://github.com/RCOSDP/arkhe/releases/tag/v0.3.0
[0.2.0]: https://github.com/RCOSDP/arkhe/releases/tag/v0.2.0
[0.1.0]: https://github.com/RCOSDP/arkhe/releases/tag/v0.1.0
[0.0.9]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.9
[0.0.8]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.8
[0.0.7]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.7
[0.0.6]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.6
[0.0.5]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.5
[0.0.4]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.4
[0.0.3]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.3
[0.0.2]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.2
[0.0.1]: https://github.com/RCOSDP/arkhe/releases/tag/v0.0.1
