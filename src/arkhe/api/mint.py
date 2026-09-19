"""The minting and update API. The shoulder comes from the principal and a request
cannot widen it.

domain.authz makes every decision about reach; this module only shapes HTTP.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, Security
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from arkhe import errors
from arkhe.api.schemas import (
    ArkOut,
    BulkImportIn,
    BulkImportOut,
    BulkMintIn,
    BulkMintOut,
    BulkQueryIn,
    BulkQueryOut,
    BulkUpdateIn,
    BulkUpdateOut,
    DeleteIn,
    DeleteOut,
    HoldIn,
    HoldReleaseIn,
    ImportIn,
    MintIn,
    PatchIn,
    PublishIn,
    PurgeIn,
    RegisterIn,
    StatsOut,
    TombstoneIn,
    UnpublishIn,
    UpdateIn,
)
from arkhe.api.token import scheme as oauth2_scheme
from arkhe.arkspec.naming import ArkParseError, compact_ark, parse_ark
from arkhe.arkspec.shoulder import split_shoulder
from arkhe.auth.deps import Config, CurrentPrincipal, Db
from arkhe.db.models import Ark, MintReceipt, Shoulder
from arkhe.domain import admin_ops, authz, minting, stats
from arkhe.domain.queries import ark_key_from_input

router = APIRouter(prefix="/api", tags=["ark"])


def needs(scope: str) -> list:
    """Declare the scope a route requires. It appears as a security requirement in the
    document, so that what each route needs is machine readable, as
    {"oauth2": ["ark:mint"]}.

    What refuses a request is still require_scope in the body. The declaration and the
    check live in two places, so a test pins them together
    (test_the_declared_scope_matches_the_enforced_one).

    Only oauth2 requirements carry scopes. bearer is type: http, and OpenAPI does not
    allow scopes on any scheme other than oauth2 and openIdConnect, where the array must
    be empty, which is why only oauth2_scheme is wrapped in Security.
    """
    return [Security(oauth2_scheme, scopes=[scope])]



# ------------------------------------------------ The wording in the document
#
# The published document and the docstrings have different readers. A docstring is for
# whoever reads the implementation; the document is for whoever calls the API, and it
# says only what a caller needs. FastAPI prefers description over a docstring, so what
# is published lives here and the explanation stays in the docstring below.

E_MINT = """\
**Mint one new ARK.** Requires `ark:mint`.

The shoulder defaults to the organisation's own. Naming one in the request only asks
whether it lies inside the caller's registered reach — it never widens it.

**Send a `request_id` and a resend will not mint again.** The same principal resending
the same `request_id` gets back the ARK minted the first time, so a lost response does
not leave a dead identifier behind. The status code says which happened:

    201  minted
    200  returned an earlier minting (a resend)

**An ARK is never reissued**, so minting cannot be undone.
"""

E_BULK_MINT = """\
**Mint in bulk.** Requires `ark:mint`. One request holds at most `ARKHE_BULK_LIMIT`
rows (1000 by default).

**One row out of reach and nothing is created.** Reach and shoulder are checked for
every row before any minting, so a half-minted batch cannot be left behind.

**The answer keeps the order of the input**, because resent rows (a `request_id`
already seen) and new ones are mixed and the caller has to line them up. `created` and
`replayed` carry the two counts; all resends answer 200, one new minting makes it 201.

Give each row a `request_id` and **an interrupted batch can be sent again as it is** —
rows already minted are skipped. **The same `request_id` twice inside one request still
mints once**: it is one request, so it gets one number.
"""

E_REGISTER = """\
**Register a row for a qualified ARK** — an existing base name plus a qualifier.

Suffix passthrough already covers a reference of any depth; this endpoint **overrides
that default at a single point**: "this subtree lives in another store", "this
derivative sits elsewhere".

**It requires `ark:mint`.** Nothing is minted, but a new resolvable identifier does
appear, so it must not be handed to a principal that holds update rights alone.
"""

E_IMPORT = """\
**Record an ARK that was minted elsewhere.** Requires `ark:import`.

Minting does not let a caller choose the name; this does, and that single difference is
why it has its own scope and its own checks. It exists so that **a name minted inside a
closed network can later be published under the same identifier** — without it, opening
an embargoed object means issuing a different ARK, and every reference handed out while
it was closed dies.

Three things are checked, and none of them can be waived:

* the shoulder is **delegated** — importing into a namespace this ledger mints in could
  collide with its own minter, and a name minted elsewhere only exists because the
  namespace was delegated in the first place;
* the name falls **inside that shoulder**;
* the **check digit verifies** — for a name that arrives from outside, that is the only
  evidence there is that it was not mistyped.

A name already in the ledger is refused rather than overwritten, exactly as minting is.
"""

E_IMPORT_BULK = """\
**Import a whole delegated namespace at once.** Requires `ark:import`. One request holds
at most `ARKHE_BULK_LIMIT` rows.

This is the shape the closed-network case actually needs: a delegate hands over the
names it minted, and they arrive together. Each row goes through exactly the same checks
as a single import, and **one row that fails any of them means nothing is created** — a
half-imported namespace is worse than none, because the names that did land cannot be
taken back.

Rows may span several shoulders, as long as every one of them is delegated and within
the caller's reach.
"""

E_PATCH = """\
**Update the fields you send, and leave the rest alone.** Requires `ark:update`.

`PUT` replaces the record: every field you omit takes its default, so repointing an ARK
with `{"ark": …, "url": …}` alone **empties its title, its who and its when**. That is
correct for a replacement and wrong for what people actually do most of the time, which
is move an object.

Sending a field as `""` clears it; not sending it leaves it untouched. Both are needed,
which is why this is not simply "ignore empty strings".
"""

E_UPDATE = """\
Update an existing ARK. **The manager of the target's shoulder is checked.**
"""

E_BULK_UPDATE = """\
Update in bulk. Rows are matched by key, and **nothing is applied unless every row
is found and in reach** — there is no partial application.
"""

E_PUBLISH = """\
**Publish an ARK.** Requires `ark:mint`.

Until it is published an ARK does not resolve and can be deleted outright; from here on
it resolves, and deleting it means first withdrawing it from publication.

This also **publishes again** an ARK that was withdrawn. The record keeps the moment it
first went out (`first_published_at`), which never changes: what has been out in the
world cannot be made never to have been out.

Publishing twice is not an error — the second call returns the same record, so a lost
response can simply be resent.
"""

E_UNPUBLISH = """\
**Withdraw an ARK from publication.** Requires `ark:unpublish`, and the ARK must be
within your reach — an organisation's own shoulder, a NAAN administrator's own NAAN,
everything for the registration authority.

The record stays and **can be published again**; in the meantime the identifier does not
resolve. It is the reversible half: deleting the record is a separate call, and that one
does not come back.

**`NR` is not broken by this.** A withdrawn name belongs to nobody and there is no path
anywhere that reassigns it, so a stale reference gets `404` — never a different object.
What breaks is "keeps resolving", not "never means something else".

Because the name **has been published**, two things are required: a `reason` (someone may
be citing it already, and there is no way to know that from here) and `confirm` repeating
the ARK (so that a script walking a list cannot withdraw everything by accident).
"""

E_DELETE = """\
**Delete an ARK that has not been published.** Requires `ark:delete`.

This is the one case where an ARK goes away. NR (no re-assignment) binds the names that
were **put out into the world**; a reserved one, minted for an object whose publication
was then abandoned, is better removed than left pointing at nothing forever.

A published ARK is refused with `409` — tombstone it instead. So is one that still has
qualified names under it: withdraw those first.

**The name is not freed.** It is kept in the ledger of withdrawn names and never
assigned again, because a reserved identifier has usually already been handed to
someone — re-using it would be indistinguishable, from the outside, from breaking NR.
"""

E_STATS = """\
**Counts for the ledger as you see it.** Requires `ark:read`.

Nothing outside your reach is included — an organisation sees its own shoulders, a NAAN
administrator its NAAN, the registration authority everything. **A total is itself a
disclosure**: how many identifiers an organisation holds is that organisation's business,
so the same reach that limits the listing limits this.

`withdrawn_after_publication` is kept apart from `withdrawn` on purpose. Retracting a
reservation nobody saw and removing a name that was out in the world are different acts,
and **the second one is the number of times the promise was broken.** It does not belong
hidden inside a total.

**Counting is exact, so it costs time proportional to the number of rows.** The listing
avoids counting because it only needs to know whether there is more; here the number *is*
the answer. What can be avoided is the number of passes: every figure over the same set is
gathered with conditional aggregation, so **the ark table is read twice, not seven times**
— which also keeps the figures consistent with each other, since counts taken separately
drift apart as rows arrive. Measured at about 110 ms over 300,000 ARKs. **This is not an
endpoint to poll every second.**
"""

E_PURGE = """\
**Purge a published ARK** — unpublish and delete in one step. Requires `ark:purge`, and
the ARK must be within your reach.

Everything else in this service exists so that a published identifier keeps resolving.
This endpoint is the one way out, and it is here because **reality sometimes brings a
demand that outweighs an identifier** — a removal order, personal data that should never
have been published, a mass ingest that went in wrong. Without a way out, someone ends up
deleting rows straight from the database, and **a deletion that leaves no trace is the
worst kind.**

So the way is narrow and it is recorded:

* **within your own reach only** — an organisation cannot touch another's shoulder;
* **a reason is required**, and it is kept with the name;
* **`confirm` must repeat the ARK**, so that a script walking a list cannot empty the
  ledger by accident;
* **the name is not freed** — it is never assigned again.

That last point is what survives: the target and the description go, but **the name can
never come to mean something else**. A stale reference gets `404`; it never gets a
different object.
"""

E_TOMBSTONE = """\
**Declare that the object is gone.** The ARK is not deleted.

Under NR (no re-assignment) an identifier cannot be removed; only reachability can be.
**The identifier and its metadata stay**, and the resolver answers with the description.

**Its scope is separate from `ark:update`.** A tombstone says "this is gone", not "this
is elsewhere" — a different meaning with different consequences. It is hard to walk back
and it is public, so it does not belong to routine writers such as an ingest batch.
"""

E_HOLD = """\
**Stop redirecting, temporarily.** Resolution is not stopped — the description keeps
being returned.

For when a delegate is down, a wrong target went out, or an object is moving: you have
to stop quickly without killing the identifier. `404` would be a lie (the identifier
exists) and `503` makes a permanent identifier look broken, so a hold answers **200 with
the description**, the same path a tombstone takes.

**Its scope is separate from `ark:update`**, because stopping is a different decision
from repointing and the reason is published. It is separate from a tombstone too: that
is a permanent declaration, while this is **dated, and keeps the previous target**.
"""

E_HOLD_RELEASE = """\
Lift a hold before its expiry. **An expired hold lifts itself by the clock**, so this
is only for lifting one early.
"""

E_BULK_QUERY = """\
Look up ARKs in bulk. **Reads are confined to the caller's reach**, exactly as writes
are.
"""

def _key(raw: str) -> str:
    """Accept ark:99999/x9tn1qkq2g7, the older ark:/99999/x9tn1qkq2g7, or a bare
    99999/x9tn1qkq2g7.

    The normalisation lives in one place, domain.queries, which the screens, the CLI and
    the API all go through. Written again here, an ARK the API accepts could answer 404
    in the CLI.
    """
    try:
        return ark_key_from_input(raw)
    except ValueError as exc:
        raise authz.Invalid(errors.ARK_UNREADABLE, reason=str(exc)) from exc



def _qualifier_error(exc: Exception) -> authz.Invalid:
    """Map what register_qualified raised to a code.

    The domain does not choose codes: that layer knows nothing about HTTP or the API's
    vocabulary, so the code is chosen here from the type of the exception.
    """
    if isinstance(exc, minting.AlreadyRegistered):
        return authz.Invalid(errors.ALREADY_REGISTERED, ark=str(exc))
    if isinstance(exc, minting.QualifierForm):
        return authz.Invalid(errors.QUALIFIER_FORM)
    if isinstance(exc, minting.QualifierOutsideBase):
        return authz.Invalid(errors.QUALIFIER_OUTSIDE_BASE, qualifier=exc.qualifier)
    if isinstance(exc, minting.NameTooLong):
        return authz.Invalid(errors.NAME_TOO_LONG, length=exc.length, limit=exc.limit)
    return authz.Invalid(errors.ARK_UNREADABLE, reason=str(exc))




def _parse(raw: str):
    try:
        return parse_ark(raw)
    except ArkParseError as exc:
        raise authz.Invalid(errors.ARK_UNREADABLE, reason=str(exc)) from exc


def _check_importable(session, shoulder, name: str, raw: str) -> None:
    """Do every check that needs no write, before writing.

    Whether the shoulder is delegated, whether the name is inside it, whether the check
    digit matches. One row that fails and the bulk import creates nothing.
    """
    try:
        minting.check_importable(session, shoulder, name)
    except minting.NotDelegated as exc:
        raise authz.Forbidden(
            errors.IMPORT_SHOULDER_NOT_DELEGATED, shoulder=exc.shoulder, status=exc.status
        ) from exc
    except minting.BadCheckDigit as exc:
        # Return the string the caller sent. A normalised name would not match what
        # someone hunting for a typo has in front of them.
        raise authz.Invalid(errors.IMPORT_CHECK_DIGIT, ark=raw) from exc
    except minting.OutsideShoulder as exc:
        raise authz.Invalid(
            errors.IMPORT_NAME_OUTSIDE_SHOULDER, name=exc.name, naan=exc.naan
        ) from exc
    except minting.NameTooLong as exc:
        raise authz.Invalid(errors.NAME_TOO_LONG, length=exc.length, limit=exc.limit) from exc
    except minting.Withdrawn as exc:
        raise authz.Invalid(errors.NAME_WITHDRAWN, ark=exc.ark) from exc


def _insert_import(session, principal, shoulder, row) -> Ark:
    """Insert one row that has passed the checks. Only a collision is known here
    (E1)."""
    authz.assert_within_quota(session, principal)
    try:
        return minting.import_minted(
            session,
            shoulder=shoulder,
            name=_parse(row.ark).name,
            created_by=principal.client_id,
            **row.writable(),
        )
    except minting.AlreadyRegistered as exc:
        raise authz.Invalid(errors.ALREADY_REGISTERED, ark=str(exc)) from exc


def _import_one(session, principal, row) -> Ark:
    """Import one row. One at a time or in bulk, the checks are the same.

    Mapping the domain's exceptions to codes happens here: domain/ knows nothing about
    HTTP or the API's vocabulary, so the table lives above.
    """
    parsed = _parse(row.ark)
    shoulder = _shoulder_holding(session, principal, parsed)
    _check_importable(session, shoulder, parsed.name, row.ark)
    return _insert_import(session, principal, shoulder, row)


def _shoulder_holding(session, principal, parsed):
    """Find the shoulder an imported name belongs to, within the principal's reach.

    The first-digit convention cuts the shoulder out of the name, and only that one is
    considered. Searching for a shoulder the name would fit into would leave room to
    slip a name into a namespace that was never delegated.
    """
    prefix = split_shoulder(parsed.name)[0]
    if not prefix:
        raise authz.Invalid(
            errors.IMPORT_NAME_OUTSIDE_SHOULDER, name=parsed.name, naan=parsed.naan
        )
    shoulder = session.scalar(
        select(Shoulder).where(
            Shoulder.naan == parsed.naan, Shoulder.shoulder == f"/{prefix}"
        )
    )
    if shoulder is None:
        raise authz.Invalid(
            errors.IMPORT_NAME_OUTSIDE_SHOULDER, name=parsed.name, naan=parsed.naan
        )
    # Two separate things are checked:
    #   1. whether this ledger is authoritative for that NAAN, since a namespace we
    #      only forward must not have names taken on for it
    #   2. whether this principal reaches that shoulder, where a wider authority covers
    #      a narrower one
    authz.assert_naan_is_ours(session, parsed.naan)
    authz.assert_reaches_shoulder(session, principal, shoulder)
    return shoulder


def _replay(session, principal, request_id: str) -> Ark | None:
    """F4: if this request_id already minted something, return that ARK."""
    if not request_id:
        return None
    key = session.scalar(
        select(MintReceipt.ark).where(
            MintReceipt.client_id == principal.client_id,
            MintReceipt.request_id == request_id,
        )
    )
    return session.get(Ark, key) if key else None


def _keep_receipt(session, principal, request_id: str, ark: Ark) -> None:
    """F4: keep the receipt, in the same transaction as the mint. Separately, a failure
    between the two would leave an ARK minted and a resend minting another."""
    if request_id:
        session.add(
            MintReceipt(client_id=principal.client_id, request_id=request_id, ark=ark.ark)
        )


def _commit_or_replay(session, principal, request_id: str, ark: Ark) -> Ark:
    """Commit, and if the same request_id was written first, return what it wrote.

    There is a gap between checking for a resend (_replay) and writing the receipt. Two
    requests with the same request_id arriving together both see nothing and both write,
    which happens with a retry from a load balancer or a caller that gave up waiting.

    The guard is in the database (one_ark_per_request_id), so the ledger is safe, but
    left alone the loser gets a 500. To the caller that is the worst answer, because it
    says nothing about whether an ARK was minted, and retrying with a new request_id
    would mint a second one.

    So the loser returns the ARK the winner wrote. The promise that a resend gets the
    same answer has to hold whether the requests arrive in sequence or together.
    """
    try:
        session.commit()
        return ark
    except IntegrityError:
        session.rollback()
        if (won := _replay(session, principal, request_id)) is not None:
            return won
        # Not a race but some other inconsistency. It is not swallowed.
        raise


def _apply(ark: Ark, data: dict, principal) -> Ark:
    for field, value in data.items():
        if field == "ark":
            continue
        setattr(ark, "metadata_" if field == "metadata" else field, value)
    ark.updated_by = principal.client_id
    return ark


# ------------------------------------------------------------------ Minting


@router.post(
    "/mint",
    dependencies=needs("ark:mint"),
    response_model=ArkOut,
    status_code=201,
    description=E_MINT,
    # A resend does not answer 201. Without declaring that, a generated client
    # treats the 200 as an unknown response.
    responses={200: {"model": ArkOut, "description": "returned an earlier minting (a resend)"}},
)
def mint(body: MintIn, principal: CurrentPrincipal, session: Db, response: Response):
    """Mint one new ARK. It requires ark:mint.

    The shoulder is the organisation's default when omitted; when named, it is only
    checked against the principal's reach and never widens it.

    With a request_id, a resend does not mint again (F4): the same principal sending the
    same request_id gets the ARK that was minted first, which stops a lost response
    leaving dead numbers behind. The status code says which happened:

      201  it was minted
      200  an earlier minting was returned (a resend)

    An ARK is never reassigned, and minting cannot be undone. Minting with reserve set
    can still be withdrawn until it is published (/api/publish and /api/delete); once
    published, it cannot be removed.
    """
    authz.require_scope(principal, "ark:mint")
    # F4: a resend mints nothing. A lost response must not add a number.
    if (existing := _replay(session, principal, body.request_id)) is not None:
        response.status_code = 200
        return ArkOut.of(existing)
    shoulder = authz.shoulder_for(session, principal, body.shoulder or None)
    authz.assert_shoulder_mintable(shoulder)
    authz.assert_within_quota(session, principal)
    ark, _ = minting.mint(
        session, shoulder=shoulder, created_by=principal.client_id,
        reserve=body.reserve, **body.writable()
    )
    _keep_receipt(session, principal, body.request_id, ark)
    authz.audit(session, principal, "mint", ark.ark, reserved=body.reserve)
    settled = _commit_or_replay(session, principal, body.request_id, ark)
    if settled is not ark:
        # This one lost. The number it drew was never committed, since it was in the
        # same transaction and rolled back, so no number was used up.
        response.status_code = 200
    return ArkOut.of(settled)


@router.post(
    "/mint/bulk",
    dependencies=needs("ark:mint"),
    response_model=BulkMintOut,
    status_code=201,
    description=E_BULK_MINT,
    responses={200: {"model": BulkMintOut, "description": "every row was a resend"}},
)
def bulk_mint(
    body: BulkMintIn, principal: CurrentPrincipal, session: Db, cfg: Config, response: Response
):
    """Mint in bulk. It requires ark:mint, and one request is capped by ARKHE_BULK_LIMIT
    (1000 by default).

    One row out of reach and nothing is created: the reach and the shoulder are checked
    for every row before anything is minted, so no half-minted state is left.

    The answer keeps the order of the input, because resends (rows whose request_id is
    known) are mixed with new mints and the caller has to line them up. created and
    replayed give the two counts. All resends answers 200; one mint answers 201.

    With a request_id on each row, an interrupted batch can be sent again as it stands:
    rows already minted are skipped. Several rows sharing a request_id are collapsed
    into one, because writing the same request twice still means one request.
    """
    authz.require_scope(principal, "ark:mint")
    rows = body.data
    if len(rows) > cfg.bulk_limit:
        raise authz.Invalid(errors.BULK_LIMIT, limit=cfg.bulk_limit)

    # If the same batch arrives twice at once, it is rebuilt once. There is a gap
    # between checking for a resend and writing the receipt, and the loser fails at
    # commit; left alone that is a 500 with nothing minted. Rebuilt, the winner's
    # receipts are visible and every row lines up as a resend, minting nothing.
    # There is no third attempt: losing again would not be a race but some other
    # inconsistency.
    for attempt in (1, 2):
        try:
            return _bulk_mint(session, principal, rows, response)
        except IntegrityError:
            if attempt == 2:
                raise
            session.rollback()
    raise AssertionError("unreachable")  # pragma: no cover


def _bulk_mint(session, principal, rows, response):
    # F4: rows already minted are skipped, so an interrupted batch can be sent again.
    wanted = {r.request_id for r in rows if r.request_id}
    replayed: dict[str, Ark] = {}
    if wanted:
        for rid, key in session.execute(
            select(MintReceipt.request_id, MintReceipt.ark).where(
                MintReceipt.client_id == principal.client_id,
                MintReceipt.request_id.in_(wanted),
            )
        ).all():
            replayed[rid] = session.get(Ark, key)

    # A repeat inside one batch is treated as a resend too. The receipt is unique per
    # (client, request_id), so minting two rows with the same request_id would write the
    # receipt twice, fail at commit with IntegrityError and mint nothing. One request_id
    # means one request, so one ARK is minted and returned for both rows.
    fresh, seen = [], set()
    for r in rows:
        if r.request_id in replayed or r.request_id in seen:
            continue
        if r.request_id:
            seen.add(r.request_id)
        fresh.append(r)
    # Reach is checked for every row first: one out of reach and nothing is created.
    shoulders = [authz.shoulder_for(session, principal, r.shoulder or None) for r in fresh]
    for sh in shoulders:
        authz.assert_shoulder_mintable(sh)
    authz.assert_within_quota(session, principal, len(fresh))

    minted: dict[int, Ark] = {}
    for sh, row in zip(shoulders, fresh, strict=True):
        ark, _ = minting.mint(
            session, shoulder=sh, created_by=principal.client_id,
            reserve=row.reserve, **row.writable()
        )
        _keep_receipt(session, principal, row.request_id, ark)
        minted[id(row)] = ark
    authz.audit(session, principal, "bulk_mint", count=len(minted))
    session.commit()

    # The order of the input is kept, because resends and new mints are mixed and the
    # caller has to line them up.
    by_request = {r.request_id: minted[id(r)] for r in fresh if r.request_id}
    made = [
        replayed.get(r.request_id) or by_request.get(r.request_id) or minted[id(r)]
        for r in rows
    ]
    if not minted:
        response.status_code = 200
    return BulkMintOut(
        minted=[ArkOut.of(a) for a in made], created=len(minted), replayed=len(made) - len(minted)
    )


@router.post(
    "/register",
    dependencies=needs("ark:mint"),
    response_model=ArkOut,
    status_code=201,
    description=E_REGISTER,
)
def register(body: RegisterIn, principal: CurrentPrincipal, session: Db):
    """B4: register a row for an existing ARK with a qualifier attached.

    By default inheritance covers any depth. This route overrides that at one point:
    "this subtree lives in another store", "this converted form is somewhere else".

    It requires ark:mint. Nothing is minted, but a new resolvable identifier comes into
    existence, so it must not be handed to a principal that can only update.
    """
    authz.require_scope(principal, "ark:mint")
    base = authz.fetch_for_update(session, principal, [_key(body.ark)]).popitem()[1]
    authz.assert_may_touch(session, principal, base)
    authz.assert_shoulder_mintable(base.shoulder)
    authz.assert_within_quota(session, principal)
    try:
        ark = minting.register_qualified(
            session,
            base=base,
            qualifier=body.qualifier,
            created_by=principal.client_id,
            **body.writable(),
        )
    except (minting.AlreadyRegistered, ValueError) as exc:
        raise _qualifier_error(exc) from exc
    authz.audit(session, principal, "register_qualified", ark.ark)
    session.commit()
    return ArkOut.of(ark)


# ----------------------------------------------------------------- Updates


@router.post(
    "/import",
    dependencies=needs("ark:import"),
    response_model=ArkOut,
    status_code=201,
    description=E_IMPORT,
)
def import_ark(body: ImportIn, principal: CurrentPrincipal, session: Db):
    """Bring an ARK minted elsewhere into this ledger.

    It is how something moves from C-2 in federation.md, minted on the closed side, to
    C-1, where the public side holds the name and its description. Without it, a name
    handed out while closed could not be published as it stands.

    Its scope is separate from ark:mint because the caller brings the name. Minting is
    asking for a number; importing is asserting that this is the number.
    """
    authz.require_scope(principal, "ark:import")
    ark = _import_one(session, principal, body)
    # Recorded under a different word from minting, so that what came from outside
    # can be traced later.
    authz.audit(session, principal, "import", ark.ark)
    session.commit()
    return ArkOut.of(ark)


@router.post(
    "/import/bulk",
    dependencies=needs("ark:import"),
    response_model=BulkImportOut,
    status_code=201,
    description=E_IMPORT_BULK,
)
def bulk_import(body: BulkImportIn, principal: CurrentPrincipal, session: Db, cfg: Config):
    """Take on a whole shoulder: the names the closed side minted, handed over at once.

    One row that fails and nothing is created, as in M5. Half-imported names cannot be
    taken back, which makes a partial apply worse here than in minting.
    """
    authz.require_scope(principal, "ark:import")
    rows = body.data
    if len(rows) > cfg.bulk_limit:
        raise authz.Invalid(errors.BULK_LIMIT, limit=cfg.bulk_limit)

    # Every row is checked before anything is written, as in bulk minting. A failure
    # partway could be rolled back, but noticing after writing is avoided: importing
    # brings names into existence, and those cannot be taken back.
    checked = [(_shoulder_holding(session, principal, _parse(row.ark)), row) for row in rows]
    for shoulder, row in checked:
        _check_importable(session, shoulder, _parse(row.ark).name, row.ark)

    out: list[Ark] = [_insert_import(session, principal, sh, row) for sh, row in checked]
    authz.audit(session, principal, "bulk_import", count=len(out))
    session.commit()
    return BulkImportOut(imported=[ArkOut.of(a) for a in out], count=len(out))


@router.put(
    "/update",
    dependencies=needs("ark:update"),
    response_model=ArkOut,
    description=E_UPDATE,
)
def update(body: UpdateIn, principal: CurrentPrincipal, session: Db):
    """Update an existing ARK, checking the organisation of its shoulder (M3)."""
    authz.require_scope(principal, "ark:update")
    ark = authz.fetch_for_update(session, principal, [_key(body.ark)]).popitem()[1]
    authz.assert_may_touch(session, principal, ark)
    before = ark.url
    _apply(ark, body.model_dump(), principal)
    # A change of target is recorded whoever made it; the audit log keeps only NAAN
    # level and above.
    authz.record_change(session, principal, ark, action="update", before_url=before)
    authz.audit(session, principal, "update", ark.ark)
    session.commit()
    return ArkOut.of(ark)


@router.patch(
    "/update",
    dependencies=needs("ark:update"),
    response_model=ArkOut,
    description=E_PATCH,
)
def patch(body: PatchIn, principal: CurrentPrincipal, session: Db):
    """Change only the fields that were sent, with the same permissions and checks as
    PUT.

    PUT is for saying "make the record this". In practice the common case is moving only
    the target, and PUT there overwrites every omitted field with its default: what
    ?info should answer with is lost along the way.

    Sending an empty string clears a field; not sending it leaves it alone. Without that
    distinction there would be no way to clear one.
    """
    authz.require_scope(principal, "ark:update")
    ark = authz.fetch_for_update(session, principal, [_key(body.ark)]).popitem()[1]
    authz.assert_may_touch(session, principal, ark)
    before = ark.url
    _apply(ark, body.sent(), principal)
    authz.record_change(session, principal, ark, action="update", before_url=before)
    authz.audit(session, principal, "patch", ark.ark)
    session.commit()
    return ArkOut.of(ark)


@router.put(
    "/update/bulk",
    dependencies=needs("ark:update"),
    response_model=BulkUpdateOut,
    description=E_BULK_UPDATE,
)
def bulk_update(body: BulkUpdateIn, principal: CurrentPrincipal, session: Db, cfg: Config):
    """M5: rows are matched by key, and nothing is applied in part."""
    authz.require_scope(principal, "ark:update")
    rows = body.data
    if len(rows) > cfg.bulk_limit:
        raise authz.Invalid(errors.BULK_LIMIT, limit=cfg.bulk_limit)
    keys = [_key(r.ark) for r in rows]
    found = authz.fetch_for_update(session, principal, keys)  # one missing row is 404
    for key, row in zip(keys, rows, strict=True):
        ark = found[key]
        authz.assert_may_touch(session, principal, ark)
        before = ark.url
        _apply(ark, row.model_dump(), principal)
        authz.record_change(session, principal, ark, action="update", before_url=before)
    authz.audit(session, principal, "bulk_update", count=len(rows))
    session.commit()
    return BulkUpdateOut(updated=len(rows))


# ------------------------------------------- Publishing and withdrawing


@router.post(
    "/publish",
    dependencies=needs("ark:mint"),
    response_model=ArkOut,
    description=E_PUBLISH,
)
def publish(body: PublishIn, principal: CurrentPrincipal, session: Db):
    """Publish a reserved ARK to the world. From then on it resolves and cannot be
    deleted.

    Its scope is ark:mint. Publishing is the second half of minting rather than a
    separate decision: if whoever reserved it could not publish it, every draft would
    need another credential.

    Calling it twice is not an error. A response can be lost, and answering 409 to a
    resend would send the caller off to check somewhere else whether it worked.
    """
    authz.require_scope(principal, "ark:mint")
    ark = admin_ops.publish_ark(session, principal, ark=_key(body.ark))
    session.commit()
    return ArkOut.of(ark)


@router.post(
    "/unpublish",
    dependencies=needs("ark:unpublish"),
    response_model=ArkOut,
    description=E_UNPUBLISH,
)
def unpublish(body: UnpublishIn, principal: CurrentPrincipal, session: Db):
    """Withdraw a publication. The row stays and it stops resolving, within the
    caller's reach.

    Its scope is separate from ark:mint. Publishing and taking down are different
    decisions: handing out a minting credential should not hand out the power to stop a
    name that went out.

    It is separate from ark:delete too. This can be undone and that cannot, and one
    credential for both would give the irreversible one to anyone who only wanted the
    other.
    """
    authz.require_scope(principal, "ark:unpublish")
    ark = admin_ops.unpublish_ark(
        session, principal, ark=_key(body.ark), reason=body.reason, confirm=body.confirm
    )
    session.commit()
    return ArkOut.of(ark)


@router.post(
    "/delete",
    dependencies=needs("ark:delete"),
    response_model=DeleteOut,
    description=E_DELETE,
)
def delete_ark(body: DeleteIn, principal: CurrentPrincipal, session: Db):
    """Delete an ARK that is not published. While it is, this answers 409: withdraw it
    first.

    If the name was ever published, a reason and a confirmation are required. Deleting a
    reservation that was never published loses less, and how much is asked follows what
    the name was, not the caller's tier.


    POST rather than DELETE. Like the other writes it takes the ARK in the body:
    proxies and clients sometimes drop the body of a DELETE, and "the reason disappeared
    but it went through" is the last thing this operation should do.

    Its scope is separate from ark:tombstone. A tombstone states publicly that something
    is gone; this withdraws something nobody has seen yet. They differ in meaning and in
    how irreversible they are.
    """
    authz.require_scope(principal, "ark:delete")
    gone = admin_ops.withdraw_ark(
        session, principal, ark=_key(body.ark), reason=body.reason, confirm=body.confirm
    )
    out = DeleteOut(
        ark=compact_ark(gone.ark), withdrawn_at=gone.withdrawn_at, reason=gone.reason
    )
    session.commit()
    return out


@router.get(
    "/stats",
    dependencies=needs("ark:read"),
    response_model=StatsOut,
    description=E_STATS,
)
def ledger_stats(
    principal: CurrentPrincipal,
    session: Db,
    naan: str = "",
    org: str = "",
):
    """Count the ledger, through the same domain.stats as the screens and the CLI.

    It is a GET: a read with no input, which sits naturally in a path. This API uses
    POST elsewhere because the body carries a key, and there is nothing to carry here.

    naan and org apply the same filters the lists use and never widen the reach: naming
    something out of reach returns zero.
    """
    authz.require_scope(principal, "ark:read")
    return stats.ledger_stats(session, principal, naan=naan, org=org)


@router.post(
    "/purge",
    dependencies=needs("ark:purge"),
    response_model=DeleteOut,
    description=E_PURGE,
)
def purge(body: PurgeIn, principal: CurrentPrincipal, session: Db):
    """Purge a published ARK in one step: withdrawal and deletion together.

    This is the one place where the answer is not simply "you cannot". With no way out,
    someone under pressure edits the database directly, and a deletion that leaves no
    trace is worse. The reasoning and the guards are in admin_ops.purge_ark.

    It requires its own scope: holding ark:delete is not enough. Removing something that
    went out, in one step, is a separate decision.
    """
    authz.require_scope(principal, "ark:purge")
    gone = admin_ops.purge_ark(
        session, principal, ark=_key(body.ark), reason=body.reason, confirm=body.confirm
    )
    out = DeleteOut(
        ark=compact_ark(gone.ark),
        withdrawn_at=gone.withdrawn_at,
        reason=gone.reason,
        was_published_at=gone.published_at,
    )
    session.commit()
    return out


@router.put(
    "/tombstone",
    dependencies=needs("ark:tombstone"),
    response_model=ArkOut,
    description=E_TOMBSTONE,
)
def tombstone(body: TombstoneIn, principal: CurrentPrincipal, session: Db):
    """Declare that the object is gone. The ARK is not deleted.

    Having declared NR, the identifier cannot be removed. What can be removed is
    reachability; the identifier and its metadata stay.

    Its scope is separate from ark:update. A tombstone says "it is gone" rather than
    "it is here", which differs in meaning and in consequence. It is hard to undo and it
    is published, so it is not handed to an everyday writer such as a loading batch.
    """
    authz.require_scope(principal, "ark:tombstone")
    ark = authz.fetch_for_update(session, principal, [_key(body.ark)]).popitem()[1]
    authz.assert_may_touch(session, principal, ark)
    before = ark.url
    # With an empty url the resolver returns the description itself, as in D6.
    ark.url = body.url
    if body.commitment:
        ark.commitment = body.commitment
    ark.updated_by = principal.client_id
    authz.record_change(session, principal, ark, action="tombstone", before_url=before)
    authz.audit(session, principal, "tombstone", ark.ark)
    session.commit()
    return ArkOut.of(ark)


# ---------------------------------------------------- Holding redirection


@router.put(
    "/hold",
    dependencies=needs("ark:hold"),
    response_model=ArkOut,
    description=E_HOLD,
)
def hold(body: HoldIn, principal: CurrentPrincipal, session: Db, cfg: Config):
    """Hold redirection for a while. Resolution is not stopped; the description keeps
    coming back.

    It is for the moments when a delegate is down, a wrong target was handed out, or
    something is being moved: stop quickly without killing the identifier. 404 would be
    untrue, because the identifier exists, and 503 makes it look broken, so it answers
    200 with a description, as D6 and a tombstone do.

    Its scope is separate from ark:update. Stopping something is a different decision
    from changing where it points, and the reason is published. It is separate from a
    tombstone too: that is a permanent statement that something is gone, while this has
    an expiry and keeps the original target.
    """
    authz.require_scope(principal, "ark:hold")
    ark = authz.fetch_for_update(session, principal, [_key(body.ark)]).popitem()[1]
    admin_ops.set_hold(
        session, principal, kind="ark", key=ark.ark,
        until=body.until, reason=body.reason, max_days=cfg.hold_max_days,
    )
    session.commit()
    return ArkOut.of(ark)


@router.put(
    "/hold/release",
    dependencies=needs("ark:hold"),
    response_model=ArkOut,
    description=E_HOLD_RELEASE,
)
def hold_release(body: HoldReleaseIn, principal: CurrentPrincipal, session: Db):
    """Lift a hold before its expiry. An expiry lifts itself against the clock, so this
    is only ever early."""
    authz.require_scope(principal, "ark:hold")
    ark = authz.fetch_for_update(session, principal, [_key(body.ark)]).popitem()[1]
    admin_ops.release_hold(session, principal, kind="ark", key=ark.ark)
    session.commit()
    return ArkOut.of(ark)


@router.post(
    "/query",
    dependencies=needs("ark:read"),
    response_model=BulkQueryOut,
    description=E_BULK_QUERY,
)
def bulk_query(body: BulkQueryIn, principal: CurrentPrincipal, session: Db, cfg: Config):
    """M4: reads are bounded by reach too. arklet did no authorisation at all."""
    authz.require_scope(principal, "ark:read")
    keys = [_key(a) for a in body.data[: cfg.bulk_limit]]
    arks = authz.visible_arks(session, principal, keys)
    return BulkQueryOut(data=[ArkOut.of(a) for a in arks])
