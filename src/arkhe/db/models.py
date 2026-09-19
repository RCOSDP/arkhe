"""The domain models (SQLAlchemy 2.0).

One chain, Naan to Manager to Shoulder to Ark, covers every NAAN. Even an organisation
with a NAAN of its own uses a shoulder: without that the model would branch per NAAN,
and the first-digit convention would hold for some NAANs and not others.

The invariants the Django version kept structurally are kept structurally here too:

  E1  an existing ARK is never overwritten silently
      minting is INSERT only, and no merge or upsert path is used (see mint())
  I5  rotation is expressed as a type through a conditional unique constraint
      a partial index (postgresql_where)
  NR  neither a namespace nor a published ARK is deleted
      guards on Shoulder and Ark refuse it; a reserved ARK is the one exception
  R2  an audit trail
  D3  an unknown name under our own NAAN is 404 (decided by Naan.is_authoritative)
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    object_session,
    relationship,
    validates,
)
from sqlalchemy.types import JSON

from arkhe.arkspec.naming import MAX_ARK_LENGTH, MAX_NAAN_LENGTH, MAX_NAME_LENGTH

#: JSONB exists only on PostgreSQL; on SQLite, which the tests use, it falls back to
#: JSON.
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class CommitmentLevel(StrEnum):
    """The NMA commitment: what is promised about serving an object.

    These are NLM's permanence ratings rather than a vocabulary invented here.
    descriptive-only is the one addition, which is not on NLM's axis; it is for physical
    objects.
    """

    NOT_GUARANTEED = "not-guaranteed"
    PERMANENT_DYNAMIC = "permanent-dynamic"
    PERMANENT_STABLE = "permanent-stable"
    PERMANENT_UNCHANGING = "permanent-unchanging"
    DESCRIPTIVE_ONLY = "descriptive-only"


class ShoulderStatus(StrEnum):
    """The administrative state of a shoulder.

    A namespace cannot be taken back once it is handed out: having declared NR, existing
    ARKs keep resolving. So "held but not in use" and "no longer minting" exist as
    states.
    """

    ACTIVE = "active"
    RESERVED = "reserved"
    DELEGATED = "delegated"
    RETIRED = "retired"


class Authority(StrEnum):
    """How far a principal reaches. A wider tier contains the narrower ones.

    ARK is not a scheme where a central authority vouches for things; it delegates
    namespaces, and each organisation states its own promises. These three tiers are that
    delegation, written down.

      SYSTEM   the RA operator, reaching every NAAN: the side that hands namespaces out
      NAAN     everything under one NAAN: the administrator of the organisation holding
               it
      MANAGER  one organisation. With shoulder_id it can be pinned to one shoulder

    Nobody a namespace was delegated to reaches further than whoever delegated it. The
    decision lives in reaches().
    """

    SYSTEM = "system"  # every NAAN: the RA operator
    NAAN = "naan"  # every shoulder under one NAAN
    MANAGER = "manager"  # only that organisation's shoulders


class HoldMixin:
    """A hold on redirection. Resolution is not stopped; only redirection is.

    A delegate's resolver is down, a wrong target was handed out, something confidential
    leaked and has to be taken down, an object is being moved: each is a reason to stop
    quickly without killing the identifier. 404 would be untrue, because the identifier
    exists, and 503 makes it look broken, so it answers 200 with a description, as D6 and
    a tombstone do.

    It differs from a tombstone in meaning and in reversibility:

      tombstone  the object is gone. Permanent, and the original target is discarded
      hold       the object exists but we cannot give out its target. It has an expiry,
                 and the original target is kept

    The expiry is required: "temporary" left to memory becomes permanent. Nothing puts
    an expired hold back either, because the clock is read on each resolution, so nobody
    has to remember to lift one
    （`domain.resolution.hold_of`）。
    """

    #: After this it no longer applies. null means there is no hold.
    hold_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )
    #: Why it is held. It appears on the public endpoints (?info and ?json), so nothing
    #: sensitive belongs here.
    hold_reason: Mapped[str] = mapped_column(String(500), default="")
    hold_by: Mapped[str] = mapped_column(String(255), default="")


class Naan(Base, HoldMixin):
    """Name Assigning Authority Number。

    N2: a naan is a string. 099999 and 99999 are different NAANs and must never become
    integers.
    """

    __tablename__ = "naan"

    naan: Mapped[str] = mapped_column(String(MAX_NAAN_LENGTH), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")

    #: D3: an unknown name under a NAAN we are authoritative for is 404, because we can
    #: say it does not exist. The decision uses this attribute rather than comparing host
    #: names: with several NAANs, those we are authoritative for and those we forward sit
    #: side by side and a string cannot tell them apart.
    is_authoritative: Mapped[bool] = mapped_column(Boolean, default=True)

    #: Where a NAAN we are not authoritative for is forwarded. It means something only
    #: when is_authoritative is False.
    redirect: Mapped[str] = mapped_column(String(500), default="")

    #: The NAA policy: NP | NR, OP, CC | 2026 | <URL>.
    na_policy: Mapped[str] = mapped_column(String(500), default="")

    #: The rules for this namespace: the default for every organisation under it, which
    #: an organisation may narrow but never widen.
    #:
    #: The default belongs to the NAAN because applying it per organisation does not
    #: scale: setting the same restriction on 800 institutions one at a time is not a
    #: workable way to run anything. Per-organisation settings record exceptions; the
    #: rule lives here.
    allowed_auth: Mapped[str] = mapped_column(String(100), default="")
    may_self_register: Mapped[bool] = mapped_column(Boolean, default=True)
    max_scopes: Mapped[str] = mapped_column(String(200), default="")

    #: Where minting for this NAAN happens when it happens elsewhere. Resolution may
    #: still continue here. It is published at /.well-known/ark so that a client knows
    #: where to go.
    minter: Mapped[str] = mapped_column(String(500), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    managers: Mapped[list[Manager]] = relationship(back_populates="naan_obj")
    shoulders: Mapped[list[Shoulder]] = relationship(back_populates="naan_obj")

    __table_args__ = (
        # Without authority a redirect is required; with it, redirecting is forbidden
        # (D3).
        CheckConstraint(
            "(is_authoritative AND redirect = '') OR (NOT is_authoritative AND redirect <> '')",
            name="naan_redirect_only_when_not_authoritative",
        ),
    )


class Manager(Base):
    """An organisation: the manager that an n2t shoulder record names, made a row.

    Credentials belong to this rather than to a shoulder, so that adding a shoulder per
    department or per discipline does not mean issuing credentials again.
    """

    __tablename__ = "manager"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    naan: Mapped[str] = mapped_column(ForeignKey("naan.naan"), index=True)

    #: Internal only, never published, so that the opacity of a shoulder (N5) is not
    #: broken.
    name: Mapped[str] = mapped_column(String(200))

    #: Used when a mint request omits the shoulder. Every organisation has one.
    #:
    #: manager to shoulder to manager is a cycle. PostgreSQL wants the target to exist
    #: at CREATE TABLE, so there is no order in which both can be created. use_alter adds
    #: the constraint afterwards, and it is named so that it can be dropped. SQLite does
    #: not show this problem, which is why migrations are verified on PostgreSQL.
    default_shoulder_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "shoulder.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_manager_default_shoulder",
        ),
        nullable=True,
    )

    commitment_level: Mapped[str] = mapped_column(
        String(32), default=CommitmentLevel.PERMANENT_DYNAMIC.value
    )
    quota_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)  # null: no limit

    #: Which authentication mechanisms this organisation may use, space separated. Empty
    #: means the deployment default (ARKHE_AUTH).
    #:
    #: It lets whoever hands out the namespace decide how the other side gets in. "Under
    #: our NAAN, institutions may only enter through the authorisation server" becomes a
    #: statement by the side handing it out rather than a setting on each institution.
    #: The organisation cannot change it: a limit the limited party can lift is not a
    #: limit, as with quota_per_day.
    #:
    #: It applies at authentication, not only when issuing. Stopping new credentials
    #: alone would let those issued before the restriction keep working while everyone
    #: believes it is in force.
    allowed_auth: Mapped[str] = mapped_column(String(100), default="")

    #: Whether an organisation's administrator may register principals.
    #:
    #: It is how much the side handing out the namespace delegates. Where it does not,
    #: "we need another principal" becomes a request to them, which is workable for a
    #: small NAAN and keeps who can get in in one pair of hands.
    may_self_register: Mapped[bool] = mapped_column(Boolean, default=True)

    #: The ceiling on the scopes this organisation's principals may hold, space
    #: separated. Empty means no ceiling.
    #:
    #: It is a ceiling, not a default: it can keep ark:tombstone to the side handing out
    #: the namespace, for instance. The organisation cannot raise it, since a ceiling
    #: that can be raised is not one, and it applies whoever created the principal. To
    #: make an exception, move the ceiling, so that what is declared and what is true do
    #: not drift apart.
    max_scopes: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    #: The successor after a merger. Identifiers survive a change of custodian: having
    #: declared NR, resolution continues. The link is kept so that the lineage can be
    #: followed.
    succeeded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("manager.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    naan_obj: Mapped[Naan] = relationship(back_populates="managers")
    default_shoulder: Mapped[Shoulder | None] = relationship(
        foreign_keys=[default_shoulder_id], post_update=True
    )
    shoulders: Mapped[list[Shoulder]] = relationship(
        back_populates="manager", foreign_keys="Shoulder.manager_id"
    )

    __table_args__ = (UniqueConstraint("naan", "name", name="uniq_manager_name_per_naan"),)


class Shoulder(Base, HoldMixin):
    """A namespace below a NAAN. It is how a namespace is delegated to an
    organisation."""

    __tablename__ = "shoulder"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shoulder: Mapped[str] = mapped_column(String(50))
    naan: Mapped[str] = mapped_column(ForeignKey("naan.naan"), index=True)
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("manager.id", ondelete="CASCADE"), nullable=True, index=True
    )

    name: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")

    #: n2t's redirect: resolution delegated per shoulder. It supports $id, ${blade} and
    #: a leading 303; expansion happens in domain.resolution.expand_redirect.
    redirect: Mapped[str] = mapped_column(String(500), default="")

    #: n2t's minter: where minting is delegated to, as an endpoint a machine can call.
    #: With status=delegated, a mint request is pointed here with 307; nothing is
    #: proxied.
    #:
    #: It may be empty. Delegating means deciding that we do not mint here, not
    #: announcing where minting happens. Requiring a URL used to push internal host names
    #: and explanatory pages into this field: pressure to invent a value to satisfy a
    #: constraint.
    #:
    #: Leave it empty when nothing outside can reach it, and never put an explanatory
    #: page here. /.well-known/ark and the Location of a 307 both promise that calling
    #: this mints something, and a page for people leaves the recipient no way to tell.
    #: Such a delegation uses about instead.
    minter: Mapped[str] = mapped_column(String(500), default="")

    #: Guidance for people: minting for this namespace happens elsewhere, and here is
    #: the explanation.
    #:
    #: It is separate from minter because an endpoint a machine calls and a page a
    #: person reads are different things. On a shoulder delegated to a closed network,
    #: minter is empty and only about is set, and a mint request answers 403 with the
    #: guidance in the body: a 307 to a page for people would make clients POST to that
    #: page.
    about: Mapped[str] = mapped_column(String(500), default="")

    status: Mapped[str] = mapped_column(
        String(16), default=ShoulderStatus.ACTIVE.value, index=True
    )
    note: Mapped[str] = mapped_column(String(500), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    naan_obj: Mapped[Naan] = relationship(back_populates="shoulders")
    manager: Mapped[Manager | None] = relationship(
        back_populates="shoulders", foreign_keys=[manager_id]
    )

    __table_args__ = (
        UniqueConstraint("shoulder", "naan", name="uniq_shoulder_per_naan"),
    )

    @property
    def can_mint_here(self) -> bool:
        return self.status == ShoulderStatus.ACTIVE.value


class Ark(Base, HoldMixin):
    """A minted ARK.

    Child resources are not minted. Inheritance covers any depth, so one record is one
    mint, which is what keeps the capacity plan workable.
    """

    __tablename__ = "ark"

    #: <naan>/<name>. For N2 the naan is joined as a string. The width comes from the
    #: minimums the specification requires: 16 for the NAAN, a slash, and 255 for the
    #: base name plus qualifier.
    ark: Mapped[str] = mapped_column(String(MAX_ARK_LENGTH), primary_key=True)
    naan: Mapped[str] = mapped_column(ForeignKey("naan.naan"), index=True)
    shoulder_id: Mapped[int] = mapped_column(ForeignKey("shoulder.id"), index=True)
    assigned_name: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH))

    url: Mapped[str] = mapped_column(String(2000), default="")
    commitment: Mapped[str] = mapped_column(Text, default="")
    metadata_: Mapped[str] = mapped_column("metadata", Text, default="")

    #: When it was published to the world. null means it has not been.
    #:
    #: NR binds names that went out. It does not bind from the moment of minting: giving
    #: a draft a number in advance and then deciding not to publish it, leaving that
    #: number in the ledger naming nothing, is not keeping the promise either.
    #:
    #: So a reserved state exists. A reserved ARK:
    #:
    #:   - does not resolve (domain.resolution treats it as an unregistered name)
    #:   - can be deleted (domain.admin_ops.withdraw_ark)
    #:
    #: Whether it is published right now. In 0.3.0 this was one-way; 0.4.0 made it
    #: reversible, because the decision to take something down belongs to the
    #: organisation that holds the object. Taking it down does not erase that it was
    #: published (see first_published_at).
    #:
    #: The default is to publish as it is minted, which keeps the previous behaviour:
    #: requiring an extra step would quietly leave callers who forget it minting ARKs
    #: that never resolve.
    #:
    #: The value is not decided by a column default. SQLAlchemy does not distinguish
    #: assigning None from leaving a value out and applies the default to both, so
    #: default=utcnow would silently publish a reservation. domain.minting, the only
    #: layer that creates an Ark, decides the value; this is only the column.
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )

    #: Whether it was ever public: when it was first published, and it is never
    #: cleared.
    #:
    #: published_at goes back and forth; this is one-way. A name that went out into the
    #: world does not become one that never did, because someone may have cited it in
    #: the meantime and there is no way to know from here.
    #:
    #: This column decides how much ceremony an operation takes, not who may perform it.
    #: Withdrawing a name that was never published is light; withdrawing one that was
    #: requires a reason and the ARK typed again (domain.admin_ops). The weight follows
    #: the name's history rather than the caller's tier, because what matters is what is
    #: being lost, not who is deleting it.
    first_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    # The ERC and Dublin Core fields
    title: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(Text, default="")
    identifier: Mapped[str] = mapped_column(Text, default="")
    format: Mapped[str] = mapped_column(Text, default="")
    relation: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(Text, default="")
    who: Mapped[str] = mapped_column(Text, default="")
    when: Mapped[str] = mapped_column(Text, default="")

    # R2: the audit trail
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    created_by: Mapped[str] = mapped_column(String(255), default="", index=True)
    updated_by: Mapped[str] = mapped_column(String(255), default="")

    shoulder: Mapped[Shoulder] = relationship()

    __table_args__ = (Index("ix_ark_shoulder_created", "shoulder_id", "created_at"),)

    @validates("url")
    def _refuse_dangerous_url(self, _key: str, value: str) -> str:
        """Refuse, at the bottom layer, a target that is dangerous for a browser to
        interpret.

        The API schema (ArkFields) validates this too, but only on the JSON routes: the
        admin form took a plain string and called minting.mint() directly, so it went
        straight past. The rule that the screens and the API behave alike could not hold
        with validation written at each entrance.

        It was not exploitable. Redirection and links go through an allow list
        (is_followable, http and https only), so a javascript: URL was never followed or
        linked. But that guards the moment of use, and the moment of entry needs its own:
        if the allow list is ever loosened, what is already in the ledger starts to
        matter.

        urn:, doi:, ark: and mailto: are not refused. An ARK can name a physical object
        or another identifier, so a target is not necessarily an HTTP URL.
        """
        from arkhe.domain.resolution import DANGEROUS_SCHEMES, is_registrable

        if not is_registrable(value):
            raise ValueError(
                "a url may not use a scheme a browser could execute: "
                + "/".join(sorted(DANGEROUS_SCHEMES))
            )
        return value

    @property
    def is_public(self) -> bool:
        """Whether it may resolve right now. False once it has been withdrawn."""
        return self.published_at is not None

    @property
    def was_ever_public(self) -> bool:
        """Whether it was ever public. It stays true after a withdrawal and is never
        cleared."""
        return self.first_published_at is not None


class Subject(StrEnum):
    """What kind of principal this is: a person or a machine.

    Without the distinction, the header an authenticating proxy sets (X-Forwarded-User)
    could be used to become a machine client. Placing the proxy correctly prevents it,
    but one wrong setting turning into "rewrite everything as the loading batch" is too
    fragile.

      machine  identifies itself with a credential, an API key or a client secret, and
               cannot sign in from outside
      person   vouched for by an external authorisation server or proxy, and holds no
               credential
    """

    MACHINE = "machine"
    PERSON = "person"


class Client(Base):
    """A principal. An API key, a token we issued and an OIDC token all end here.

    The point is that the reach, the NAAN, the organisation, the shoulder and the scopes,
    is an attribute of the registration rather than something named in a token request or
    a request body, which is what prevents privilege escalation.
    """

    __tablename__ = "client"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: The identifier shown outside, matching an OAuth2 client_id or an OIDC sub or
    #: azp.
    client_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    naan: Mapped[str] = mapped_column(ForeignKey("naan.naan"), index=True)
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("manager.id", ondelete="CASCADE"), nullable=True, index=True
    )

    #: Person or machine. This one column decides which routes can be used to identify
    #: as it (see Subject).
    subject_type: Mapped[str] = mapped_column(String(16), default=Subject.MACHINE.value)

    #: The reach is an attribute of the registration, never named in a token request.
    authority: Mapped[str] = mapped_column(String(16), default=Authority.MANAGER.value)

    #: Optionally pins this client to one shoulder. Several clients minting into one
    #: shoulder is ordinary: a web API, a worker and a loading batch all use the same
    #: namespace. Each is issued its own credential, and none of them share one.
    shoulder_id: Mapped[int | None] = mapped_column(
        ForeignKey("shoulder.id"), nullable=True
    )

    #: The operations granted. A scope that was not registered must not be obtainable
    #: through a token request.
    allowed_scopes: Mapped[str] = mapped_column(String(200), default="ark:mint")

    active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # required when authority=naan
    label: Mapped[str] = mapped_column(String(200), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    manager: Mapped[Manager | None] = relationship()
    shoulder: Mapped[Shoulder | None] = relationship()
    credentials: Mapped[list[Credential]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # I5: unique on (manager, label) among the active ones, so that disabling the
        # old one and issuing another under the same label works: rotation expressed as
        # a type.
        #
        # An empty label is outside the constraint. Empty means unnamed, not a name
        # collision. Including it would stop one organisation having two unlabelled
        # principals, which rules out an ordinary split by role: web-api, web-ui and
        # worker.
        Index(
            "uniq_active_label_per_manager",
            "manager_id",
            "label",
            unique=True,
            postgresql_where=active.is_(True) & (label != ""),
            sqlite_where=active.is_(True) & (label != ""),
        ),
    )


class CredentialKind(StrEnum):
    """The kinds of credential. A person can hold only a password.

    API keys and client secrets belong to machines: handed to a person, they outlive
    their time at the organisation. A password is not given to a machine, which has
    nobody to remember it.
    """

    API_KEY = "api_key"  # as in arklet. The plaintext is returned once, when issued
    CLIENT_SECRET = "client_secret"  # for OAuth2 client_credentials
    PASSWORD = "password"  # local sign-in to the admin interface, for people only


class Credential(Base):
    """A client's credential. The plaintext is not stored.

    API keys and client secrets share one table because they are handled the same way:
    the plaintext is returned once when issued, and afterwards only a hash is compared.
    For rotation, one client may hold several active credentials at once, so that the
    old and the new run side by side during a switch.
    """

    __tablename__ = "credential"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_pk: Mapped[int] = mapped_column(
        ForeignKey("client.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), default=CredentialKind.API_KEY.value)

    #: A prefix that makes lookup constant time. It is not a secret: it is the first
    #: eight characters of the plaintext. Without it, every row's hash would have to be
    #: tried, which is what arklet did.
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    hashed: Mapped[str] = mapped_column(String(255))

    active: Mapped[bool] = mapped_column(Boolean, default=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Stops guessing. Offering a login page without this leaves it open. An API key is
    #: 256 random bits and needs none, but a password chosen by a person can be
    #: guessed.
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    client: Mapped[Client] = relationship(back_populates="credentials")


class MintReceipt(Base):
    """F4: the receipt of a mint, so that a resend with the same request_id gets the
    same ARK.

    Minting cannot simply be retried: an ARK declares NR, and resending after a lost
    response adds an ARK that names nothing, a dead number.

    But over a batch of tens of thousands, a network dropping partway is ordinary. With
    a receipt, resending is safe: the caller supplies a request_id and the server pins it
    to one row per (client, request_id).

    They are per client. They do not collide with another organisation's request_ids, and
    guessing one does not reveal another organisation's ARK.
    """

    __tablename__ = "mint_receipt"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(255), index=True)
    request_id: Mapped[str] = mapped_column(String(200))
    ark: Mapped[str] = mapped_column(ForeignKey("ark.ark"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("client_id", "request_id", name="one_ark_per_request_id"),
    )


class ArkChange(Base):
    """The record of an ARK's target changing.

    Without it, where something used to point cannot be recovered. A scheme that declares
    NR and says an identifier does not change has to be able to show what changed, when,
    and who changed it; otherwise nobody outside can verify the promise.

    There are two reasons it is separate from the audit log:

      the audit log keeps only operations at NAAN level and above, while minting and
      repointing are done by organisations, so it would miss the changes that matter
      (R2 in authz.audit)

      the audit log is for operators, while this is the history of the identifier
      itself. They are kept for different periods and thinned differently: the audit log
      can be thinned, this cannot

    Rows are only ever added. A history that can be deleted is not a history.
    """

    __tablename__ = "ark_change"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ark: Mapped[str] = mapped_column(ForeignKey("ark.ark"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    #: `update` / `tombstone` / `hold` / `release_hold` / `publish`。
    #: Kept apart because they mean different things: repointing a target, declaring
    #: that an object is gone, and publishing to the world are three separate acts.
    action: Mapped[str] = mapped_column(String(16))

    #: The target before the change. This is what anyone would want to recover.
    before_url: Mapped[str] = mapped_column(String(2000), default="")
    after_url: Mapped[str] = mapped_column(String(2000), default="")

    by: Mapped[str] = mapped_column(String(255), default="", index=True)
    ip: Mapped[str] = mapped_column(String(45), default="")


class AuditEvent(Base):
    """R2: who did what and when. Every operation at NAAN level and above is
    recorded."""

    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    client_id: Mapped[str] = mapped_column(String(255), index=True)
    authority: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(MAX_ARK_LENGTH), default="")
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)

    #: The caller's address: the result of trusting whatever is in front, not evidence.
    #: With ARKHE_TRUSTED_PROXIES at 0 it is the direct peer itself.
    ip: Mapped[str] = mapped_column(String(45), default="", index=True)

    __table_args__ = (Index("ix_audit_authority_at", "authority", "at"),)


class UnknownSubject(Base):
    """A principal that arrived from the authorisation server without a registration.

    One wrong character means a silent 401, and at the moment of refusal arkhe has that
    exact string in hand: azp has already passed signature verification. Keeping it lets
    an operator register without retyping.

    Only what the authorisation server signed is kept. A string typed into a login field
    is not (see record_sign_in), but this is different: it is not a value an attacker can
    plant, and without it an operator has no way to track down a typo.

    Which organisation it belongs to is unknown. The token does not say, and nothing here
    guesses, so it is visible only to principals that reach NAAN level or above: shown to
    an organisation-level administrator, it would mix in another organisation's client
    ids.
    """

    __tablename__ = "unknown_subject"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    #: The identifier from the authorisation server, taken as azp, then client_id,
    #: then sub.
    subject: Mapped[str] = mapped_column(String(255), index=True)
    issuer: Mapped[str] = mapped_column(String(500), default="")

    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    #: How many times it arrived. Once is a typo; repeatedly means something is
    #: configured and running, which says how urgent it is.
    seen: Mapped[int] = mapped_column(Integer, default=1)
    ip: Mapped[str] = mapped_column(String(45), default="")

    #: One row per principal, so the table is bounded by the number of clients at the
    #: authorisation server.
    __table_args__ = (UniqueConstraint("subject", "issuer", name="uq_unknown_subject"),)


class WithdrawnName(Base):
    """A name withdrawn before publication. It is never minted again.

    A reserved ARK can be deleted (see Ark.published_at), but what may be deleted is the
    row, not the name. Even unpublished, a reserved string may already be in someone's
    hands: taking a number in advance and putting it on the object is the whole point of
    reserving one. Pointing that name at a different object is indistinguishable, from
    outside, from an NR violation.

    So when the row goes, the name moves here. From then on it:

      - is never drawn by minting (a hit is counted as a collision and retried)
      - is refused by import (import_minted)

    There is no foreign key to Ark. The row it would reference is gone, and for the same
    reason as AuditEvent: a record should outlive what it is about, and referential
    integrity makes "the record cannot stay, so delete it too" the easy path.
    """

    __tablename__ = "withdrawn_name"

    ark: Mapped[str] = mapped_column(String(MAX_ARK_LENGTH), primary_key=True)
    naan: Mapped[str] = mapped_column(String(MAX_NAAN_LENGTH), index=True)
    assigned_name: Mapped[str] = mapped_column(String(MAX_NAME_LENGTH))

    #: Which namespace's capacity it used. A shoulder is never deleted, so this can be
    #: followed later.
    shoulder_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    #: Who minted it and when. Keeping only who withdrew it would lose who reserved
    #: it.
    minted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    minted_by: Mapped[str] = mapped_column(String(255), default="")

    #: Whether it had been published. null means it was withdrawn before publication;
    #: a value means a published name was purged (purge_ark), and the time says when it
    #: was out in the world.
    #:
    #: They share a table because the consequence is the same: the name is never minted
    #: again. Their meaning differs, though. The first happened outside the promise; the
    #: second broke it. Without telling them apart, nobody could count afterwards how
    #: often the promise was broken.
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    withdrawn_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    withdrawn_by: Mapped[str] = mapped_column(String(255), default="", index=True)
    #: Why it was withdrawn. Nothing here happens without a record: this is the only
    #: explanation left of a row that is gone.
    reason: Mapped[str] = mapped_column(String(500), default="")
    ip: Mapped[str] = mapped_column(String(45), default="")


# ------------------------------------------------------------- Deletion is refused
#
# Shoulders and published ARKs are not deleted.
#   deleting a published ARK  resolution stops, which breaks the identifier. Having
#                             declared NR, that is not allowed. When an object is gone,
#                             tombstone it or empty the url and return the description
#                             (FAIR A2)
#   a reserved ARK            can be deleted. A name that never went out is not what NR
#                             binds. The name moves to WithdrawnName and is never minted
#                             again (domain.admin_ops.withdraw_ark)
#   deleting a shoulder       random assignment could hand out the same string again,
#                             which is how an NR violation starts. When an organisation
#                             goes, the row stays and its status becomes retired. A
#                             shoulder that was delegated especially cannot go: an
#                             outside minter may have created identifiers we know
#                             nothing about
#
#   purging a published ARK   possible within the caller's reach, leaving a reason and
#                             the ARK typed again (domain.admin_ops.purge_ark). It is
#                             the way out for a legal removal order, or for something
#                             that should never have been published, and using it means
#                             the promise was broken. So there is one path, and it
#                             always leaves a trace: the audit log and WithdrawnName
#
# Rather than asking people to follow the rule, the ORM makes it impossible. A published
# row cannot be removed unless the session has named that ARK as one to purge, and only
# purge_ark makes that declaration.
#
# The mark lives on the session and applies to the one ARK it names, because a global
# flag gets left raised. Nobody checks that a flag is down, and it is noticed only after
# a row that should have stayed is gone.


class NotDeletable(RuntimeError):
    pass


#: The key in session.info: the ARK this session declared it would purge.
_PURGING = "arkhe_purging"


@contextmanager
def sanctioned_purge(session, ark: str):
    """Allow this one ARK to be purged, in this session only.

    Nothing but purge_ark uses it. The declaration is always cleared on the way out,
    including when an exception leaves the block: not staying raised is most of the
    value here.
    """
    before = session.info.get(_PURGING)
    session.info[_PURGING] = ark
    try:
        yield
    finally:
        if before is None:
            session.info.pop(_PURGING, None)
        else:  # pragma: no cover - no caller nests this
            session.info[_PURGING] = before


@event.listens_for(Ark, "before_delete")
def _no_published_ark_delete(mapper, connection, target):  # noqa: ARG001
    """An ARK that was ever published is not deleted. Only one that was named for
    purging gets through.

    It looks at first_published_at, whether it was ever public, rather than
    published_at, whether it is published now. Once publication became reversible,
    looking at the latter would let withdrawing and then deleting walk straight past
    this guard, and a guard that can be stepped around in one move is not a guard.
    """
    if target.first_published_at is None and target.published_at is None:
        return
    session = object_session(target)
    if session is not None and session.info.get(_PURGING) == target.ark:
        return  # a purge by the RA operator (admin_ops.purge_ark)
    raise NotDeletable(
        "a published ARK is not deleted: resolution would stop, which breaks the "
        "identifier. Tombstone it or empty the url. If it truly has to go, the RA "
        "operator purges it, which leaves a trace."
    )


@event.listens_for(Shoulder, "before_delete")
def _no_shoulder_delete(mapper, connection, target):  # noqa: ARG001
    raise NotDeletable(
        "a shoulder is not deleted: reusing a namespace violates NR. Set its status "
        "to retired instead."
    )
