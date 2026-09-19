"""Check this client against the API document, so that the two cannot drift apart.

The OpenAPI documents are generated from the server's implementation and committed, and
check.sh fails when they differ from what the code would produce. That makes them the
one description of the interface. This file compares the client with them, which is why
the client is written by hand rather than generated: what a generator gives is coverage,
and coverage is the part that can be checked.

An endpoint added to the server with nothing here to call it fails this file, which is
the moment to decide whether the client should carry it.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from arkhe_client import Arkhe, Resolver
from arkhe_client.models import FIELDS, Ark

#: This client lives beside the server it speaks to, so the documents are two
#: directories up. Moving it out means bringing them along: without them nothing here
#: can be checked, and the coverage check is the reason the client can be hand-written.
DOCS = Path(__file__).resolve().parents[3] / "docs" / "assets"


def load(name: str) -> dict:
    path = DOCS / name
    assert path.exists(), (
        f"{path} is missing. The OpenAPI documents are what this client is checked "
        "against; without them there is nothing to check."
    )
    return json.loads(path.read_text(encoding="utf-8"))


#: Which method calls which operation. This is the only place the two are tied
#: together, and the tests below read it in both directions: an endpoint with no method
#: fails, and a method naming an endpoint that no longer exists fails too.
MINTER = {
    ("post", "/api/mint"): "mint",
    ("post", "/api/mint/bulk"): "mint_many",
    ("post", "/api/register"): "register",
    ("post", "/api/import"): "import_ark",
    ("post", "/api/import/bulk"): "import_many",
    ("put", "/api/update"): "update",
    ("patch", "/api/update"): "patch",
    ("put", "/api/update/bulk"): "update_many",
    ("post", "/api/publish"): "publish",
    ("post", "/api/unpublish"): "unpublish",
    ("post", "/api/delete"): "delete",
    ("post", "/api/delete/bulk"): "delete_many",
    ("post", "/api/purge"): "purge",
    ("put", "/api/tombstone"): "tombstone",
    ("put", "/api/hold"): "hold",
    ("put", "/api/hold/release"): "release_hold",
    ("post", "/api/query"): "query",
    ("get", "/api/stats"): "stats",
    ("post", "/oauth/token"): "token",
}

RESOLVER = {
    ("get", "/.well-known/ark"): "inventory",
    ("get", "/ark:{rest}"): "resolve",
    # The old ark:/ form is the same operation. Both are answered in perpetuity, and
    # the client passes either through as it arrived.
    ("get", "/ark:/{rest}"): "resolve",
}

#: Methods that are not an endpoint: the connection itself.
HOUSEKEEPING = {"close"}


def operations(document: dict) -> set[tuple[str, str]]:
    return {
        (method, path)
        for path, methods in document["paths"].items()
        for method in methods
    }


@pytest.mark.parametrize(
    ("name", "cls", "table"),
    [("openapi-minter.json", Arkhe, MINTER), ("openapi-resolver.json", Resolver, RESOLVER)],
)
def test_every_endpoint_has_a_method(name, cls, table):
    """An endpoint the client cannot call is one its users have to reach around it to
    use, with their own idea of what a retry is safe to do."""
    missing = operations(load(name)) - set(table)
    assert not missing, (
        "endpoints with nothing to call them: "
        + ", ".join(f"{m.upper()} {p}" for m, p in sorted(missing))
    )
    for (method, path), attr in table.items():
        assert callable(getattr(cls, attr, None)), (
            f"{cls.__name__}.{attr} was named for {method.upper()} {path} and is not there"
        )


@pytest.mark.parametrize(
    ("name", "cls", "table"),
    [("openapi-minter.json", Arkhe, MINTER), ("openapi-resolver.json", Resolver, RESOLVER)],
)
def test_no_method_calls_an_endpoint_that_is_gone(name, cls, table):
    """The other direction. After a route is removed the method would keep compiling
    and fail only when someone called it."""
    stale = set(table) - operations(load(name))
    assert not stale, (
        "the client calls endpoints this API no longer has: "
        + ", ".join(f"{m.upper()} {p}" for m, p in sorted(stale))
    )


@pytest.mark.parametrize(
    ("cls", "table", "extra"),
    [
        (Arkhe, MINTER, {"describe", "statement", "exists"}),
        (Resolver, RESOLVER, {"describe", "statement", "exists"}),
    ],
)
def test_every_public_method_is_accounted_for(cls, table, extra):
    """A method that speaks to no endpoint in the table is either a convenience built
    on one that is, or something nobody listed. The convenience ones are named here so
    that anything else stands out."""
    public = {
        name
        for name, value in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
    }
    unlisted = public - set(table.values()) - HOUSEKEEPING - extra
    assert not unlisted, f"methods nothing accounts for: {sorted(unlisted)}"


def test_what_an_ark_carries_matches_the_document():
    """Ark mirrors the ArkOut schema. A field added to the server would otherwise
    reach callers only through .raw, which nobody looks in."""
    schema = load("openapi-minter.json")["components"]["schemas"]["ArkOut"]
    documented = set(schema["properties"])
    # resent comes from the status code, not the body; raw is the answer itself.
    ours = {f.name for f in Ark.__dataclass_fields__.values()} - {"resent", "raw"}
    assert ours == documented, (
        f"only in the document: {sorted(documented - ours)}; "
        f"only in the client: {sorted(ours - documented)}"
    )


def test_the_metadata_fields_match_the_document():
    """The same set is accepted when minting, importing, registering and updating,
    which is why every one of those methods takes the same keywords."""
    schemas = load("openapi-minter.json")["components"]["schemas"]
    mint = set(schemas["MintIn"]["properties"]) - {"shoulder", "reserve", "request_id"}
    update = set(schemas["UpdateIn"]["properties"]) - {"ark"}
    assert set(FIELDS) == mint == update


@pytest.mark.parametrize("method", ["mint", "register", "import_ark", "update", "patch"])
def test_the_writing_methods_take_every_field(method):
    """A field the client cannot pass cannot be set at all, and the caller finds out by
    reading the source."""
    taken = set(inspect.signature(getattr(Arkhe, method)).parameters)
    assert set(FIELDS) <= taken, f"Arkhe.{method} cannot set {sorted(set(FIELDS) - taken)}"
