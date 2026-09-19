"""Resolution: the only route a resolver process has. There is no minting and no admin
interface here.

domain.resolution.resolve() makes the decisions; this module shapes them into HTTP.
"""

from __future__ import annotations

import os
from dataclasses import replace
from http import HTTPStatus
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from arkhe import errors
from arkhe.api import i18n
from arkhe.arkspec.naming import ArkParseError, compact_ark, parse_ark
from arkhe.auth.deps import Config, Db
from arkhe.db.models import Manager, Naan, Shoulder, utcnow
from arkhe.db.repository import SqlArkRepository
from arkhe.domain.resolution import Inflection, Outcome, is_followable, resolve

router = APIRouter(tags=["resolve"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

#: The ERC code for a missing value. A blank is not acceptable: draft-kunze-erc-01
#: says to put a standard value that gives the reason. Left blank, "not filled in yet"
#: and "there is none" cannot be told apart. We cannot tell which it is, so (:unav) is
#: used throughout, which is more honest than claiming (:unas) or (:none).
UNAVAILABLE = "(:unav)"

DC_FIELDS = ("type", "identifier", "format", "relation", "source")

#: The header carrying the raw URI, used to detect a bare ?. Set it only when
#: something in front provides one.
RAW_URI_HEADER = os.environ.get("ARKHE_RAW_URI_HEADER", "")

#: The display name of a commitment level comes from ci.* in api/i18n, in the reader's
#: language: ?info is public, and ARKs are followed from anywhere.



# ------------------------------------------------ The wording in the document
#
# The published document and the docstrings have different readers: one is for whoever
# calls the API, the other for whoever reads the implementation. FastAPI prefers
# description over a docstring.

E_WELL_KNOWN = """\
**Tells a client that this host has an ARK resolver** (draft-kunze-ark-42 §5.6).

§5.6 registers `ark` in the Well-Known URIs registry (RFC 8615) and defines the answer
as **plain text holding the resolver's root path, ending in `/`** — append a compact ARK
to it and you have a resolution request. **A client that sends no `Accept`, or `*/*`,
gets that**; answering such a client with JSON would make the host look, to anyone
reading the specification, as though it had no ARK resolver at all.

`Accept: application/json` returns arkhe's own inventory instead: **where to go when a
NAAN's minting happens elsewhere** (`Naan.minter` / `Shoulder.minter`), **where resolution
has been delegated** (`redirect`), and any namespace whose redirection is on hold.

That list is also **what to watch from outside**. If a `minter` goes away, minting for
that namespace stops — bad, but survivable. **If a `redirect` goes away, every ARK under
it stops resolving**, and nothing here will tell you: arkhe answers with a redirect and
never fetches the target. Probe them from your monitoring, not from the ledger.

Both representations carry `Vary: Accept`.
"""

E_RESOLVE = """\
**Resolve an ARK. No authentication.** Both `ark:99999/x9tn1qkq2g7` and the older
`ark:/99999/x9tn1qkq2g7` are accepted, in any letter case.

There is more than one way to answer, and **keeping the identifier alive comes first on
every path**:

    302  redirect to the target (the usual case; a shoulder's delegation template may
         name 301, 303 or 307 instead)
    200  return a description — for `?info` and `??`, for a target a browser cannot
         open (`urn:isbn:…`), for an empty target, for a tombstone, and while a hold
         is on
    404  not in this ledger and nowhere to forward to. **`?info` on an unknown name is
         still a 404** — there is nothing to say about a name we do not know
    400  not readable as an ARK

**A hold is not a 404.** The identifier exists; we are only declining to hand out its
address for now, so the reason and the expiry come back with a 200. **The same holds for
a tombstone** — saying "it was lost" is not the same as saying "it never was".

An ARK that is only a NAAN (`ark:12345`) answers with what can be said about that NAAN.
An unknown NAAN is forwarded to the global resolver (`ARKHE_GLOBAL_RESOLVER`, n2t.net by
default).

Every answer this resolver gives about an identifier carries the THUMP headers of §5.2
(`THUMP-Status` and `Link: <…>; rel="describes"`); redirects carry neither.
"""


def _inflection(request: Request) -> Inflection:
    """Decide which inflection was asked for.

    | notation | query string | what is returned |
    | --- | --- | --- |
    | `?` | `""`, told apart by the raw URI | a brief description in ERC/ANVL |
    | `??` | `"?"` | the persistence statement (C4) |
    | `?info` | `"info"` | a description for people, which the specification requires |
    | `?json` | `"json"` | machine readable |

    A bare ? cannot be told from nothing by the query string alone: .../name? and
    .../name both leave it empty. ASGI is no different, and it cannot be recovered
    without a server that passes the raw URI, as gunicorn does with RAW_URI. The
    specification makes ? optional, so where it cannot be told apart it is treated as no
    inflection, and nothing breaks: ?? still works, because its query string is "?".

    Behind a server that does pass the raw URI, setting ARKHE_RAW_URI_HEADER to the
    header name picks ? up as well; with nginx, for instance, by setting X-Raw-URI.
    """
    # Only the first element counts. For ?info the query string itself is the
    # inflection, so switching language has to be written ?info&lang=en, and this reads
    # up to the &.
    qs = request.url.query.split("&", 1)[0]
    if qs == "?":
        return Inflection.POLICY
    if qs == "info":
        return Inflection.INFO
    if qs == "json":
        return Inflection.JSON
    if not qs:
        raw = request.headers.get(RAW_URI_HEADER, "") if RAW_URI_HEADER else ""
        if raw.endswith("?"):
            return Inflection.BRIEF
    return Inflection.NONE


def _raw_ark_path(request: Request) -> str:
    """Return the path with its percent encoding intact.

    A4. request.url.path, which is ASGI's scope["path"], has already been decoded by the
    server, so %2F arrives as / and %7D as }. Taking that at face value means:

    - x54%2Fc2, one name hiding a slash that is not a separator, becomes x54/c2, meaning
      c2 inside x54. That is a different identifier, and inheritance then follows another
      row's target
    - } is not in the character set of 3.1. %7D is the only legal way to carry it, so the
      decoded string is not a valid ARK at all
    - when handing on to another resolver, the rewritten ARK is what gets passed along

    draft-kunze-ark-42, 3.2 forbids exactly this: "no %-encoded character should ever
    appear in an ARK in its decoded form".

    ASGI keeps the raw path in scope["raw_path"], which is preferred here. Where
    something in front flattens it, it cannot be recovered: with nginx, do not write a
    path in proxy_pass, which re-encodes it; with Apache, AllowEncodedSlashes NoDecode
    is needed.
    """
    raw = request.scope.get("raw_path")
    if not raw:
        return request.url.path
    # Some servers include the query. Inside a name a ? is written %3F, so cutting at
    # a bare ? is safe.
    raw = raw.split(b"?", 1)[0]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        # The raw bytes are not UTF-8. Nothing is invented; it falls back to the
        # decoded path.
        return request.url.path


def _anvl(pairs) -> str:
    """The ERC/ANVL form, which is what ARKs have traditionally returned for ? and ??.

    Measured: n2t.net/ark:/13030/m5s75pdz?? answers text/plain with erc.who, erc.what
    and erc.when. It is not JSON.

    An element passed as an empty string is always printed as (:unav); one passed as
    None is left out entirely. Only the four kernel elements, who, what, when and where,
    require a code, and filling optional labels with (:unav) would claim ignorance about
    something that is known elsewhere.
    """
    lines = ["erc:"]
    for key, value in pairs:
        if value is None:
            continue
        text = str(value).strip() or UNAVAILABLE
        lines.append(f"{key}: " + text.replace("\n", "\n    "))
    return "\n".join(lines) + "\n"


#: C7: the THUMP version. The example response in draft-kunze-ark-42, 5.2 shows
#: THUMP-Status: 0.6 200 OK, and [THUMP] there refers to draft-kunze-thump-03.
THUMP_VERSION = "0.6"


def _thump(status: int, requested: str = "") -> dict[str, str]:
    """The THUMP response headers (5.2).

    C7. The example in the specification:

        S: THUMP-Status: 0.6 200 OK
        S: Link: </ark:67531/metadc107835> rel="describes";

    The specification explains what Link is for: telling a recipient that does not know
    about inflections that this response describes the unqualified ARK. Without it, the
    answer to ?info reads as a representation of that URL itself.

    The rel is not written as the example shows. The example has <...> rel="describes";
    while a link value in RFC 8288 is <URI>; rel="...", with the semicolon before it.
    The example is wrong, and emitting it would leave a standard Link parser unable to
    read it. Saying the same thing in a form that is understood is better than saying it
    in one that is not.
    """
    headers = {"THUMP-Status": f"{THUMP_VERSION} {status} {HTTPStatus(status).phrase}"}
    if requested:
        # A relative reference. It is the resolution path itself, so no host is needed (the NMA is
        # identity inert。§2.1）。
        headers["Link"] = f'</{compact_ark(requested)}>; rel="describes"'
    return headers


def _negotiate(accept: str, offers: tuple[str, ...]) -> str:
    """Choose one media type from Accept. A tie goes to the first of offers.

    It looks at the q value and at how specific the type is (text/plain over text/* over
    */*). With no header, an empty one, or */*, it falls back to the first offer, so the
    caller puts the representation the specification defines first.
    """
    best = dict.fromkeys(offers, 0.0)
    for part in accept.split(","):
        media, _, params = part.strip().partition(";")
        media = media.strip().lower()
        if not media:
            continue
        q = 1.0
        for param in params.split(";"):
            key, _, value = param.partition("=")
            if key.strip().lower() == "q":
                try:
                    q = float(value.strip())
                except ValueError:
                    q = 0.0
        for offer in offers:
            kind = offer.split("/")[0]
            if media in (offer, f"{kind}/*", "*/*"):
                best[offer] = max(best[offer], q)
    # max keeps the first of equals, so the order of offers is the order of
    # preference.
    chosen = max(offers, key=lambda o: best[o])
    return chosen if best[chosen] > 0 else offers[0]


#: What /.well-known/ark can return, with text/plain first: that is what the
#: specification defines, and it is what a caller sending no Accept, such as curl or a
#: discovery client, receives.
WELL_KNOWN_OFFERS = ("text/plain", "application/json")

#: What ?info can return, with html first: ?info is for people, and it is what a
#: browser or curl receives when no Accept is sent.
#:
#: draft-kunze-ark-42, 5.2: "THUMP is designed so that the response
#: (**indicated by the returned HTTP content type**) is normally displayed, whether the
#: output is structured for machine processing (text/plain) or formatted for human
#: consumption (text/html)." Varying by media type is what the specification
#: intends.
#:
#: The content is the same each time, a description with the persistence statement
#: (5: ?info returns the description and the permanence together). ?json remains as
#: another way of naming that JSON.
INFO_OFFERS = ("text/html", "application/json", "text/plain")


def _resolver_path(request: Request) -> str:
    """The root path of the ARK resolver on this host. It always ends in a slash.

    The ARK routes sit directly under the app (/ark:...), so with nothing stripping a
    prefix in front this is /. When mounted under a prefix, set the ASGI root_path
    (--root-path with uvicorn): that value is what this answers, so forgetting it points
    callers at the wrong place.
    """
    root = "/" + (request.scope.get("root_path") or "").strip("/")
    return root if root.endswith("/") else root + "/"


def _erc(session, res, t) -> dict:
    ark = res.ark
    manager = None
    if ark.shoulder is not None and ark.shoulder.manager_id:
        manager = session.get(Manager, ark.shoulder.manager_id)
    naan = session.get(Naan, ark.naan)
    return {
        "ark": compact_ark(res.requested),
        "who": ark.who,
        "what": ark.title,
        "when": ark.when,
        # C6: where is the ARK, not the target.
        #
        # draft-kunze-ark-42, 5.1.2: "A description must at a minimum answer
        # the who, what, when, and where questions (**"where" being the long-term
        # identifier as opposed to a transient redirect target**)".
        #
        # This used to hold the target URL, with the ARK as a fallback when there was
        # none, which is the wrong way round. A description answers what this identifier
        # names, so unless the value survives a change of target it cannot be cited.
        #
        # Not a mapping ARK with a host. Depending on what rewrites requests in front,
        # that could burn an internal host name into a public description, and the
        # compact ARK is a complete long-term identifier on its own (the NMA is identity
        # inert, 2.1).
        "where": compact_ark(res.requested),
        # The target is not thrown away; it goes in its own element, outside the
        # kernel, because it says where something is now rather than what it is.
        "redirect": ark.url + res.suffix if ark.url else "",
        # Whether it may be linked travels with the value. Deciding that in a template
        # would be forgotten the next time a page is added. Registering it is not
        # prevented; whether a browser is sent there is another question.
        "redirect_safe": is_followable(ark.url),
        **{f: getattr(ark, f) for f in DC_FIELDS},
        "commitment_level": manager.commitment_level if manager else "",
        # permanent-dynamic on its own means nothing to a reader, so a readable name
        # goes with it, in the reader's language (ci.*). An unknown value is returned
        # unchanged by the translator.
        "commitment_label": t(f"ci.{manager.commitment_level}") if manager else "",
        "na_policy": naan.na_policy if naan else "",  # the NAA policy, per NAAN
        "inherited_from": compact_ark(res.inherited_from) if res.inherited_from else "",
        "suffix": res.suffix,
        "created_at": ark.created_at.isoformat() if ark.created_at else "",
        "updated_at": ark.updated_at.isoformat() if ark.updated_at else "",
    }


_WELL_KNOWN_RESPONSES = {
    200: {
        "description": (
            "`text/plain` by default: the resolver's root path, one line "
            "(draft-kunze-ark-42 §5.6). `Accept: application/json` returns the "
            "namespaces this ledger holds."
        ),
        "content": {
            "text/plain": {"schema": {"type": "string"}},
            "application/json": {"schema": {"type": "object"}},
        },
    },
}


@router.get("/.well-known/ark", responses=_WELL_KNOWN_RESPONSES, description=E_WELL_KNOWN)
def well_known_ark(request: Request, session: Db, cfg: Config):
    """The endpoint that says an ARK resolver lives on this host
    (draft-kunze-ark-42, 5.6).

    Version 42 registers ark in the Well-Known URIs registry (RFC 8615) and defines the
    answer as plain text containing the resolver's root path, ending in a slash. A caller
    that sends no Accept gets exactly that: answering */* with JSON makes a discovery
    client that follows the specification conclude this is not an ARK resolver.

    Only with Accept: application/json does it return arkhe's own inventory: where a
    client should go when minting for a NAAN is delegated (Naan.minter and
    Shoulder.minter), where resolution is delegated to (redirect), and which namespaces
    are held.

    That list is also the list of things to watch from outside. If a minter disappears,
    minting for that namespace stops, which is bad but survivable. If a redirect
    disappears, every ARK under it stops resolving, and arkhe does not know: it returns
    a redirect without ever fetching the target.

    One URL with two representations, so both carry Vary: Accept.
    """
    vary = {"Vary": "Accept"}
    if _negotiate(request.headers.get("accept", ""), WELL_KNOWN_OFFERS) == "text/plain":
        # It ends with a newline: the specification calls it a plain text file and
        # writes the example as one line. Readers should strip surrounding whitespace.
        return PlainTextResponse(
            _resolver_path(request) + "\n",
            media_type="text/plain; charset=utf-8",
            headers=vary,
        )

    naans = session.scalars(select(Naan).order_by(Naan.naan)).all()
    return JSONResponse(
        headers=vary,
        content={
            # The value the specification defines is in the JSON too, so one of the
            # two is enough.
            "resolver_path": _resolver_path(request),
            "resolver": "arkhe",
            "global_resolver": cfg.global_resolver,
            "naans": [
                {
                    "naan": n.naan,
                    "authoritative": n.is_authoritative,
                    "redirect": n.redirect or None,
                    "minter": n.minter or None,
                    "na_policy": n.na_policy or None,
                }
                for n in naans
            ],
            # minter holds only an endpoint a machine can call; guidance for people
            # goes in about. Under one key, a reader could not tell them apart.
            #
            # redirect, where resolution is delegated, is listed too, because the
            # consequences are the other way round: if a minter dies only minting
            # stops, while if a redirect dies every ARK in that shoulder stops
            # resolving. What monitoring should watch first cannot be watched if it is
            # not listed.
            #
            # status is included: a redirect on a delegated shoulder and one on a
            # shoulder we still mint from mean different things when they fail.
            "delegated_shoulders": [
                {
                    "shoulder": f"{s.naan}{s.shoulder}",
                    "status": s.status,
                    "minter": s.minter or None,
                    "about": s.about or None,
                    "redirect": s.redirect or None,
                }
                for s in session.scalars(
                    # Both the delegated ones and those whose resolution is
                    # delegated. redirect can be set independently of status, so
                    # listing only the delegated ones would drop a shoulder that still
                    # mints here while resolving elsewhere.
                    select(Shoulder)
                    .where((Shoulder.status == "delegated") | (Shoulder.redirect != ""))
                    .order_by(Shoulder.naan, Shoulder.shoulder)
                ).all()
            ],
            # Namespaces whose redirection is held are published. In a federated
            # setup, each level has to be able to check mechanically what the other
            # has stopped.
            "held": [
                {
                    "scope": scope,
                    "target": target(row),
                    "until": row.hold_until.isoformat(),
                    "reason": row.hold_reason,
                }
                for scope, model, target in (
                    ("naan", Naan, lambda r: r.naan),
                    ("shoulder", Shoulder, lambda r: f"{r.naan}{r.shoulder}"),
                )
                for row in session.scalars(
                    select(model).where(model.hold_until > utcnow())
                ).all()
            ],
        }
    )


_TEXT = {"text/plain": {"schema": {"type": "string"}}}

#: This route does more than redirect. Without saying so, a generated client is built
#: expecting only a 200 with JSON and treats a redirect, a description and a 404 as
#: errors.
#:
#: There is more than one media type, too. Within the same 200, ?json and a NAAN-only
#: ARK return JSON, ? and ?? and a hold return ANVL (text/plain), and ?info returns HTML
#: for people. There are four 3xx codes because a shoulder's delegation template can
#: name one (_STATUS_PREFIX; following n2t, only 301, 302, 303 and 307 are accepted).
_RESOLVE_RESPONSES = {
    200: {
        "description": (
            "a description (`?info` / `?` / `??` / `?json`, a target that cannot be "
            "opened, a tombstone, a hold, an ARK that is only a NAAN)"
        ),
        "content": {
            "application/json": {"schema": {"type": "object"}},
            "text/plain": {"schema": {"type": "string"}},   # ANVL
            "text/html": {"schema": {"type": "string"}},
        },
    },
    301: {"description": "redirect to the target (a delegation template named `301 `)"},
    302: {"description": "redirect to the target (the default)"},
    303: {"description": "redirect to the target (a delegation template named `303 `)"},
    307: {"description": "redirect to the target (a delegation template named `307 `)"},
    400: {"description": "not readable as an ARK", "content": _TEXT},
    404: {"description": "not in this ledger, and nowhere to forward to", "content": _TEXT},
}


@router.get("/ark:/{rest:path}", responses=_RESOLVE_RESPONSES, description=E_RESOLVE)
@router.get("/ark:{rest:path}", responses=_RESOLVE_RESPONSES, description=E_RESOLVE)
def resolve_ark(rest: str, request: Request, session: Db, cfg: Config):
    """Resolve an ARK. No credentials are needed, and both ark:/99999/x9tn1qkq2g7 and
    ark:99999/x9tn1qkq2g7 are accepted.

    There is more than one way to answer, and every path puts keeping the identifier
    alive first:

      302  redirect to the target (the usual case; 301, 303 or 307 when a shoulder's
           delegation template names one)
      200  return a description: with ?info or ??, when the target is something a
           browser cannot open such as urn:isbn:..., when there is no target, for a
           tombstone, and while a hold is in force
      404  not in this ledger and nothing to hand it on to. ?info does not change that:
           there is nothing to say about a name we do not know
      400  a string that cannot be read as an ARK

    A hold is not a 404. The identifier exists and we are simply not redirecting right
    now, so it answers 200 with the reason and the expiry. A tombstone is the same:
    saying something is gone is not the same as saying it never existed.

    An ARK that is only a NAAN (ark:12345) is answered with what can be said about that
    NAAN. One we do not know is handed on to the resolver above (ARKHE_GLOBAL_RESOLVER,
    n2t.net by default).
    """
    # A4: the decoded path is not used. %2F turning into / makes a different
    # identifier.
    raw = _raw_ark_path(request)
    try:
        parsed = parse_ark(raw.lstrip("/"), allow_naan_only=True)  # D4
    except ArkParseError as exc:
        # The code goes first. Resolution answers in text/plain, which people read
        # too, and the start of the line is the easiest place for a machine to find.
        return PlainTextResponse(
            f"{errors.ARK_UNREADABLE.number} {errors.ARK_UNREADABLE.say(reason=exc)}\n",
            status_code=400,
            headers=_thump(400),
        )

    if not parsed.name:
        # D4: an ARK that is only a NAAN. Answer with what can be said about it.
        naan = session.get(Naan, parsed.naan)
        if naan is None:
            return RedirectResponse(
                f"{cfg.global_resolver.rstrip('/')}/{compact_ark(parsed.naan)}", status_code=302
            )
        return JSONResponse(
            {"naan": naan.naan, "name": naan.name, "na_policy": naan.na_policy,
             "authoritative": naan.is_authoritative, "minter": naan.minter}
        )

    res = resolve(
        SqlArkRepository(session, unpublished=cfg.resolve_unpublished),
        parsed.naan,
        parsed.name,
        _inflection(request),
        global_resolver=cfg.global_resolver,
        # A closed resolver serves reserved ARKs too (ARKHE_RESOLVE_UNPUBLISHED). The
        # flag goes to both the repository and the decision logic: with it in only one,
        # substituting the repository would change the decision.
        unpublished=cfg.resolve_unpublished,
    )

    # A browser is only sent somewhere it can open. A valid target such as
    # urn:isbn:... is described instead of redirected to, which is not a restriction but
    # what ?info has always been for. FORWARD, handing on to another resolver, is always
    # http.
    if res.outcome is Outcome.REDIRECT and not is_followable(res.location):
        res = replace(res, outcome=Outcome.DESCRIBE, status=200)

    if res.outcome in (Outcome.REDIRECT, Outcome.FORWARD):
        # C2: ?? is not appended to the target URL. A redirect leads to the object,
        # while an inflection is a question asked of this resolver.
        return RedirectResponse(res.location, status_code=res.status)

    if res.outcome is Outcome.HELD:
        # Not a 404: the namespace exists and we are simply not forwarding right now.
        # With no row there is no description, but the reason and the expiry are given,
        # which beats stopping silently.
        return PlainTextResponse(
            _anvl(
                [
                    ("where", compact_ark(res.requested)),
                    ("hold", res.hold.reason if res.hold else ""),
                    ("hold-until", res.hold.until.isoformat() if res.hold else ""),
                    ("hold-scope", res.hold.scope if res.hold else ""),
                ]
            ),
            media_type="text/plain; charset=utf-8",
            headers=_thump(200, res.requested),
        )

    if res.outcome is Outcome.NOT_FOUND:
        code = res.code or errors.ARK_UNKNOWN_NAME
        return PlainTextResponse(
            f"{code.number} {compact_ark(res.requested)} — {res.reason}\n",
            status_code=404,
            headers=_thump(404, res.requested),
        )

    # The wording around a description follows the reader's language. ?info is public,
    # so Accept-Language and ?info&lang= are read, in the same order as the screens.
    lang = i18n.pick(request)
    erc = _erc(session, res, i18n.translator(lang))
    kernel = [
        ("who", erc["who"]),
        ("what", erc["what"]),
        ("when", erc["when"]),
        ("where", erc["where"]),
    ]

    if res.inflection is Inflection.BRIEF:
        # ? returns the four ERC elements briefly. It can be answered even when the
        # object cannot be reached (FAIR A2). The target goes outside the kernel, and
        # only when there is one.
        return PlainTextResponse(
            _anvl([*kernel, ("redirect", erc["redirect"] or None)]),
            media_type="text/plain; charset=utf-8",
            headers=_thump(200, res.requested),
        )

    def _as_json():
        return JSONResponse(
            headers={**_thump(200, res.requested), "Vary": "Accept, Accept-Language"},
            content={
                **erc,
                "commitment": res.ark.commitment,
                # A hold is not hidden, and it is given in a form a machine reads.
                "hold": res.hold.as_dict() if res.hold else None,
            },
        )

    def _as_anvl():
        # What ?? contains. The text/plain of ?info is the same thing: a description
        # with the persistence statement, differing only in media type (5).
        return PlainTextResponse(
            _anvl(
                [
                    *kernel,
                    ("redirect", erc["redirect"] or None),
                    ("about", erc["ark"]),
                    # The NAA policy: what is promised about the namespace, per NAAN
                    ("policy", erc["na_policy"]),
                    # The NMA commitment: what is promised about this object. When it
                    # is empty the line is left out; (:unav) would read as "our promise
                    # is unknown", while the promise is stated below in
                    # commitment-level.
                    ("commitment", res.ark.commitment or None),
                    ("commitment-level", erc["commitment_level"]),
                    # A hold belongs to the promise. ?? answers how this identifier
                    # is kept, so the fact that it is not being redirected right now
                    # belongs here.
                    ("hold", res.hold.reason if res.hold else None),
                    ("hold-until", res.hold.until.isoformat() if res.hold else None),
                    ("inherited-from", erc["inherited_from"] or None),
                ]
            ),
            media_type="text/plain; charset=utf-8",
            headers=_thump(200, res.requested),
        )

    def _as_html():
        return templates.TemplateResponse(
            request,
            "info.html",
            {
                "erc": erc, "res": res,
                "hold": res.hold.as_dict() if res.hold else None,
                "t": i18n.translator(lang), "lang": lang, "langs": i18n.LANGS,
            },
            headers={**_thump(200, res.requested), "Vary": "Accept, Accept-Language"},
        )

    if res.inflection is Inflection.JSON:
        # ?json is another way of naming the JSON that ?info returns. It is not part
        # of the specification's vocabulary, so it is kept, and sending ?info with
        # Accept: application/json returns the same thing.
        return _as_json()

    if res.inflection is Inflection.POLICY:
        # ?? is what ? returns plus the persistence statement (C4).
        #   draft-kunze-ark-42        … "'?' (brief metadata) and '??' (more metadata)"
        #   arks.org/about/ark-features … "a maintenance commitment from the current server"
        # Reading "more" as the commitment reconciles the two, and the form follows
        # ANVL as well.
        return _as_anvl()

    # ?info, and a description with no inflection (a tombstone, a hold, no target).
    # It varies by media type, as the specification says the shape of the response is
    # indicated by the content type, while the content is the same description with the
    # persistence statement. A caller that sends no Accept gets the HTML for people.
    chosen = _negotiate(request.headers.get("accept", ""), INFO_OFFERS)
    if chosen == "application/json":
        return _as_json()
    if chosen == "text/plain":
        return _as_anvl()
    return _as_html()

