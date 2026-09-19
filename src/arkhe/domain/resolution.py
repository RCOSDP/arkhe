"""The decision logic of resolution, kept away from HTTP so that it can be verified on
its own.

It reads as one flow (arklet_ark_conformance.md, 7-1):

    normalise (A1, N4)
      then an exact match (a public resolver serves only what is published; a closed
        one answers for reserved ARKs too)
      then inheritance from an ancestor (D5, D6, B3)
      then the check digit (D1, only for a NAAN we are authoritative for)
      then the shoulder's redirect
      then 404 for our own NAAN (D3), the NAAN's redirect for another, or n2t for one
        we do not know (D2)

Acceptance criteria: D1, D2, D3, D5, D6, B3, C5, N4, A2, SC1
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from urllib.parse import urlsplit

from arkhe import errors
from arkhe.arkspec.betanumeric import verify_ark_check_digit
from arkhe.arkspec.naming import (
    QUALIFIER_SEPARATORS,
    ark_key,
    compact_ark,
    gen_prefixes,
    is_structural_at,
    normalize_percent,
    normalize_structural,
    split_after_normalized,
    strip_hyphens,
)
from arkhe.arkspec.shoulder import split_shoulder

#: D2: where an unknown NAAN is forwarded. It is configurable.
#: The schemes that are dangerous for a browser to interpret. They are the only reason
#: registration is ever refused.
#:
#: ?info is a public page that needs no credentials, so if whoever minted an ARK could
#: choose any string on it, they could make other people run script on the resolver's
#: origin.
#:
#: A list of what is refused is enough because urlsplit absorbs the spelling: mixed
#: case, leading whitespace, and tabs, newlines or NULs in the middle all normalise to
#: the same scheme, as a browser would treat them. Comparing raw strings would need a
#: list of what is allowed; comparing after parsing can be enumerated.
DANGEROUS_SCHEMES = frozenset({"javascript", "data", "vbscript", "blob", "filesystem"})

#: The schemes a browser may be sent to. Anything else is neither linked nor redirected
#: to, but registering it is not prevented.
FOLLOWABLE_SCHEMES = frozenset({"http", "https"})


def _scheme(url: str) -> str:
    try:
        return urlsplit(url.strip()).scheme.lower()
    except ValueError:
        return "?"


def is_registrable(url: str) -> bool:
    """Whether this may be stored as a target.

    An ARK can name a physical object or another identifier. The target is a URI, not
    necessarily an HTTP URL, so urn:, doi:, ark: and mailto: must all be accepted, and
    empty is valid too: an object with no target is a central use.

    Only what is dangerous for a browser to interpret is refused.
    """
    return not url or _scheme(url) not in DANGEROUS_SCHEMES


def is_followable(url: str) -> bool:
    """Whether a browser may be redirected there, or a link made to it.

    urn:isbn:... is a valid target but not one to redirect to, because a browser cannot
    open it. Such an ARK is described instead, which is not a restriction: it is what
    ?info has always been for.
    """
    return bool(url) and _scheme(url) in FOLLOWABLE_SCHEMES


DEFAULT_GLOBAL_RESOLVER = "https://n2t.net"


class Inflection(Enum):
    """A query beginning with ?. The specification requires only ?info (C1,
    corrected)."""

    NONE = "none"
    BRIEF = "brief"  # ?      a brief description in ERC/ANVL
    INFO = "info"  # ?info  a description for people (required)
    JSON = "json"  # ?json  machine readable, an extension from arklet
    POLICY = "policy"  # ??     the persistence statement (C4)

    @property
    def wants_metadata(self) -> bool:
        return self is not Inflection.NONE


class Outcome(Enum):
    REDIRECT = "redirect"  # redirect with 302 or 303
    DESCRIBE = "describe"  # the resolver returns the description itself
    NOT_FOUND = "not_found"
    FORWARD = "forward"  # hand on to another NAAN, or to one we do not know
    HELD = "held"  # redirection is held. The identifier is alive


@dataclass(frozen=True)
class Hold:
    """A hold in force. It stops redirection, not resolution.

    scope says which level holds it: ark, shoulder or naan. Knowing that, a reader can
    tell whether this one ARK is the problem or a whole namespace is stopped.
    """

    scope: str
    reason: str = ""
    until: datetime | None = None

    def as_dict(self) -> dict:
        return {
            "scope": self.scope,
            "reason": self.reason,
            "until": self.until.isoformat() if self.until else "",
        }


def _aware(value):
    """Treat a naive datetime as UTC.

    SQLite drops the time zone, and comparing a naive value with an aware one raises
    TypeError, so only the hold check would fail. Redirecting something that was meant
    to be held is far worse than being lenient here.
    """
    if value is None or not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def hold_of(obj, scope: str, now: datetime) -> Hold | None:
    """Return a Hold if that row is held right now.

    Nothing puts expired holds back. The clock is read here on each resolution, so
    nobody has to remember to lift one: a hold may be forgotten, but an expiry is never
    missed.
    """
    until = _aware(getattr(obj, "hold_until", None))
    if until is None or until <= now:
        return None
    return Hold(scope=scope, reason=getattr(obj, "hold_reason", "") or "", until=until)


def effective_hold(now: datetime, *pairs) -> Hold | None:
    """Look at each (row, scope) from the narrowest outwards and return the first hold
    in force.

    The narrowest comes first because the reason for holding one ARK is more specific.
    """
    for obj, scope in pairs:
        if obj is None:
            continue
        found = hold_of(obj, scope, now)
        if found is not None:
            return found
    return None


@dataclass
class Resolution:
    outcome: Outcome
    status: int = 302
    location: str = ""
    #: The Ark the description comes from, which may be an ancestor.
    ark: object | None = None
    #: The ARK that was asked for (naan/name): the name used when inheriting.
    requested: str = ""
    #: The qualifier, cut from the ancestor.
    suffix: str = ""
    #: When inheriting, which ARK it was inherited from (C5).
    inherited_from: str = ""
    inflection: Inflection = Inflection.NONE
    reason: str = ""
    #: The code (arkhe.errors.Code). Callers branch on it rather than on the wording.
    code: object | None = None
    detail: dict = field(default_factory=dict)
    #: The hold in force, carried so that the reason redirection stopped appears in
    #: the response.
    hold: Hold | None = None


#: Anything without a published_at, such as a fake repository in a test, counts as
#: published. Being reserved is something the ledger states, not something the absence
#: of an attribute decides.
_ASSUME_PUBLIC = object()


def is_public(ark) -> bool:
    """Whether this ARK has been published to the world."""
    return getattr(ark, "published_at", _ASSUME_PUBLIC) is not None


def serves(ark, *, unpublished: bool) -> bool:
    """Whether this resolver may answer for this row.

    Whether a reserved ARK resolves does not follow from the state of the ARK alone; it
    follows from which resolver is answering:

      a closed resolver  serves its own reserved ARKs (unpublished=True)
      a public resolver  serves only what is published, treating a reserved ARK as a
                         name that does not exist, including as an ancestor

    If ARKs minted inside a closed network do not resolve there, handing out identifiers
    for closed objects is pointless. Meanwhile the public endpoints (?info and ??) need
    no credentials, so serving a reserved ARK there would expose the existence, the
    title and the target of something unpublished. One decision, placed differently.
    """
    return unpublished or is_public(ark)


def base_name(name: str) -> str:
    """Return the base name, up to the qualifier.

    N7: the check digit is computed over the base compact name and excludes any
    qualifier.
    """
    for i, char in enumerate(name):
        if char in QUALIFIER_SEPARATORS and is_structural_at(name, i):
            return name[:i]
    return name


_TEMPLATE = re.compile(r"\$\{blade\}|\$id")
_STATUS_PREFIX = re.compile(r"^(30[1237])\s+")


def expand_redirect(template: str, naan: str, name: str) -> tuple[int, str]:
    """Expand a template, compatible with n2t.

    | notation | replaced with |
    | --- | --- |
    | `$id` | `<naan>/<name>`, including any qualifier |
    | `${blade}` | everything after the shoulder |
    | a leading `303 ` and the like | the status code to use |

    ${nlid} is not supported: it is n2t's internal normalised id, with nothing here
    that corresponds to it.
    """
    status = 302
    m = _STATUS_PREFIX.match(template)
    if m:
        status = int(m.group(1))
        template = template[m.end() :]
    blade = split_shoulder(name)[1]
    expanded = _TEMPLATE.sub(
        lambda mo: blade if mo.group(0) == "${blade}" else f"{naan}/{name}", template
    )
    return status, expanded


class ArkRepository:
    """The few queries resolution needs, and nothing else.

    It can be substituted in the tests, which keeps the decision logic independent of
    any database.
    """

    def get_ark(self, key: str):  # pragma: no cover - implemented in db.repository
        raise NotImplementedError

    def get_arks(self, keys: list[str]) -> dict:  # pragma: no cover
        raise NotImplementedError

    def get_naan(self, naan: str):  # pragma: no cover
        raise NotImplementedError

    def get_shoulder(self, naan: str, shoulder: str):  # pragma: no cover
        raise NotImplementedError


def resolve(
    repo: ArkRepository,
    naan: str,
    name: str,
    inflection: Inflection = Inflection.NONE,
    *,
    global_resolver: str = DEFAULT_GLOBAL_RESOLVER,
    now: datetime | None = None,
    unpublished: bool = False,
) -> Resolution:
    """Resolve an ARK.

    now is used only to judge holds. It is an argument for the tests; without it, the
    current time is read.

    unpublished says whether this resolver is inside a closed network (see serves). The
    default is a public resolver, where a reserved ARK is treated as a name that does
    not exist.
    """
    now = now or datetime.now(UTC)
    # A4: percent encoding is not decoded; only the hex case is normalised (step 5).
    # %2F is the only way to write a slash that is not a separator, and decoding it
    # would make a different identifier: x54%2Fc2 and x54/c2 are not the same.
    name = normalize_percent(name)
    name = normalize_structural(name)  # N4
    normalized = strip_hyphens(name)  # A2
    requested = ark_key(naan, name)

    # --- An exact match ------------------------------------------------------
    # Try the stored spelling first, so that older rows containing hyphens still
    # match.
    for key in dict.fromkeys([ark_key(naan, name), ark_key(naan, normalized)]):
        ark = repo.get_ark(key)
        # On a public resolver a reserved ARK is a name that does not exist yet.
        # Answering 200 for a number that was only reserved would reveal that something
        # unpublished exists, and describe it. A closed resolver does answer: it is
        # inside the network the name was handed out in.
        if ark is not None and serves(ark, unpublished=unpublished):
            return _deliver(ark, requested=requested, inflection=inflection, now=now)

    # --- Inheriting from an ancestor (D5: the longest match) -----------------
    candidates = list(gen_prefixes(normalized))  # longest first
    if candidates:
        # SC1: no sorting by a function in the database. There are at most as many
        # candidates as the name is long, so they are fetched with one IN and the first
        # match is taken here, in the order gen_prefixes returns them.
        found = repo.get_arks([ark_key(naan, c) for c in candidates])
        for cand in candidates:
            ancestor = found.get(ark_key(naan, cand))
            if ancestor is None or not serves(ancestor, unpublished=unpublished):
                continue
            _, suffix = split_after_normalized(name, len(cand))
            return _deliver(
                ancestor,
                requested=requested,
                inflection=inflection,
                suffix=suffix,
                inherited_from=ark_key(naan, cand),
                now=now,
            )

    # --- From here on, nothing is registered ---------------------------------
    naan_obj = repo.get_naan(naan)

    if naan_obj is None:
        # D2: an unknown NAAN is handed on to the global resolver (SHOULD).
        if inflection.wants_metadata:
            return Resolution(
                Outcome.NOT_FOUND,
                status=404,
                requested=requested,
                inflection=inflection,
                code=errors.NO_METADATA_FOR_UNKNOWN_NAAN,
                reason=errors.NO_METADATA_FOR_UNKNOWN_NAAN.message,
            )
        return Resolution(
            Outcome.FORWARD,
            status=302,
            location=f"{global_resolver.rstrip('/')}/{compact_ark(requested)}",
            requested=requested,
            reason="unknown NAAN forwarded to the global resolver",
        )

    if naan_obj.is_authoritative:
        # D1: the check digit is verified only for a NAAN we are authoritative for.
        # Another NAAN does not necessarily use check digits at all.
        stem = base_name(normalized)
        if not verify_ark_check_digit(naan, stem):
            return Resolution(
                Outcome.NOT_FOUND,
                status=404,
                requested=requested,
                inflection=inflection,
                code=errors.CHECK_DIGIT_MISMATCH,
                reason=errors.CHECK_DIGIT_MISMATCH.message,
                detail={"base": stem},
            )

        # Resolution delegated per shoulder, as in n2t's data model.
        shoulder_part = split_shoulder(stem)[0]
        if shoulder_part:
            shoulder = repo.get_shoulder(naan, f"/{shoulder_part}")
            if shoulder is not None and shoulder.redirect:
                # This is the only place a delegate can be stopped. The name is not
                # in our ledger, so the decision can only live on the shoulder or the
                # NAAN.
                held = effective_hold(now, (shoulder, "shoulder"), (naan_obj, "naan"))
                if held is not None:
                    return _held(requested, inflection, held)
                status, location = expand_redirect(shoulder.redirect, naan, name)
                return Resolution(
                    Outcome.REDIRECT,
                    status=status,
                    location=location,
                    requested=requested,
                    reason="delegated by shoulder",
                )

        # D3: for a NAAN we are authoritative for, an unknown name really is absent.
        return Resolution(
            Outcome.NOT_FOUND,
            status=404,
            requested=requested,
            inflection=inflection,
            code=errors.ARK_UNKNOWN_NAME,
            reason=errors.ARK_UNKNOWN_NAME.message,
        )

    # Another NAAN goes to its registered delegate, and a whole NAAN can be held.
    held = effective_hold(now, (naan_obj, "naan"))
    if held is not None:
        return _held(requested, inflection, held)
    return Resolution(
        Outcome.FORWARD,
        status=302,
        location=f"{naan_obj.redirect.rstrip('/')}/{compact_ark(requested)}",
        requested=requested,
        reason="delegated by NAAN registration",
    )


def _held(requested: str, inflection: Inflection, held: Hold) -> Resolution:
    """The answer when something is held with no row in the ledger, at shoulder or
    NAAN level.

    It is not a 404: the namespace exists, and we are simply not forwarding right now.
    """
    return Resolution(
        Outcome.HELD,
        status=200,
        requested=requested,
        inflection=inflection,
        reason="redirection is on hold",
        hold=held,
    )


def _deliver(
    ark,
    *,
    requested: str,
    inflection: Inflection,
    suffix: str = "",
    inherited_from: str = "",
    now: datetime | None = None,
) -> Resolution:
    """Decide how to answer for the ARK that was found, itself or an ancestor."""
    now = now or datetime.now(UTC)
    # Look at the ARK, then its shoulder, then its NAAN: the narrower reason is more
    # specific. The relationships are followed, not queried: the repository loaded them
    # on the same query.
    shoulder = getattr(ark, "shoulder", None)
    held = effective_hold(
        now,
        (ark, "ark"),
        (shoulder, "shoulder"),
        (getattr(shoulder, "naan_obj", None), "naan"),
    )
    if held is not None:
        # Only redirection stops. The description keeps coming back: the identifier
        # is alive.
        return Resolution(
            Outcome.DESCRIBE,
            status=200,
            ark=ark,
            requested=requested,
            suffix=suffix,
            inherited_from=inherited_from,
            inflection=inflection,
            reason="redirection is on hold",
            hold=held,
        )
    if inflection.wants_metadata:
        # C5: an inflection survives inheritance. The metadata of the nearest
        # registered ancestor is returned under the name that was asked for (FAIR A2).
        return Resolution(
            Outcome.DESCRIBE,
            status=200,
            ark=ark,
            requested=requested,
            suffix=suffix,
            inherited_from=inherited_from,
            inflection=inflection,
        )
    if not ark.url:
        # D6: with no target, do not redirect to a bare suffix; return the
        # description. For a physical object this is the usual answer.
        return Resolution(
            Outcome.DESCRIBE,
            status=200,
            ark=ark,
            requested=requested,
            suffix=suffix,
            inherited_from=inherited_from,
        )
    return Resolution(
        Outcome.REDIRECT,
        status=302,
        location=f"{ark.url}{suffix}",
        ark=ark,
        requested=requested,
        suffix=suffix,
        inherited_from=inherited_from,
    )
