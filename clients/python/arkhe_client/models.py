"""What comes back, as plain objects.

These mirror the ArkOut, BulkMintOut and DeleteOut schemas of the API. Each one keeps
the answer it was built from in .raw, so a field added to the server is reachable before
this client knows about it, and a check in the tests compares the fields here with the
published OpenAPI document so that the two cannot drift apart quietly.

Timestamps arrive as ISO 8601 strings and are turned into datetime objects. Everything
else is a string, empty when it was not set, exactly as the server has it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

#: The metadata an ARK carries. It is the same set on minting, importing, registering
#: and updating, which is why every one of those takes the same keywords.
FIELDS = (
    "url", "title", "type", "identifier", "format", "relation", "source",
    "commitment", "metadata", "who", "when",
)


def _moment(value: Any) -> datetime | None:
    """Read a timestamp, leaving anything unreadable as None rather than failing.

    A client that raises while reading a successful answer is worse than one that hands
    back the raw string: the write happened either way, and .raw still has it.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class Ark:
    """One ARK, as the API returns it.

    resent is not part of the answer body. It comes from the status code: 200 means the
    server recognised the request_id and returned the ARK it minted the first time, so
    nothing new was created. 201 means this call minted it.
    """

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
    published_at: datetime | None = None
    hold_until: datetime | None = None
    hold_reason: str = ""
    resent: bool = False
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def published(self) -> bool:
        """Whether it resolves. An ARK with no published_at is reserved: it exists and
        the name is taken, but it does not resolve yet and can still be deleted."""
        return self.published_at is not None

    @property
    def held(self) -> bool:
        """Whether redirection is being held. The ARK still resolves, to its
        description rather than to the target."""
        return self.hold_until is not None

    @classmethod
    def of(cls, data: dict, *, resent: bool = False) -> Ark:
        return cls(
            ark=data.get("ark", ""),
            **{f: data.get(f, "") or "" for f in FIELDS},
            created_at=_moment(data.get("created_at")),
            updated_at=_moment(data.get("updated_at")),
            published_at=_moment(data.get("published_at")),
            hold_until=_moment(data.get("hold_until")),
            hold_reason=data.get("hold_reason", "") or "",
            resent=resent,
            raw=data,
        )


@dataclass(frozen=True)
class BulkMint:
    """The answer to minting a batch.

    minted is in the order the rows were sent, with resends in their places, so a caller
    can line the results up against its input. created and replayed say how the batch
    split: created is what this call minted, replayed is what already existed under the
    same request_id.
    """

    minted: list[Ark]
    created: int
    replayed: int
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    def __len__(self) -> int:
        return len(self.minted)

    def __iter__(self):
        return iter(self.minted)

    @classmethod
    def of(cls, data: dict) -> BulkMint:
        return cls(
            minted=[Ark.of(x) for x in data.get("minted", [])],
            created=int(data.get("created", 0)),
            replayed=int(data.get("replayed", 0)),
            raw=data,
        )


@dataclass(frozen=True)
class Withdrawn:
    """What is left after delete or purge.

    The row is gone from the ledger; this is the record of its going. was_published_at
    is set by purge, which removes something that was published, and is None for a
    delete, which only removes what never was.
    """

    ark: str
    withdrawn_at: datetime | None = None
    reason: str = ""
    was_published_at: datetime | None = None
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def of(cls, data: dict) -> Withdrawn:
        return cls(
            ark=data.get("ark", ""),
            withdrawn_at=_moment(data.get("withdrawn_at")),
            reason=data.get("reason", "") or "",
            was_published_at=_moment(data.get("was_published_at")),
            raw=data,
        )
