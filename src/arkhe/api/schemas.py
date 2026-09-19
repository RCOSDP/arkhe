"""The API request and response models. The OpenAPI document is generated from
them."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from arkhe import errors
from arkhe.arkspec.naming import compact_ark
from arkhe.domain.resolution import DANGEROUS_SCHEMES, is_registrable

#: The fields a caller may set. shoulder is not among them: it follows from the
#: principal.
WRITABLE = (
    "url",
    "title",
    "type",
    "identifier",
    "format",
    "relation",
    "source",
    "commitment",
    "metadata",
    "who",
    "when",
)



def _spec(description: str) -> ConfigDict:
    """Set the description a schema publishes.

    Pydantic uses a class docstring as the schema description. The docstring is written
    for whoever reads the implementation, while what the document publishes is written
    for readers outside this ledger, so the published wording is set here.
    """
    return ConfigDict(json_schema_extra={"description": description})


class ArkFields(BaseModel):
    """The ERC and Dublin Core fields. All optional."""

    model_config = _spec("ERC / Dublin Core fields. All optional.")

    @field_validator("url")
    @classmethod
    def _safe_url(cls, v: str) -> str:
        """Refuse only what is dangerous for a browser to interpret.

        An ARK can name a physical object or another identifier, so urn:, doi: and ark:
        must all be accepted, and empty is valid too: an object with no target.

        What is refused is javascript:, data: and the like, because ?info is a public
        page that needs no credentials and whoever minted the ARK chooses the text on
        it.
        """
        if not is_registrable(v):
            raise ValueError(
                errors.URL_SCHEME_REFUSED.say(schemes="/".join(sorted(DANGEROUS_SCHEMES)))
            )
        return v

    url: str = ""
    title: str = ""
    type: str = ""
    identifier: str = ""
    format: str = ""
    relation: str = ""
    source: str = ""
    commitment: str = ""
    metadata: str = ""
    who: str = ""
    when: str = ""

    def writable(self) -> dict:
        return self.model_dump(include=set(WRITABLE))


class MintIn(ArkFields):
    """Input for minting.

    shoulder is optional. Omitted, the organisation's default_shoulder is used; named,
    it is only checked against the registered reach and never widens it. naan is not
    accepted: it follows from the principal.
    """

    model_config = _spec(
        "Input for minting. `shoulder` is optional: omitted, the organisation's "
        "default is used; named, it is only checked against the caller's registered "
        "reach, never widening it. `naan` is not accepted — it follows from the "
        "principal."
    )

    shoulder: str = ""
    #: Mint it as reserved: it does not resolve, and it can still be deleted.
    reserve: bool = Field(
        default=False,
        description=(
            "Mint it **without publishing it**. A reserved ARK does not resolve, and "
            "it can still be deleted; publish it when the object goes public. The "
            "default mints and publishes in one step, as before."
        ),
    )
    #: F4: the key that stops a resend minting twice. The caller supplies it.
    request_id: str = Field(
        default="",
        max_length=200,
        description=(
            "Idempotency key. Resending the same value returns the ARK minted the "
            "first time, instead of minting again."
        ),
    )


class RegisterIn(ArkFields):
    """B4: registering a qualified ARK.

    ark is an existing base name and qualifier is the part reference appended to it.
    Nothing is minted, so no NOID and no check digit are generated.
    """

    model_config = _spec(
        "A qualified ARK: `ark` is an existing base name and `qualifier` the part "
        "reference appended to it. Nothing is minted, so no NOID and no check digit "
        "are generated."
    )

    ark: str = Field(description="An existing base ARK (`ark:99999/x9tn1qkq2g7`).")
    qualifier: str = Field(description="Begins with `/` (a part) or `.` (a variant).")


class ImportIn(ArkFields):
    """Import an ARK that was minted elsewhere.

    The caller brings the name in ark. That is the one decisive difference from mint:
    everything mint guaranteed structurally becomes a check here. See
    `domain.minting.import_minted`。
    """

    model_config = _spec(
        "An ARK minted elsewhere, to be recorded here. Unlike minting, **the caller "
        "brings the name**; it must fall inside a delegated shoulder of this ledger and "
        "its check digit must verify."
    )

    ark: str = Field(
        description="The ARK as it was minted elsewhere (`ark:99999/c7962c644f8`)."
    )


class HoldIn(BaseModel):
    """Hold redirection. Resolution is not stopped; the description keeps coming back.

    until is required because "temporary" left to memory becomes permanent. reason is
    required because it is published at ?info and because lifting the hold needs it: a
    hold with no reason cannot be lifted by anyone but whoever set it.
    """

    model_config = _spec(
        "A temporary stop on redirection. **Resolution is not stopped** — the "
        "description keeps being returned. `until` is required because a "
        "\"temporary\" left to memory becomes permanent; `reason` is required "
        "because it is published, and because lifting the hold needs it."
    )

    ark: str
    until: datetime = Field(
        description="No redirection until this moment. A time in the past is refused."
    )
    reason: str = Field(
        min_length=1,
        max_length=500,
        description="Why redirection is stopped. **This is published.**",
    )


class HoldReleaseIn(BaseModel):
    """Lift a hold before its expiry."""

    model_config = _spec("Lift a hold before its expiry.")

    ark: str


class UpdateIn(ArkFields):
    """Input for PUT: the record is replaced, so an omitted field takes its
    default."""

    model_config = _spec(
        "Input for a replacing update. **Every omitted field takes its default**, so "
        "send the whole record; to change one field and leave the rest alone, PATCH."
    )

    ark: str


class PatchIn(ArkFields):
    """Input for PATCH: only the fields that were sent are changed.

    The only difference from PUT is how an omitted field is read: there it means "make
    it empty", here it means "leave it alone". model_fields_set holds the keys that were
    actually sent, which distinguishes sending an empty string to clear a field from not
    sending it at all. Without that, there would be no way to clear a field.
    """

    model_config = _spec(
        "Input for a merging update. **Only the fields actually sent are written**; "
        "everything else is left as it is. Sending a field as \"\" clears it, which is "
        "how a value is removed."
    )

    ark: str

    def sent(self) -> dict:
        """Return only the writable fields that were sent."""
        return {k: v for k, v in self.model_dump(include=set(WRITABLE)).items()
                if k in self.model_fields_set}


class PublishIn(BaseModel):
    """Publish an ARK to the world: one that was reserved, or one that was
    withdrawn."""

    model_config = _spec(
        "Publish an ARK: a reserved one, or one whose publication was withdrawn. From "
        "then on it resolves again. Publishing twice is not an error; the second call "
        "returns the same record. Deleting it now requires unpublishing it first."
    )

    ark: str


class UnpublishIn(BaseModel):
    """Withdraw a publication. The row stays and it stops resolving."""

    model_config = _spec(
        "Withdraw an ARK from publication. The record stays and can be published "
        "again; the identifier stops resolving in the meantime. **The name is never "
        "reassigned**, so a stale reference gets `404`, never a different object. "
        "Because the name has been published, a reason and `confirm` are required."
    )

    ark: str
    reason: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "Why it is being withdrawn. **Required**: someone may be citing it "
            "already, and there is no way to know from here."
        ),
    )
    confirm: str = Field(
        description="The ARK again, to be sure of the target. Anything else is refused."
    )


class DeleteIn(BaseModel):
    """Delete an ARK that is not published. It does nothing to a published one."""

    model_config = _spec(
        "Delete an ARK that is not currently published. One that is published must be "
        "unpublished first (409), or purged in one step. **If it has ever been "
        "published, a reason and `confirm` are required.** The name itself is "
        "remembered and never assigned again."
    )

    ark: str
    reason: str = Field(
        default="",
        max_length=500,
        description=(
            "Why it was withdrawn. Kept with the name; not published. **Required if "
            "the ARK has ever been published.**"
        ),
    )
    confirm: str = Field(
        default="",
        description=(
            "The ARK again. **Required if the ARK has ever been published**, so that "
            "a script walking a list cannot empty the ledger by accident."
        ),
    )


class PurgeIn(BaseModel):
    """Purge a published ARK: withdrawal and deletion in one step, within the
    caller's reach."""

    model_config = _spec(
        "Purge a **published** ARK in one step (unpublish and delete). Within the "
        "caller's own reach, for a legal removal order or data that should never have "
        "been published. A reason is required and `confirm` must repeat the ARK."
    )

    ark: str
    reason: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "Why it is being purged. **Required**: this and the audit log are all that "
            "will be left about the identifier."
        ),
    )
    confirm: str = Field(
        description="The ARK again, to be sure of the target. Anything else is refused."
    )


class DeleteOut(BaseModel):
    """What a withdrawal leaves: the row is gone and the name remains."""

    model_config = _spec(
        "The row is gone; the name is kept so that it is never assigned again."
    )

    ark: str
    withdrawn_at: datetime
    reason: str = ""
    #: For a purge, when the name was published. null means it was withdrawn before
    #: publication.
    was_published_at: datetime | None = None


class TombstoneIn(BaseModel):
    """Declare that the object is gone. The ARK is not deleted."""

    model_config = _spec(
        "Declare that the object is gone. **The ARK is not deleted** — the identifier "
        "and its metadata stay, only reachability goes."
    )

    ark: str
    #: Empty means the resolver returns the description itself, as in D6.
    url: str = ""
    commitment: str = ""


class BulkMintIn(BaseModel):
    data: list[MintIn]


class BulkUpdateIn(BaseModel):
    data: list[UpdateIn]


class BulkImportIn(BaseModel):
    """Import in bulk. One row that fails any check and nothing is created."""

    model_config = _spec(
        "Import in bulk. **One row that fails any check and nothing is created** — a "
        "half-imported namespace is worse than none, because the names that did land "
        "cannot be taken back."
    )

    data: list[ImportIn]


class BulkImportOut(BaseModel):
    imported: list[ArkOut]
    count: int


class BulkQueryIn(BaseModel):
    data: list[str]


class ShoulderStatOut(BaseModel):
    """The breakdown for one shoulder."""

    model_config = _spec(
        "One shoulder's share of the ledger. **The shoulder is the unit the ledger is "
        "organised by**, so this is the breakdown that costs nothing extra to produce."
    )

    naan: str
    shoulder: str
    status: str
    organisation: str = ""
    arks: int
    public: int
    reserved: int


class StatsOut(BaseModel):
    """The ledger as this principal sees it. Nothing out of reach is included."""

    model_config = _spec(
        "Counts for the ledger **as this caller sees it**. Nothing outside the caller's "
        "reach is included — a total is itself a disclosure, since how many identifiers "
        "an organisation holds is that organisation's business. Counting is exact and "
        "therefore costs time proportional to the number of rows, though every figure "
        "over the same set is gathered in one pass: **this is not an endpoint to poll "
        "every second.**"
    )

    scope: str = Field(description="How far the caller reaches: system, naan or organisation.")
    naans: int
    arks: int
    public: int
    reserved: int
    withdrawn: int
    withdrawn_after_publication: int = Field(
        description=(
            "Of the withdrawn names, how many had already been published. **This is the "
            "number of times the promise was broken**, and it is kept separate for that "
            "reason."
        )
    )
    shoulders: dict[str, int]
    organisations: int
    organisations_active: int
    clients: int
    clients_active: int
    holds: dict[str, int]
    minted: dict[str, int] = Field(
        description="ARKs minted within the last 24h, 7 days and 30 days."
    )
    first_mint: datetime | None = None
    last_mint: datetime | None = None
    by_shoulder: list[ShoulderStatOut] = []


class ArkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ark: str
    url: str = ""
    title: str = ""
    type: str = ""
    identifier: str = ""
    format: str = ""
    relation: str = ""
    source: str = ""
    commitment: str = ""
    metadata: str = ""
    who: str = ""
    when: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    #: When it was published to the world. null means it has not been: it does not
    #: resolve and can still be deleted.
    published_at: datetime | None = None
    #: If redirection is held, until when and why. A hold is not hidden.
    hold_until: datetime | None = None
    hold_reason: str = ""

    @classmethod
    def of(cls, ark) -> ArkOut:
        return cls(
            ark=compact_ark(ark.ark),
            **{f: getattr(ark, "metadata_" if f == "metadata" else f) for f in WRITABLE},
            created_at=ark.created_at,
            updated_at=ark.updated_at,
            published_at=ark.published_at,
            hold_until=ark.hold_until,
            hold_reason=ark.hold_reason,
        )


class BulkMintOut(BaseModel):
    minted: list[ArkOut]
    created: int
    replayed: int


class BulkUpdateOut(BaseModel):
    updated: int


class BulkQueryOut(BaseModel):
    data: list[ArkOut]
