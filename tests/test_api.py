"""The HTTP endpoints. Authentication is substituted; authorisation is real."""

from __future__ import annotations

import pytest

from arkhe.auth.deps import Db
from arkhe.db.models import Authority


def test_an_ark_can_be_minted_and_resolved(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/api/mint", json={"url": "https://example.org/1", "title": "A"})
    assert r.status_code == 201
    key = r.json()["ark"].removeprefix("ark:")
    assert c.get(f"/ark:/{key}").headers["location"] == "https://example.org/1"


def test_f4_a_resend_of_one_request_id_mints_nothing(world, principal_of, as_principal):
    """A lost response must not add a number. ARKs are never reassigned, so a dead
    number cannot be taken back."""
    c = as_principal(principal_of(manager=world["a"]))
    a = c.post("/api/mint", json={"request_id": "job-1"})
    b = c.post("/api/mint", json={"request_id": "job-1"})
    assert (a.status_code, b.status_code) == (201, 200)
    assert a.json()["ark"] == b.json()["ark"]


def test_f4_request_ids_are_per_principal(world, principal_of, as_principal):
    """They do not collide across organisations, and guessing one does not reveal
    another organisation's ARK."""
    a = as_principal(principal_of(manager=world["a"], client_id="a")).post(
        "/api/mint", json={"request_id": "same"}
    )
    b = as_principal(principal_of(manager=world["b"], client_id="b")).post(
        "/api/mint", json={"request_id": "same"}
    )
    assert a.json()["ark"] != b.json()["ark"]


def test_f4_a_repeated_request_id_inside_one_batch_is_handled(world, principal_of, as_principal):
    """The receipt is unique per (client, request_id). Two rows in one request sharing
    a request_id meant writing the receipt twice, an IntegrityError and a 500.

    One request_id means one request, so a single ARK is minted and returned for both
    rows: the same promise as a resend, applied inside a batch.
    """
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/api/mint/bulk", json={"data": [
        {"request_id": "same", "url": "https://example.org/1"},
        {"request_id": "same", "url": "https://example.org/2"},
        {"url": "https://example.org/3"},
    ]})
    assert r.status_code == 201
    body = r.json()
    assert body["minted"][0]["ark"] == body["minted"][1]["ark"]   # one ARK
    assert body["minted"][2]["ark"] != body["minted"][0]["ark"]   # unmarked rows differ
    assert (body["created"], body["replayed"]) == (2, 1)


def test_bulk_minting_answers_in_the_order_it_was_asked(world, principal_of, as_principal):
    """Resends and new mints are mixed together, so the order is kept for the caller
    to line them up."""
    c = as_principal(principal_of(manager=world["a"]))
    c.post("/api/mint", json={"request_id": "r2"})
    r = c.post(
        "/api/mint/bulk",
        json={"data": [{"request_id": "r1"}, {"request_id": "r2"}, {"request_id": "r3"}]},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["created"] == 2 and body["replayed"] == 1
    assert len(body["minted"]) == 3


def test_one_row_out_of_reach_mints_nothing(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/api/mint/bulk", json={"data": [{}, {"shoulder": "/b2"}]})
    assert r.status_code == 403


def test_m4_another_organisations_ark_cannot_be_read(db, world, principal_of, as_principal):
    from arkhe.domain import minting

    theirs, _ = minting.mint(db, shoulder=world["sh_b"], created_by="b")
    db.commit()
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/api/query", json={"data": [f"ark:/{theirs.ark}"]})
    assert r.json()["data"] == []


def test_a_tombstone_is_not_a_deletion(world, principal_of, as_principal):
    """The identifier and its metadata stay; only reachability goes."""
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://x/1", "title": "T"}).json()["ark"]
    r = c.put("/api/tombstone", json={"ark": key, "commitment": "the object is gone"})
    assert r.status_code == 200 and r.json()["url"] == ""
    assert r.json()["title"] == "T"  # the metadata stays
    # D6: with no target, describe it instead of redirecting to a bare suffix
    assert c.get(f"/{key}").status_code == 200


def test_tombstone_has_its_own_scope(world, principal_of, as_principal):
    """A tombstone declares that something is gone, not where it is, so it is not
    handed to an everyday writer such as a loading batch."""
    c = as_principal(principal_of(manager=world["a"], scopes={"ark:mint", "ark:update"}))
    key = c.post("/api/mint", json={}).json()["ark"]
    assert c.put("/api/tombstone", json={"ark": key}).status_code == 403


def test_minting_into_a_delegated_shoulder_answers_307(db, world, root, principal_of, as_principal):
    """Nothing is proxied. Calling on someone's behalf means that a lost response
    leaves an ARK minted over there that we know nothing about."""
    from arkhe.domain import admin_ops as ops

    ops.set_shoulder_status(
        db, root, shoulder_id=world["sh_a"].id, status="delegated",
        minter="https://mint.example.org",
    )
    db.commit()
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/api/mint", json={})
    assert r.status_code == 307
    assert r.headers["location"] == "https://mint.example.org"


def test_variations_in_ark_spelling_are_absorbed(world, principal_of, as_principal):
    """Both ark:/x and x are accepted, through the same normalisation as resolution.

    Only the name ignores hyphens. A NAAN is the string itself (N2), so 9999-9 is a
    different NAAN and 400 is the right answer.
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"].removeprefix("ark:")
    naan, name = key.split("/", 1)
    hyphenated = f"{naan}/{name[:3]}-{name[3:]}"  # inside the name
    # 2.2: both label forms are recognised in perpetuity. Generating the new form
    # does not narrow what is accepted.
    for form in (f"ark:{key}", f"ark:/{key}", key, hyphenated):
        assert c.put(
            "/api/update", json={"ark": form, "url": "https://x/2"}
        ).status_code == 200, form
    # A hyphen inside the NAAN makes a different NAAN, which must not be accepted.
    # The url is valid here: what is being checked is the NAAN, not the target.
    bad = c.put(
        "/api/update",
        json={"ark": f"{naan[:4]}-{naan[4:]}/{name}", "url": "https://x/3"},
    )
    assert bad.status_code in (400, 404)


def test_f1_a_naan_as_long_as_the_specification_requires_works_end_to_end(
    db, root, principal_of, as_principal
):
    """2.3: receiving implementations must support NAANs of up to 16 octets.

    The limit of 10 existed to protect arklet's int(), and the reason disappeared once
    N2 settled that NAANs are strings. This goes end to end: parsing alone is not
    enough, because a narrow column fails at minting.
    """
    from arkhe.domain import admin_ops as ops

    long_naan = "bcdfghjkmnpqrstv"  # 16 betanumeric octets
    assert len(long_naan) == 16
    ops.create_naan(db, root, naan=long_naan, name="an RA with a long NAAN")
    db.flush()
    manager, _ = ops.onboard_manager(db, root, naan=long_naan, name="org D", shoulder="/d4")
    db.commit()

    c = as_principal(principal_of(naan=long_naan, manager=manager))
    r = c.post("/api/mint", json={"url": "https://long.example.org/1"})
    assert r.status_code == 201
    key = r.json()["ark"].removeprefix("ark:")
    assert key.startswith(f"{long_naan}/")
    assert c.get(f"/ark:/{key}").headers["location"] == "https://long.example.org/1"


def test_f1_names_are_accepted_to_the_specified_length_and_refused_beyond_it(
    world, principal_of, as_principal
):
    """3.1: a base name plus qualifier must be supported up to 255 octets.

    Beyond that we do not fail with a database error. The limit is ours, about what we
    can index, so we say so and answer 400. The specification also warns whoever makes
    long strings that receiving implementations may not index them.
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"]
    base = key.removeprefix("ark:").split("/", 1)[1]

    fits = "/" + "z" * (255 - len(base) - 1)      # base plus qualifier is exactly 255
    r = c.post("/api/register", json={"ark": key, "qualifier": fits, "url": "https://x/2"})
    assert r.status_code == 201
    assert len(r.json()["ark"].removeprefix("ark:").split("/", 1)[1]) == 255

    over = fits + "z"                              # one octet too many
    bad = c.post("/api/register", json={"ark": key, "qualifier": over, "url": "https://x/3"})
    assert bad.status_code == 400
    assert bad.json()["code"] == "ARKHE-1004"
    assert bad.json()["detail"] == {"length": 256, "limit": 255}


def _delegate(db, root, shoulder):
    """Put the shoulder into the delegated state, which import requires."""
    from arkhe.domain import admin_ops as ops

    ops.set_shoulder_status(
        db, root, shoulder_id=shoulder.id, status="delegated",
        minter="https://closed.example/api",
    )
    db.commit()


def _valid_name(naan: str, stem: str) -> str:
    """Build a name with a correct check digit, as an outside minter would have."""
    from arkhe.arkspec.betanumeric import check_digit_base, noid_check_digit

    return stem + noid_check_digit(check_digit_base(naan, stem))


def test_a_delegation_with_no_endpoint_answers_403_with_guidance(
    db, world, root, principal_of, as_principal
):
    """Location means "send the same request there".

    Putting a page for people in it makes clients POST to that page. A delegation with
    no endpoint, on a closed network for instance, answers 403 with guidance in the body
    rather than 307.
    """
    from arkhe.domain import admin_ops as ops

    # With an endpoint, 307 lets a machine follow it
    ops.set_shoulder_status(
        db, root, shoulder_id=world["sh_a"].id, status="delegated",
        minter="https://mint.example.org",
    )
    db.commit()
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/api/mint", json={})
    assert r.status_code == 307
    assert r.headers["location"] == "https://mint.example.org"
    assert r.json()["code"] == "ARKHE-1306"

    # With only a page for people, 403 and no Location
    ops.set_shoulder_status(
        db, root, shoulder_id=world["sh_b"].id, status="delegated",
        about="https://ark.example.ac.jp/closed/99999",
    )
    db.commit()
    c2 = as_principal(principal_of(manager=world["b"]))
    r2 = c2.post("/api/mint", json={})
    assert r2.status_code == 403
    assert "location" not in r2.headers
    assert r2.json()["code"] == "ARKHE-1309"
    assert r2.json()["detail"]["about"] == "https://ark.example.ac.jp/closed/99999"


def test_a_delegation_with_no_target_just_says_we_do_not_mint_here(db, world, root,
                                                             principal_of, as_principal):
    """A delegation with nothing to point at is still valid: being able to give
    directions and being able to delegate are different things.

    Demanding a URL where there is none only produces invented values.
    """
    from arkhe.domain import admin_ops as ops

    ops.set_shoulder_status(db, root, shoulder_id=world["sh_a"].id, status="delegated")
    db.commit()
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/api/mint", json={})
    assert r.status_code == 403
    assert r.json()["code"] == "ARKHE-1309"
    # No invented URL: what does not exist does not appear in detail either.
    assert "about" not in r.json().get("detail", {})
    assert "location" not in r.headers


def test_well_known_separates_the_minter_from_the_guidance(
    db, world, root, principal_of, as_principal
):
    """Not under one key: a reader could no longer tell the API from a page for
    people."""
    from arkhe.domain import admin_ops as ops

    ops.set_shoulder_status(
        db, root, shoulder_id=world["sh_a"].id, status="delegated",
        minter="https://mint.example.org",
    )
    ops.set_shoulder_status(
        db, root, shoulder_id=world["sh_b"].id, status="delegated",
        about="https://ark.example.ac.jp/closed/99999",
    )
    db.commit()
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    rows = {s["shoulder"]: s for s in
            c.get("/.well-known/ark", headers={"Accept": "application/json"})
             .json()["delegated_shoulders"]}
    assert rows["99999/a1"]["minter"] == "https://mint.example.org"
    assert rows["99999/a1"]["about"] is None
    assert rows["99999/b2"]["minter"] is None
    assert rows["99999/b2"]["about"] == "https://ark.example.ac.jp/closed/99999"


def test_import_only_accepts_a_delegated_namespace(db, world, root, principal_of, as_principal):
    """The endpoint for bringing a name minted on a closed network into the public
    ledger (C-2 to C-1).

    It is separate from minting because the caller brings the name. Everything mint
    guaranteed structurally, no collision, a correct check digit, inside our own
    namespace, becomes a check here.
    """
    _delegate(db, root, world["sh_a"])
    c = as_principal(principal_of(manager=world["a"], scopes={"ark:import"}))
    name = _valid_name("99999", "a1closed01")

    r = c.post("/api/import", json={
        "ark": f"ark:99999/{name}", "title": "minted on a closed network",
        "url": "https://repo.example/records/9",
    })
    assert r.status_code == 201 and r.json()["ark"] == f"ark:99999/{name}"

    # Not twice: as with minting, nothing existing is overwritten silently (E1).
    again = c.post("/api/import", json={"ark": f"ark:99999/{name}"})
    assert again.status_code == 400 and again.json()["code"] == "ARKHE-1005"

    # A wrong check digit is refused: it is the only way to trust a name from outside.
    bad = c.post("/api/import", json={"ark": f"ark:99999/{name[:-1]}z"})
    assert bad.status_code == 400 and bad.json()["code"] == "ARKHE-1012"

    # A shoulder that is not delegated is refused: it could collide with our minting.
    other = _valid_name("99999", "b2closed01")
    r2 = c.post("/api/import", json={"ark": f"ark:99999/{other}"})
    assert r2.status_code in (400, 403)


def test_import_reach_follows_the_tiers(db, world, root, principal_of, as_principal):
    """A wider authority covers a narrower one and not the other way round, the same
    decision minting uses."""
    _delegate(db, root, world["sh_a"])
    _delegate(db, root, world["sh_b"])
    n_a = _valid_name("99999", "a1reach001")
    n_b = _valid_name("99999", "b2reach001")

    # A principal of organisation A does not reach B's shoulder.
    a = as_principal(principal_of(manager=world["a"], scopes={"ark:import"}))
    assert a.post("/api/import", json={"ark": f"ark:99999/{n_b}"}).status_code == 403
    assert a.post("/api/import", json={"ark": f"ark:99999/{n_a}"}).status_code == 201

    # A NAAN-level principal reaches every shoulder under that NAAN.
    naan_wide = as_principal(
        principal_of(authority=Authority.NAAN, naan="99999", scopes={"ark:import"})
    )
    assert naan_wide.post("/api/import", json={"ark": f"ark:99999/{n_b}"}).status_code == 201

    # It does not reach another NAAN.
    n_c = _valid_name("88888", "c3reach001")
    assert naan_wide.post("/api/import", json={"ark": f"ark:88888/{n_c}"}).status_code == 403


def test_import_is_refused_for_a_naan_we_are_not_authoritative_for(
    db, world, root, principal_of, as_principal
):
    """We do not claim to hold a NAAN we merely forward, which is separate from the
    principal's reach."""
    from arkhe.db.models import Naan

    # Make it a NAAN we only forward for
    naan = db.get(Naan, "88888")
    naan.is_authoritative = False
    naan.redirect = "https://elsewhere.example"
    db.commit()
    _delegate(db, root, world["sh_c"])
    sysadmin = as_principal(
        principal_of(authority=Authority.SYSTEM, naan="", scopes={"ark:import"})
    )
    name = _valid_name("88888", "c3notours1")
    r = sysadmin.post("/api/import", json={"ark": f"ark:88888/{name}"})
    assert r.status_code == 403 and r.json()["code"] == "ARKHE-1308"


def test_one_bad_row_imports_nothing(db, world, root, principal_of, as_principal):
    """Half-imported names cannot be taken back, which makes a partial apply worse
    here than in minting."""
    _delegate(db, root, world["sh_a"])
    c = as_principal(principal_of(manager=world["a"], scopes={"ark:import", "ark:read"}))
    ok1 = _valid_name("99999", "a1bulk0001")
    ok2 = _valid_name("99999", "a1bulk0002")

    bad = c.post("/api/import/bulk", json={"data": [
        {"ark": f"ark:99999/{ok1}"},
        {"ark": f"ark:99999/{ok2[:-1]}z"},   # broken check digit
    ]})
    assert bad.status_code == 400
    assert c.post("/api/query", json={"data": [f"ark:99999/{ok1}"]}).json()["data"] == []

    good = c.post("/api/import/bulk", json={"data": [
        {"ark": f"ark:99999/{ok1}", "title": "1"},
        {"ark": f"ark:99999/{ok2}", "title": "2"},
    ]})
    assert good.status_code == 201 and good.json()["count"] == 2


def test_an_imported_ark_is_published_under_the_same_name(
    db, world, root, principal_of, as_principal
):
    """This is why the endpoint exists: a name handed out while closed can be
    published unchanged."""
    _delegate(db, root, world["sh_a"])
    c = as_principal(principal_of(manager=world["a"], scopes={"ark:import", "ark:update"}))
    name = _valid_name("99999", "a1embargo1")

    # Import with a description and no target: it exists, but cannot be reached
    c.post("/api/import", json={"ark": f"ark:99999/{name}", "title": "under embargo"})
    assert c.get(f"/ark:99999/{name}", follow_redirects=False).status_code == 200

    # When the embargo lifts, only the url is set. The identifier does not change.
    c.patch("/api/update", json={
        "ark": f"ark:99999/{name}", "url": "https://repo.example/records/9",
    })
    moved = c.get(f"/ark:99999/{name}", follow_redirects=False)
    assert moved.status_code == 302
    assert moved.headers["location"] == "https://repo.example/records/9"


def test_patch_changes_only_the_fields_that_were_sent(world, principal_of, as_principal):
    """PUT replaces and PATCH amends. The common case is moving only the target, and
    doing that with PUT wipes the description back to defaults.
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={
        "url": "https://one.example/1", "title": "a title", "who": "an author",
        "when": "2026",
    }).json()["ark"]

    moved = c.patch("/api/update", json={"ark": key, "url": "https://two.example/2"}).json()
    assert moved["url"] == "https://two.example/2"
    assert (moved["title"], moved["who"], moved["when"]) == ("a title", "an author", "2026")

    # An empty string clears the field. Without that distinction there would be no
    # way to remove a value at all.
    cleared = c.patch("/api/update", json={"ark": key, "title": ""}).json()
    assert cleared["title"] == "" and cleared["who"] == "an author"

    # PUT still replaces, unchanged.
    replaced = c.put("/api/update", json={"ark": key, "url": "https://three.example/3"}).json()
    assert replaced["who"] == "" and replaced["url"] == "https://three.example/3"

    # Permissions and reach go through the same path as PUT.
    thin = as_principal(principal_of(manager=world["a"], scopes={"ark:read"}))
    assert thin.patch("/api/update", json={"ark": key, "url": "https://x/9"}).status_code == 403


def test_info_varies_by_media_type(world, principal_of, as_principal):
    """5.2: the shape of the response is indicated by the content type returned. The
    content is the same description and persistence statement each time; only the media
    type differs.

    ?json stays as another way of naming that JSON, not as different content.
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={
        "url": "https://x/1", "title": "a title", "who": "an author", "when": "2026",
    }).json()["ark"].removeprefix("ark:")

    html = c.get(f"/ark:{key}?info")
    assert html.headers["content-type"].startswith("text/html")

    js = c.get(f"/ark:{key}?info", headers={"Accept": "application/json"})
    assert js.headers["content-type"].startswith("application/json")
    assert js.json()["where"] == f"ark:{key}"
    # The same thing ?json returns.
    assert js.json() == c.get(f"/ark:{key}?json").json()

    anvl = c.get(f"/ark:{key}?info", headers={"Accept": "text/plain"})
    assert anvl.headers["content-type"].startswith("text/plain")
    assert anvl.text == c.get(f"/ark:{key}??").text   # the same as ??

    # All of them carry the THUMP headers and say through Vary that they differ.
    for r in (html, js):
        assert r.headers["thump-status"] == "0.6 200 OK"
        assert "Accept" in r.headers["vary"]


def test_info_answers_in_the_readers_language(world, principal_of, as_principal):
    """?info is public, and ARKs are followed from anywhere. Speaking only one
    language means the identifier arrives but the description cannot be read.

    ?lang= on its own will not do, because the query string is the inflection. It is
    written ?info&lang=en.
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"].removeprefix("ark:")

    ja = c.get(f"/ark:{key}?info")
    en = c.get(f"/ark:{key}?info&lang=en")
    # The Japanese heading is written as an escape: it comes from the Japanese UI.
    assert "\u6c38\u7d9a\u6027\u306b\u3064\u3044\u3066" in ja.text \
        and 'lang="ja"' in ja.text
    assert "On persistence" in en.text and 'lang="en"' in en.text

    # Accept-Language switches it too.
    hdr = c.get(f"/ark:{key}?info", headers={"Accept-Language": "en-GB,en;q=0.9"})
    assert "On persistence" in hdr.text

    # The name of the commitment level comes from the catalogue too, and appears
    # in ?json as well.
    js = c.get(f"/ark:{key}?info&lang=en", headers={"Accept": "application/json"}).json()
    assert js["commitment_label"] == "permanent; the content may be revised"


def test_a5_the_new_form_is_generated_and_the_old_one_still_accepted(
    world, principal_of, as_principal
):
    """2.2: both ark: and ark:/ must be recognised in perpetuity, and implementations
    should generate new ARKs in the new form.

    Accepting and generating are deliberately asymmetric. Narrowing what is accepted
    kills existing references; keeping the old form on the way out means the strings we
    hand round become someone else's input and the old form never shrinks.
    """
    c = as_principal(principal_of(manager=world["a"]))
    ark = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"]
    assert ark.startswith("ark:") and not ark.startswith("ark:/")
    key = ark.removeprefix("ark:")

    # Everything we emit uses the new form. One place left behind keeps leaking it.
    assert c.get(f"/ark:{key}?json").json()["ark"] == f"ark:{key}"
    assert f"ark:{key}" in c.get(f"/ark:{key}??").text
    missing = c.get(f"/ark:{key}zz-not-registered")
    assert missing.status_code == 404 and "ark:/" not in missing.text

    # What is accepted does not shrink: the old form and an upper-case label both hit
    # the same ARK.
    for path in (f"/ark:{key}", f"/ark:/{key}", f"/ARK:/{key}", f"/Ark:{key}"):
        assert c.get(path, follow_redirects=False).headers["location"] == "https://x/1", path


def test_errors_come_back_with_a_code_and_english_wording(world, principal_of, as_principal):
    """Callers branch on the code, not the wording, which changes with translation and
    tone.

    detail returns the values that were interpolated, still structured, so that nobody
    has to pull numbers out of a sentence.
    """
    # Create the other organisation's ARK first. as_principal overrides the same app,
    # so the principal created last is the one in force.
    theirs = as_principal(principal_of(manager=world["b"], client_id="b")).post(
        "/api/mint", json={}
    ).json()["ark"]

    c = as_principal(principal_of(manager=world["a"]))

    over = c.post("/api/mint/bulk", json={"data": [{} for _ in range(1001)]})
    assert over.status_code == 400
    assert over.json() == {
        "code": "ARKHE-1011",
        "message": "A request holds at most 1000 rows.",
        "detail": {"limit": 1000},
    }

    # Another organisation's ARK is out of reach, and the code says it is about reach.
    denied = c.put("/api/update", json={"ark": theirs, "url": "https://x/1"})
    assert denied.status_code in (403, 404)
    assert denied.json()["code"].startswith("ARKHE-1")

    # An ARK that cannot be parsed is 400.
    bad = c.put("/api/update", json={"ark": "not-an-ark", "url": "https://x/1"})
    assert bad.status_code == 400 and bad.json()["code"] == "ARKHE-1001"

    # A missing scope is named in the answer.
    thin = as_principal(principal_of(manager=world["a"], scopes={"ark:read"}))
    short = thin.post("/api/mint", json={})
    assert short.status_code == 403
    assert short.json()["code"] == "ARKHE-1301"
    assert short.json()["detail"]["scope"] == "ark:mint"


def test_the_resolution_code_is_at_the_start_of_the_body(world, principal_of, as_principal):
    """Resolution answers in text/plain, which people read, so the code goes
    first."""
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"].removeprefix("ark:")
    naan = key.split("/")[0]

    # A name whose check digit fails is reported as a transcription error.
    mistyped = c.get(f"/ark:{naan}/x9zzzzzzzz")
    assert mistyped.status_code == 404
    assert mistyped.text.startswith("ARKHE-1403 ")

    # Not readable as an ARK at all.
    unreadable = c.get("/ark:/")
    assert unreadable.status_code == 400 and unreadable.text.startswith("ARKHE-1001 ")


def test_a1_the_label_ignores_case_in_the_route_too(world, principal_of, as_principal):
    """3.2, step 3: case-insensitively, replace the first match of ark:/ or ark: with
    ark:.

    parse_ark ignored case from the start, but route matching does not, so /ARK:/...
    never reached the router and answered 404. Only the five characters of the label are
    changed; the case of the name is part of the identifier (step 5).
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"].removeprefix("ark:")
    for label in ("ark:", "ark:/", "ARK:", "ARK:/", "Ark:", "aRk:/"):
        r = c.get(f"/{label}{key}", follow_redirects=False)
        assert r.headers.get("location") == "https://x/1", label

    # The case of the name is left alone: changing it would hit another identifier.
    assert c.get(f"/ARK:{key.upper()}", follow_redirects=False).status_code == 404


def test_c7_the_thump_headers_are_sent(world, principal_of, as_principal):
    """5.2. The specification explains what Link is for: telling a recipient that does
    not know about inflections that this response describes the unqualified ARK.

    The rel is spelled as RFC 8288 requires, not as the example in the specification
    shows. The example is wrong, and a standard Link parser cannot read it.
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"].removeprefix("ark:")

    # A bare ? is not included: the query string alone cannot be told apart, and on
    # this path it means no inflection, so a redirect. See ARKHE_RAW_URI_HEADER.
    for q in ("??", "?info", "?json"):
        h = c.get(f"/ark:{key}{q}").headers
        assert h["thump-status"] == "0.6 200 OK", q
        assert h["link"] == f'</ark:{key}>; rel="describes"', q

    # Not found is a THUMP response too.
    missing = c.get(f"/ark:{key}zz-not-registered?info")
    assert missing.status_code == 404
    assert missing.headers["thump-status"] == "0.6 404 Not Found"

    # Not on a redirect: that is not a THUMP answer but a way to the object.
    assert "thump-status" not in c.get(f"/ark:{key}", follow_redirects=False).headers


def test_c6_where_is_the_ark_not_the_target(world, principal_of, as_principal):
    """5.1.2: where is the long-term identifier, not the temporary target.

    It used to be the other way round: where held the target URL and the ARK was the
    fallback when there was none. A description answers what this identifier names, so
    unless the value survives a change of target it cannot be cited.
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={
        "url": "https://one.example/1", "title": "a title", "who": "an author",
        "when": "2026",
    }).json()["ark"].removeprefix("ark:")

    body = c.get(f"/ark:{key}??").text
    assert f"where: ark:{key}" in body
    # The target is not thrown away: it appears outside the kernel when there is one.
    assert "redirect: https://one.example/1" in body

    j = c.get(f"/ark:{key}?json").json()
    assert j["where"] == f"ark:{key}" and j["redirect"] == "https://one.example/1"

    # Changing the target does not move where, which is what the element means.
    c.put("/api/update", json={"ark": f"ark:{key}", "url": "https://two.example/2"})
    j2 = c.get(f"/ark:{key}?json").json()
    assert j2["where"] == j["where"] and j2["redirect"] == "https://two.example/2"

    # An ARK with no target can still answer where (FAIR A2).
    c.put("/api/tombstone", json={"ark": f"ark:{key}", "commitment": "lost"})
    assert f"where: ark:{key}" in c.get(f"/ark:{key}??").text


def test_a4_an_encoded_slash_is_not_a_separator(world, principal_of, as_principal):
    """draft-kunze-ark-42, 3.2: a percent-encoded character must not be shown decoded.

    %2F is the only way to write a slash that is not a separator; 3.2 permits encoding a
    reserved character exactly to hide its reserved meaning. Decoded, base/a%2Fb, which
    is one name, becomes base/a/b, meaning b inside base/a, and inheritance then follows
    the base's target: a different identifier answered with something else.

    ASGI decodes the path first, so it is read again from scope["raw_path"].
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://base.example.org/1"}).json()["ark"]
    base = key.removeprefix("ark:")

    # Register a qualifier containing the hidden slash, with its own target.
    r = c.post("/api/register", json={"ark": key, "qualifier": "/a%2fb",
                                      "url": "https://other.example.org/2"})
    assert r.status_code == 201
    # Step 5: what is stored is the upper-case form.
    assert r.json()["ark"] == f"ark:{base}/a%2Fb"

    # It hits that row, not the base target with /a/b appended.
    hit = c.get(f"/ark:/{base}/a%2Fb", follow_redirects=False)
    assert hit.status_code == 302
    assert hit.headers["location"] == "https://other.example.org/2"

    # Lower case hits the same row; step 5 applies on the way in too.
    assert c.get(f"/ark:/{base}/a%2fb", follow_redirects=False).headers["location"] == (
        "https://other.example.org/2"
    )

    # A plain slash is a different identifier, and with nothing registered it
    # inherits from the base.
    passthrough = c.get(f"/ark:/{base}/a/b", follow_redirects=False)
    assert passthrough.status_code == 302
    assert passthrough.headers["location"] == "https://base.example.org/1/a/b"


def test_a4_without_raw_path_the_decoded_route_is_used():
    """It works on a server that does not pass the raw path, falling back to the
    previous behaviour."""
    from types import SimpleNamespace

    from arkhe.api.resolve import _raw_ark_path

    url = SimpleNamespace(path="/ark:/99999/x54/c2")
    assert _raw_ark_path(SimpleNamespace(scope={}, url=url)) == "/ark:/99999/x54/c2"
    # Some servers include the query, so it is cut at the first ?.
    req = SimpleNamespace(scope={"raw_path": b"/ark:/99999/x54%2Fc2?info"}, url=url)
    assert _raw_ark_path(req) == "/ark:/99999/x54%2Fc2"
    # Raw bytes that are not UTF-8 fall back rather than being invented.
    bad = SimpleNamespace(scope={"raw_path": b"/ark:/99999/x\xff"}, url=url)
    assert _raw_ark_path(bad) == "/ark:/99999/x54/c2"


def test_well_known_ark_answers_text_plain_by_default(world, principal_of, as_principal):
    """draft-kunze-ark-42, 5.6: a client that sends no Accept gets the representation
    the specification defines.

    Answering */* with our own JSON makes a discovery client that follows the
    specification conclude that this host is not an ARK resolver.
    """
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    r = c.get("/.well-known/ark")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    # The body is one line, the resolver root path, ending in a slash: appending a
    # compact ARK to it gives the resolution path, as the specification says.
    assert r.text.strip() == "/"
    assert c.get(f"{r.text.strip()}ark:/99999/x9abc").status_code in (200, 302, 404)
    # One URL with two representations, so caches in between need this.
    assert r.headers["vary"] == "Accept"


def test_well_known_ark_returns_the_inventory_only_when_json_is_asked_for(
    world, principal_of, as_principal
):
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    r = c.get("/.well-known/ark", headers={"Accept": "application/json"})
    assert r.status_code == 200
    assert {n["naan"] for n in r.json()["naans"]} == {"99999", "88888"}
    # The value the specification defines is in the JSON too, so one is enough.
    assert r.json()["resolver_path"] == "/"
    assert r.headers["vary"] == "Accept"


@pytest.mark.parametrize(
    ("accept", "want"),
    [
        ("", "text/plain"),                                   # no header
        ("*/*", "text/plain"),                                # what curl sends
        ("application/json", "application/json"),
        ("application/json, text/plain;q=0.9", "application/json"),
        ("text/plain, application/json", "text/plain"),       # a tie goes to the spec
        ("text/html,application/xhtml+xml,*/*;q=0.8", "text/plain"),  # a browser
        ("application/*", "application/json"),
        ("application/xml", "text/plain"),                    # neither is available
    ],
)
def test_how_well_known_ark_chooses_a_media_type(accept, want, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    r = c.get("/.well-known/ark", headers={"Accept": accept} if accept else {})
    assert r.headers["content-type"].startswith(want)


@pytest.mark.parametrize(
    ("root_path", "want"),
    [("", "/"), ("/", "/"), ("/pid", "/pid/"), ("/pid/", "/pid/"), (None, "/")],
)
def test_well_known_ark_reports_where_it_is_mounted(root_path, want):
    """When a proxy strips a prefix, that is what is reported.

    The specification says appending a compact ARK to the path gives a resolution
    request, so hard-coding / would point at the wrong place behind a prefix.
    """
    from types import SimpleNamespace

    from arkhe.api.resolve import _resolver_path

    assert _resolver_path(SimpleNamespace(scope={"root_path": root_path})) == want


@pytest.mark.parametrize("resolver", [False, True], ids=["minter", "resolver"])
def test_healthz_answers_in_every_mode(factory, resolver):
    """A probe endpoint is needed whatever the role.

    It used to live only on the resolve router, so the minter and the admin interface
    answered 404 to the liveness probe and kubelet kept killing them.
    """
    from fastapi.testclient import TestClient

    from arkhe.app import create_app
    from arkhe.settings import Settings

    app = create_app(
        Settings(
            resolver=resolver, database_url="sqlite://", auth=["apikey"],
            admin_login="bearer",
        )
    )
    assert TestClient(app).get("/healthz").json() == {"ok": True}


def test_the_public_page_carries_protective_headers(world, principal_of, as_principal):
    """Even if target validation is bypassed, no script runs.

    ?info is public and needs no credentials, and whoever minted the ARK decides the
    text on it, so it is guarded in layers.
    """
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/api/mint", json={"url": "https://example.org/1", "title": "x"})
    key = r.json()["ark"].removeprefix("ark:")
    # Check on a path that answers 200. The headers are present on a 404 too, which
    # would not show that the public page carries them.
    info = c.get(f"/ark:/{key}?info")
    assert info.status_code == 200
    h = info.headers
    assert "script-src 'none'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff"
    # The API documentation is the exception. Swagger UI loads script from a CDN, so
    # the plain CSP would leave a blank page. The sources are restricted.
    docs = c.get("/api/docs").headers["content-security-policy"]
    assert "script-src 'none'" not in docs
    assert "cdn.jsdelivr.net" in docs


# --------------------------------------- Recording a change of target


def test_a_change_of_target_is_recorded_even_at_organisation_level(
    db, world, principal_of, as_principal
):
    """The audit log only keeps NAAN level and above.

    Minting and repointing are done by organisations, so the audit log alone would miss
    the changes that matter most.
    """
    from arkhe.db.models import ArkChange

    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://before.example/1"}).json()["ark"]
    c.put("/api/update", json={"ark": key, "url": "https://after.example/2"})

    rows = db.scalars(db.query(ArkChange).statement).all()
    assert len(rows) == 1
    assert rows[0].before_url == "https://before.example/1"
    assert rows[0].after_url == "https://after.example/2"
    assert rows[0].action == "update"


def test_nothing_is_recorded_when_the_target_does_not_change(db, world, principal_of, as_principal):
    """Fixing only a title should not add history, which would bury the rest."""
    from arkhe.db.models import ArkChange

    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://same.example/1"}).json()["ark"]
    c.put("/api/update", json={"ark": key, "url": "https://same.example/1", "title": "a new title"})
    assert db.scalars(db.query(ArkChange).statement).all() == []


def test_a_tombstone_is_recorded_too(db, world, principal_of, as_principal):
    """It means something different from repointing, so the action tells them
    apart."""
    from arkhe.db.models import ArkChange

    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://gone.example/1"}).json()["ark"]
    c.put("/api/tombstone", json={"ark": key, "commitment": "withdrawn"})
    rows = db.scalars(db.query(ArkChange).statement).all()
    assert [r.action for r in rows] == ["tombstone"]
    assert rows[0].before_url == "https://gone.example/1"


def test_a_bulk_change_is_recorded_row_by_row(db, world, principal_of, as_principal):
    from arkhe.db.models import ArkChange

    c = as_principal(principal_of(manager=world["a"]))
    keys = [c.post("/api/mint", json={"url": f"https://b.example/{i}"}).json()["ark"]
            for i in range(3)]
    c.put("/api/update/bulk",
          json={"data": [{"ark": k, "url": f"https://a.example/{i}"}
                         for i, k in enumerate(keys)]})
    assert len(db.scalars(db.query(ArkChange).statement).all()) == 3


def test_who_made_the_change_is_recorded(db, world, principal_of, as_principal):
    from arkhe.db.models import ArkChange

    c = as_principal(principal_of(manager=world["a"], client_id="repo-1"))
    key = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"]
    c.put("/api/update", json={"ark": key, "url": "https://x/2"})
    assert db.scalars(db.query(ArkChange).statement).all()[0].by == "repo-1"


def test_a_target_a_browser_cannot_open_is_described(world, principal_of, as_principal):
    """Being registrable and being safe to send a browser to are different things.

    A urn: is a valid target that a browser cannot open. Handing it over in a 302 looks
    like a broken link; a description is the better answer.
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post(
        "/api/mint", json={"url": "urn:isbn:0451450523", "title": "a printed book"}
    ).json()["ark"].removeprefix("ark:")
    r = c.get(f"/ark:/{key}")
    assert r.status_code == 200                     # not a redirect
    assert "urn:isbn:0451450523" in r.text          # the target is shown
    assert '<a href="urn:' not in r.text            # but not as a link


def test_a_target_a_browser_can_open_is_redirected_to(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post(
        "/api/mint", json={"url": "https://ok.example/1"}
    ).json()["ark"].removeprefix("ark:")
    r = c.get(f"/ark:/{key}")
    assert r.status_code == 302 and r.headers["location"] == "https://ok.example/1"


@pytest.mark.parametrize("resolver", [False, True], ids=["minter", "resolver"])
def test_internal_knobs_do_not_leak_into_the_query(resolver):
    """FastAPI exposes a dependency's arguments as query parameters.

    While get_session took read_only as an argument, ?read_only=true appeared on every
    path, so POST /api/mint?read_only=true could aim a write at a replica from outside.
    The role decides which database is used, not the request.
    """
    from arkhe.app import create_app
    from arkhe.settings import Settings

    spec = create_app(
        Settings(
            resolver=resolver, database_url="sqlite://", auth=["apikey"],
            admin_login="bearer",
        )
    ).openapi()

    leaked = [
        f"{method.upper()} {path} ?{q['name']}"
        for path, ops in spec["paths"].items()
        for method, op in ops.items()
        for q in op.get("parameters", [])
        if q.get("in") == "query" and q["name"] == "read_only"
    ]
    assert not leaked, leaked


@pytest.mark.parametrize(
    "resolver,want", [(True, "replica"), (False, "primary")], ids=["resolver", "minter"]
)
def test_the_database_follows_this_apps_settings(resolver, want):
    """ARKHE_READ_DATABASE_URL has to take effect. The setting was read and used by
    nothing, so a resolver read from the write engine and never reached a replica.

    What counts is the settings passed to create_app. Taking the role from
    get_settings(), which caches the environment, means looking at different settings
    from the app that was built with create_app(settings=...), and then the routes and
    the database disagree. The URL used here is not in the environment, so reading from
    the environment would fail the comparison below.
    """
    from fastapi.testclient import TestClient

    from arkhe.app import create_app
    from arkhe.settings import Settings

    app = create_app(
        Settings(
            resolver=resolver, auth=["apikey"], admin_login="bearer",
            database_url="sqlite:///primary.sqlite3",
            read_database_url="sqlite:///replica.sqlite3",
        )
    )

    # The real dependency is used: substituting it would remove the wiring under test.
    # Db is imported at the top because, under from __future__ import annotations, the
    # annotation is a string and FastAPI cannot resolve an import made inside the
    # function.
    @app.get("/_bind", include_in_schema=False)
    def _bind(session: Db):
        return {"url": str(session.get_bind().url)}

    assert TestClient(app).get("/_bind").json()["url"].endswith(f"{want}.sqlite3")



def _spec(**over):
    """Build the OpenAPI document for that configuration through the real create_app.
    The document is the result of which routes are installed, so checking it without
    building the app would prove nothing."""
    from arkhe.app import create_app
    from arkhe.settings import Settings

    base = dict(database_url="sqlite://", admin_login="bearer", token_secret="x" * 48)
    return create_app(Settings(**(base | over))).openapi()


def test_the_specification_says_where_to_get_a_token():
    """Say where to get one in a machine-readable way. The URL was only in the README,
    so a client generated from the OpenAPI document had no way to authenticate.

    The advertised URL is checked to exist, so that changing a prefix cannot leave the
    document pointing at the old place.
    """
    from arkhe.domain import authz

    spec = _spec(auth=["apikey", "oauth2"])
    flow = spec["components"]["securitySchemes"]["oauth2"]["flows"]["clientCredentials"]

    assert flow["tokenUrl"] in spec["paths"]              # it points at a real route
    assert set(flow["scopes"]) == set(authz.SCOPES)       # one vocabulary
    assert "security" not in spec["paths"][flow["tokenUrl"]]["post"]  # the route is open

    # It sits alongside bearer, either being acceptable. Listing only one would make
    # using an API key look unsupported in the document.
    security = spec["paths"]["/api/mint"]["post"]["security"]
    assert {"oauth2": ["ark:mint"]} in security   # and what it requires
    assert {"bearer": []} in security


@pytest.mark.parametrize(
    "over", [{"auth": ["apikey"]}, {"resolver": True, "auth": ["apikey"]}],
    ids=["minter-apikey", "resolver"],
)
def test_a_configuration_without_the_route_does_not_advertise_it(over):
    """Do not point at a route that is not there: a generated client would meet a
    404."""
    spec = _spec(**over)
    assert "oauth2" not in spec.get("components", {}).get("securitySchemes", {})
    assert "/oauth/token" not in spec["paths"]


def test_the_documented_3xx_codes_match_what_can_be_produced():
    """Compare what is declared with what is implemented. The 3xx codes in the
    document have to be the ones expand_redirect can produce, or the contract is
    untrue.
    """
    from arkhe.api.resolve import _RESOLVE_RESPONSES
    from arkhe.domain.resolution import expand_redirect

    declared = {c for c in _RESOLVE_RESPONSES if 300 <= c < 400}
    produced = {expand_redirect(f"{c} https://x/$id", "99999", "abc")[0] for c in declared}
    assert produced == declared
    # An unsupported code falls back to the default, which is no reason to declare
    # more of them.
    assert expand_redirect("308 https://x/$id", "99999", "abc")[0] == 302


def test_a_200_from_resolution_uses_the_three_declared_media_types(
    world, principal_of, as_principal
):
    """The same 200 comes in different media types. With only application/json
    declared, a client generated from the document treats ANVL and HTML as unknown.
    """
    from arkhe.api.resolve import _RESOLVE_RESPONSES

    c = as_principal(principal_of(manager=world["a"]))
    key = c.post(
        "/api/mint", json={"url": "https://example.org/1", "title": "A"}
    ).json()["ark"].removeprefix("ark:")

    got = {
        c.get(f"/ark:/{key}?{q}").headers["content-type"].split(";")[0]
        for q in ("json", "?", "info")
    }
    assert got == set(_RESOLVE_RESPONSES[200]["content"])


def test_the_declared_scope_matches_the_enforced_one():
    """The declaration and the check live in two places: needs(...) on the route is
    what appears in the document, and require_scope(...) in the body is what refuses.
    If they drift, the document lies.

    They were not merged because merging would attach the scope to bearer as well.
    OpenAPI does not allow scopes on any scheme other than oauth2 and openIdConnect,
    where the array must be empty, so only oauth2 is wrapped in Security.
    """
    import ast
    import pathlib

    src = pathlib.Path("src/arkhe/api/mint.py").read_text(encoding="utf-8")
    for fn in ast.walk(ast.parse(src)):
        if not isinstance(fn, ast.FunctionDef):
            continue
        declared = [
            k.value.args[0].value
            for d in fn.decorator_list if isinstance(d, ast.Call)
            for k in d.keywords
            if k.arg == "dependencies" and isinstance(k.value, ast.Call)
            and getattr(k.value.func, "id", "") == "needs"
        ]
        enforced = [
            x.args[1].value for x in ast.walk(fn)
            if isinstance(x, ast.Call)
            and ast.unparse(x.func) == "authz.require_scope"
        ]
        assert declared == enforced, f"{fn.name}: declared {declared}, enforced {enforced}"
        if fn.name != "_apply":
            assert not enforced or declared, f"{fn.name}: enforced but not declared"


def test_scopes_appear_only_under_oauth2():
    """OpenAPI 3.1, 4.8.30: for anything other than oauth2 and openIdConnect the array
    must be empty. bearer is type: http, so a scope there makes the document invalid.
    """
    spec = _spec(auth=["apikey", "oauth2"])
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            for requirement in op.get("security", []):
                for name, scopes in requirement.items():
                    if name != "oauth2":
                        assert scopes == [], f"{method.upper()} {path}: {name} has {scopes}"


# ------------------- Redundancy: one request arriving twice at the same time


def test_when_the_receipt_was_written_first_the_winners_ark_is_returned(db, world, principal_of):
    """The recovery side of something redundancy makes possible, tested
    deterministically.

    A retry from a load balancer, or a caller that gave up waiting, can reach two
    minters at once. Between checking for a resend and writing the receipt there is a
    gap, so both see nothing and both write.

    The guard is in the database (one_ark_per_request_id), so the ledger is safe. The
    problem is the answer to the loser: left alone it is a 500, which tells the caller
    nothing about whether an ARK was minted, and retrying with a new request_id would
    mint a second one.

    Here the receipt is written first, and _commit_or_replay has to return the winner's
    ARK. No threads are used, because what is being tested is the outcome of the race
    rather than the race itself.
    """
    from arkhe.api.mint import _commit_or_replay
    from arkhe.db.models import MintReceipt
    from arkhe.domain.minting import mint

    p = principal_of(scopes={"ark:mint"}, manager=world["a"], client_id="racer")
    winner, _ = mint(db, shoulder=world["sh_a"], created_by="winner")
    db.add(MintReceipt(client_id="racer", request_id="same", ark=winner.ark))
    db.commit()

    # The loser: mints with the same request_id and tries to write the same receipt.
    loser, _ = mint(db, shoulder=world["sh_a"], created_by="loser")
    db.add(MintReceipt(client_id="racer", request_id="same", ark=loser.ark))

    got = _commit_or_replay(db, p, "same", loser)
    assert got.ark == winner.ark, "the loser did not get the winner's ARK"
    assert db.query(MintReceipt).filter(MintReceipt.request_id == "same").count() == 1


# ------------------------------------------ Checking the Host header actually works


def test_allowed_hosts_really_takes_effect():
    """A setting that is declared and documented but does nothing is worse than no
    setting.

    An operator who set it counts the problem as handled while nothing is restricted.
    This one existed for a while and was read by nothing.
    """
    from fastapi.testclient import TestClient

    from arkhe.app import create_app
    from arkhe.settings import Settings

    def app(hosts):
        return create_app(
            Settings(resolver=True, database_url="sqlite:///:memory:", allowed_hosts=hosts)
        )

    narrow = app(["ark.example.org"])
    assert TestClient(narrow, base_url="http://ark.example.org").get("/healthz").status_code == 200
    assert TestClient(narrow, base_url="http://evil.example.net").get("/healthz").status_code == 400
    # Not installed by default: where a proxy terminates the connection it usually
    # checks this, and refusing twice makes problems harder to place.
    wide = app(["*"])
    assert TestClient(wide, base_url="http://anything.example").get("/healthz").status_code == 200


def test_the_pool_size_follows_the_settings():
    """Pool size multiplies by the number of workers.

    On the defaults that is up to 15 connections per process, so two resolvers with four
    workers each reach 120, past PostgreSQL's default max_connections of 100, or 97 once
    the reserve is taken out. The recommended shape jams there on the defaults, and
    without a knob the only remedy is fewer workers.
    """
    from arkhe.db.session import engines
    from arkhe.settings import Settings

    def cap(size, overflow):
        w, _ = engines(Settings(
            database_url="postgresql+psycopg://arkhe@localhost/arkhe",
            db_pool_size=size, db_max_overflow=overflow,
        ))
        return w.pool.size() + w.pool._max_overflow

    assert cap(5, 10) == 15, "the default ceiling has changed"
    assert cap(2, 2) == 4, "the setting had no effect"


def test_pre_ping_can_be_turned_off():
    """Turning it off roughly halves the database round trips per resolution: 1.60
    against 0.82 when measured.

    Resolution only reads one index, so the liveness check costs a lot in relative
    terms. It stays on by default; turning it off suits a deployment where the database
    is close and a dropped connection surfacing as an exception is acceptable.
    """
    from arkhe.db.session import engines
    from arkhe.settings import Settings

    def ping(v):
        w, _ = engines(Settings(
            database_url="postgresql+psycopg://arkhe@localhost/arkhe", db_pre_ping=v
        ))
        return w.pool._pre_ping

    assert ping(True) is True, "the default no longer checks"
    assert ping(False) is False, "the setting had no effect"
