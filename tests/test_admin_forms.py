"""Building the ledger from the admin interface.

What the screens show and what is actually authorised have to be one decision. Kept
apart, they leave the hole where the button is hidden but the POST still works. That is
what these tests look for.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from arkhe.db.models import Authority, Client, Manager, Naan, Shoulder
from arkhe.domain import admin_ops as ops

# -------------------------- The commitment level, which the organisation declares


def test_an_organisation_admin_can_restate_its_own_commitment(
    db, world, principal_of, as_principal
):
    """The promise belongs to the organisation; it is useless if they cannot state
    it."""
    a = world["a"]
    c = as_principal(principal_of(manager=a))
    r = c.post(f"/admin/manager/{a.id}", data={"commitment": "permanent-unchanging"})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Manager, a.id).commitment_level == "permanent-unchanging"


def test_an_organisation_admin_cannot_restate_another_organisations(
    db, world, principal_of, as_principal
):
    a, b = world["a"], world["b"]
    c = as_principal(principal_of(manager=a))
    r = c.post(f"/admin/manager/{b.id}", data={"commitment": "not-guaranteed"})
    assert r.status_code == 403
    db.expire_all()
    assert db.get(Manager, b.id).commitment_level != "not-guaranteed"


def test_the_system_administrator_can_restate_any_of_them(db, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.SYSTEM))
    r = c.post(f"/admin/manager/{world['c'].id}", data={"commitment": "descriptive-only"})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Manager, world["c"].id).commitment_level == "descriptive-only"


def test_an_organisation_cannot_lift_its_own_quota(db, world, principal_of, as_principal):
    """The quota is imposed by whoever handed out the namespace. A limit the limited
    party can lift is not a limit."""
    a = world["a"]
    a.quota_per_day = 10
    db.commit()
    c = as_principal(principal_of(manager=a))
    r = c.post(f"/admin/manager/{a.id}", data={"commitment": "permanent-stable", "quota": ""})
    assert r.status_code == 303          # the commitment itself is saved
    db.expire_all()
    assert db.get(Manager, a.id).quota_per_day == 10   # the quota does not move


# ------------------- The NAA policy, declared by whoever hands out the namespace


def test_an_organisation_admin_cannot_change_the_naa_policy(db, world, principal_of, as_principal):
    """The declaration covers every organisation under the NAAN, so one of them cannot
    rewrite it for the others."""
    before = db.get(Naan, "99999").na_policy
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/admin/naan/99999", data={"policy": "rewritten", "minter": ""})
    assert r.status_code == 403
    db.expire_all()
    assert db.get(Naan, "99999").na_policy == before


def test_a_naan_administrator_can_declare_the_policy(db, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.NAAN))
    r = c.post("/admin/naan/99999", data={"policy": "NP | NR, OP, CC | 2027 |", "minter": ""})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Naan, "99999").na_policy == "NP | NR, OP, CC | 2027 |"


def test_only_the_system_administrator_registers_a_naan(db, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.NAAN))
    assert c.get("/admin/naan/new").status_code == 403
    assert c.post(
        "/admin/naan/new", data={"naan": "77777", "name": "x"}
    ).status_code == 403


# ------------------------------------------------------- How far a screen reaches


def test_an_organisation_admin_cannot_open_the_naan_settings(world, principal_of, as_principal):
    """Opening and saving are allowed under the same conditions.

    Otherwise the form looks editable and the save returns 403, which is the same drift
    between display and authorisation.
    """
    c = as_principal(principal_of(manager=world["a"]))
    assert c.get("/admin/naan/99999").status_code == 403


def test_another_organisations_settings_cannot_be_opened(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    assert c.get(f"/admin/manager/{world['b'].id}").status_code == 403


def test_your_own_organisations_settings_can_be_opened(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    r = c.get(f"/admin/manager/{world['a'].id}")
    assert r.status_code == 200
    assert "permanent-dynamic" in r.text


def test_the_list_links_to_your_own_organisation(world, principal_of, as_principal):
    """The promise belongs to the organisation, so its admin gets the link."""
    a = world["a"]
    r = as_principal(principal_of(manager=a)).get("/admin/")
    assert f"/admin/manager/{a.id}" in r.text
    # The NAAN settings and the shoulder operations are not shown: out of reach
    assert "/admin/naan/99999" not in r.text
    assert "/admin/naan/new" not in r.text


# ------------------------------------------------------- Building the ledger


def test_onboarding_works_from_the_screen_too(db, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.NAAN))
    r = c.post("/admin/manager/new", data={
        "naan": "99999", "name": "org D", "shoulder": "/d4",
        "commitment": "permanent-stable", "quota": "100",
    })
    assert r.status_code == 303
    m = db.scalar(db.query(Manager).filter_by(name="org D").statement)
    assert m.commitment_level == "permanent-stable"
    assert m.quota_per_day == 100
    # An organisation and its namespace are always created together.
    assert db.get(Shoulder, m.default_shoulder_id).shoulder == "/d4"


def test_a_retired_shoulder_cannot_be_reopened_from_the_screen(
    db, world, principal_of, as_principal
):
    """The invariant is the same from the screen: the decision lives only in
    admin_ops."""
    sh = world["sh_a"]
    c = as_principal(principal_of(authority=Authority.NAAN))
    assert c.post(f"/admin/shoulder/{sh.id}", data={"status": "retired"}).status_code == 303
    db.expire_all()
    r = c.post(f"/admin/shoulder/{sh.id}", data={"status": "active"})
    # 400, not 403: this is not about permission. Nobody may do it.
    assert r.status_code == 400
    db.expire_all()
    assert db.get(Shoulder, sh.id).status == "retired"


@pytest.mark.parametrize("level", ["permanent", "eternal", ""])
def test_an_unknown_commitment_level_is_refused_here_too(
    db, world, principal_of, as_principal, level
):
    a = world["a"]
    before = a.commitment_level
    c = as_principal(principal_of(manager=a))
    r = c.post(f"/admin/manager/{a.id}", data={"commitment": level})
    db.expire_all()
    if level == "":
        assert r.status_code == 303      # empty means "leave it alone"
    else:
        assert r.status_code == 400
    assert db.get(Manager, a.id).commitment_level == before


# -------------------------------------------- Principals and issuing credentials


def test_a_credential_can_be_issued_from_the_screen(db, world, root, principal_of, as_principal):
    """The plaintext appears in this response and nowhere else; only a hash is
    stored."""
    c = ops.register_client(db, root, client_id="repo", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    r = cli.post(f"/admin/client/{c.id}/key", data={"kind": "api_key"})
    assert r.status_code == 200
    db.expire_all()
    cred = db.get(Client, c.id).credentials[0]
    assert cred.active and cred.prefix in r.text
    # The plaintext is not stored: what the page showed is not in the database.
    secret = r.text.split('class="secret">')[1].split("<")[0].strip()
    assert secret and secret not in cred.hashed


def test_reloading_does_not_show_the_credential_again(db, world, root, principal_of, as_principal):
    """Once per issue. Redirecting away makes that structural rather than a rule."""
    c = ops.register_client(db, root, client_id="repo2", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    cli.post(f"/admin/client/{c.id}/key", data={"kind": "api_key"})
    assert 'class="secret"' not in cli.get(f"/admin/client/{c.id}").text


def test_a_person_is_issued_no_credential(db, world, root, principal_of, as_principal):
    """A key handed to a person outlives their time at the organisation."""
    c = ops.register_client(db, root, client_id="alice@example.ac.jp", naan="99999",
                            manager_id=world["a"].id, subject_type="person")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    assert cli.post(f"/admin/client/{c.id}/key", data={"kind": "api_key"}).status_code == 400
    # The screen does not offer to issue one either
    assert "/key" not in cli.get(f"/admin/client/{c.id}").text


def test_no_credential_for_another_organisations_principal(
    db, world, root, principal_of, as_principal
):
    c = ops.register_client(db, root, client_id="other", naan="99999",
                            manager_id=world["b"].id, scopes="ark:mint")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    assert cli.get(f"/admin/client/{c.id}").status_code == 403
    assert cli.post(f"/admin/client/{c.id}/key", data={"kind": "api_key"}).status_code == 403


def test_revoking_keeps_the_row(db, world, root, principal_of, as_principal):
    """When it was revoked is kept. Whose key it was must stay traceable."""
    from arkhe.db.models import Credential

    c = ops.register_client(db, root, client_id="rot", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    issued = ops.issue_credential(db, root, client_pk=c.id)
    db.commit()
    cid = issued.credential.id
    cli = as_principal(principal_of(manager=world["a"]))
    r = cli.post(f"/admin/client/{c.id}/revoke", data={"credential_id": cid})
    assert r.status_code == 303
    db.expire_all()
    cred = db.get(Credential, cid)
    assert cred is not None and not cred.active and cred.expires_at is not None


def test_an_organisation_admin_registers_its_own_principals(db, world, principal_of, as_principal):
    """The screen is not stricter than admin_ops, or something that should be
    possible would not be."""
    cli = as_principal(principal_of(manager=world["a"]))
    r = cli.post("/admin/client/new", data={
        "client_id": "own-repo", "scopes": "ark:mint", "person": "",
    })
    assert r.status_code == 303
    made = db.scalar(db.query(Client).filter_by(client_id="own-repo").statement)
    assert made.manager_id == world["a"].id


def test_an_organisation_admin_cannot_choose_another_organisation(
    db, world, principal_of, as_principal
):
    """A value that was never offered falls back to the caller's own organisation."""
    cli = as_principal(principal_of(manager=world["a"]))
    r = cli.post("/admin/client/new", data={
        "client_id": "sneaky", "manager_id": str(world["b"].id), "scopes": "ark:mint",
    })
    assert r.status_code == 303
    made = db.scalar(db.query(Client).filter_by(client_id="sneaky").statement)
    assert made.manager_id == world["a"].id


# ------------------------------------- Nothing is shown that cannot be used


def test_the_audit_log_is_hidden_from_an_organisation_admin(world, principal_of, as_principal):
    """A link that only refuses when followed is not shown.

    The audit log is for NAAN level and above, so the link itself is hidden. Showing it
    would mean finding out only after a 403.
    """
    c = as_principal(principal_of(manager=world["a"]))
    home = c.get("/admin/").text
    assert "/admin/audit" not in home
    assert c.get("/admin/audit").status_code == 403   # asking directly is refused


def test_a_naan_administrator_is_shown_the_audit_log(world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.NAAN))
    assert "/admin/audit" in c.get("/admin/").text
    assert c.get("/admin/audit").status_code == 200


def test_a_principal_that_cannot_mint_is_not_offered_minting(world, principal_of, as_principal):
    """The scope decides, and the route uses the same decision as the display."""
    c = as_principal(principal_of(manager=world["a"], scopes=["ark:read"]))
    assert "/admin/mint" not in c.get("/admin/").text
    assert c.get("/admin/mint").status_code == 403


def test_a_principal_that_can_mint_is_offered_it(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"], scopes=["ark:mint"]))
    assert "/admin/mint" in c.get("/admin/").text
    assert c.get("/admin/mint").status_code == 200


def test_a_principal_with_no_organisation_is_not_offered_registration(
    world, principal_of, as_principal
):
    """With no organisation of its own, it cannot register anyone."""
    c = as_principal(principal_of(manager=None))
    assert "/admin/client/new" not in c.get("/admin/clients").text
    assert c.get("/admin/client/new").status_code == 403


def test_an_organisation_admin_is_offered_registration(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    assert "/admin/client/new" in c.get("/admin/clients").text
    assert c.get("/admin/client/new").status_code == 200


def test_every_link_on_the_page_actually_opens(world, principal_of, as_principal):
    """An exhaustive check that display and authorisation agree.

    Every link on the page is followed, and one refusal means the display is wrong.
    """
    import re

    for p in (principal_of(authority=Authority.SYSTEM),
              principal_of(authority=Authority.NAAN),
              principal_of(manager=world["a"])):
        c = as_principal(p)
        seen, todo = set(), ["/admin/", "/admin/clients"]
        while todo:
            path = todo.pop()
            if path in seen:
                continue
            seen.add(path)
            r = c.get(path)
            assert r.status_code == 200, f"{path} shown to {p.authority} gave {r.status_code}"
            for href in re.findall(r'href="(/admin/[^"?#]*)"', r.text):
                if href not in seen and not href.endswith(("logout", "login")):
                    todo.append(href)


# ------------------- Only offer credentials the configuration accepts


@pytest.fixture
def with_auth(app, settings, as_principal, principal_of):
    """Open the screens as the system administrator with ARKHE_AUTH replaced."""
    from arkhe.settings import get_settings

    def use(mechanisms):
        app.dependency_overrides[get_settings] = lambda: settings.model_copy(
            update={"auth": mechanisms}
        )
        return as_principal(principal_of(authority=Authority.SYSTEM))

    return use


def test_without_apikey_no_api_key_is_offered(db, world, root, with_auth):
    """Offering a credential that cannot be used is a button that does nothing.

    authenticate only tries the mechanisms listed in ARKHE_AUTH, so with apikey off, an
    API key issued here would work nowhere.
    """
    c = ops.register_client(db, root, client_id="m1", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    cli = with_auth(["oidc"])
    page = cli.get(f"/admin/client/{c.id}").text
    assert 'value="api_key"' not in page and 'value="client_secret"' not in page
    # The page explains that this deployment leans on an authorisation server
    assert "azp" in page
    # Going to the URL directly does not create one either
    assert cli.post(f"/admin/client/{c.id}/key", data={"kind": "api_key"}).status_code == 403
    db.expire_all()
    assert db.get(Client, c.id).credentials == []


def test_with_oauth2_a_client_secret_is_offered_too(db, world, root, with_auth):
    c = ops.register_client(db, root, client_id="m2", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    page = with_auth(["apikey", "oauth2"]).get(f"/admin/client/{c.id}").text
    assert 'value="api_key"' in page and 'value="client_secret"' in page


def test_with_neither_the_page_says_why(db, world, root, with_auth):
    """Not just an empty area: say what to change."""
    c = ops.register_client(db, root, client_id="m3", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    page = with_auth([]).get(f"/admin/client/{c.id}").text
    assert "ARKHE_AUTH" in page


def test_a_valid_token_fails_without_a_registration(db, world, root):
    """A registration is required.

    Authenticating at the authorisation server and being allowed to touch this namespace
    are different things, so a principal that is not in the ledger does not get in. The
    match is tried as azp, then client_id, then sub; see auth/oidc.py.
    """
    from arkhe.auth.errors import AuthError
    from arkhe.auth.oidc import OidcVerifier

    v = OidcVerifier.__new__(OidcVerifier)
    v.issuer = "https://kc.example.org/realms/arkhe"
    v.decode = lambda _t: {"azp": "nobody", "scope": "ark:mint"}
    with pytest.raises(AuthError, match="not registered"):
        v.authenticate(db, "dummy")


def test_the_same_token_works_once_registered(db, world, root):
    """Registering is the binding. No credential is issued; this alone lets it in."""
    from arkhe.auth.oidc import OidcVerifier

    ops.register_client(db, root, client_id="kc-repo", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    v = OidcVerifier.__new__(OidcVerifier)
    v.issuer = "https://kc.example.org/realms/arkhe"
    v.decode = lambda _t: {"azp": "kc-repo", "scope": "ark:mint"}
    p = v.authenticate(db, "dummy")
    assert p.client_id == "kc-repo" and p.has("ark:mint")


def test_with_an_authorisation_server_the_page_explains_registration(db, world, root, with_auth):
    """Say up front that this page binds an identity rather than issues a key."""
    page = with_auth(["oidc"]).get("/admin/client/new").text
    assert "azp" in page and "preferred_username" in page


def test_the_page_names_the_authorisation_server(
    db, world, root, app, settings, as_principal, principal_of
):
    """"Create it at the authorisation server" does not say which one."""
    from arkhe.settings import get_settings

    c = ops.register_client(db, root, client_id="kc-m", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(
        update={"auth": ["oidc"], "oidc_issuer": "https://kc.example.org/realms/arkhe"}
    )
    page = as_principal(principal_of(authority=Authority.SYSTEM)).get(
        f"/admin/client/{c.id}"
    ).text
    assert "https://kc.example.org/realms/arkhe" in page


# ---------------- Stopping a principal where an authorisation server is used


def test_with_oidc_there_has_to_be_a_way_to_stop_a_principal(db, world, root):
    """There is no credential, so revoke_credential has nothing to act on.

    Unless this stops it, tokens the authorisation server keeps issuing keep working.
    """
    from arkhe.auth.errors import AuthError
    from arkhe.auth.oidc import OidcVerifier

    c = ops.register_client(db, root, client_id="kc-stop", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    v = OidcVerifier.__new__(OidcVerifier)
    v.issuer = "https://kc.example.org/realms/arkhe"
    v.decode = lambda _t: {"azp": "kc-stop", "scope": "ark:mint"}
    assert v.authenticate(db, "t").client_id == "kc-stop"

    ops.set_client_active(db, root, client_pk=c.id, active=False)
    db.commit()
    # "Stopped", not "never registered". The answer is 401 either way, but the two
    # are kept apart so the disabled do not end up in the unregistered list.
    with pytest.raises(AuthError) as stopped:
        v.authenticate(db, "t")
    # The message that goes out is generic; the reason stays in detail for diagnosis.
    assert stopped.value.code.number == "ARKHE-1202"
    assert "not usable" in stopped.value.detail["reason"]


def test_a_stopped_principal_can_be_restored(db, world, root):
    c = ops.register_client(db, root, client_id="back", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    ops.set_client_active(db, root, client_pk=c.id, active=False)
    ops.set_client_active(db, root, client_pk=c.id, active=True)
    db.commit()
    assert c.active


def test_a_principal_of_a_departed_organisation_cannot_be_restored(db, world, root):
    """Restoring one principal must not hollow out the decision that minting has
    stopped."""
    from arkhe.domain.authz import Invalid

    c = ops.register_client(db, root, client_id="gone", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    ops.depart(db, root, manager_id=world["a"].id)
    db.commit()
    assert not c.active
    with pytest.raises(Invalid):
        ops.set_client_active(db, root, client_pk=c.id, active=True)


def test_a_principal_can_be_stopped_from_the_screen(db, world, root, principal_of, as_principal):
    c = ops.register_client(db, root, client_id="ui-stop", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    assert cli.post(f"/admin/client/{c.id}/active", data={"active": ""}).status_code == 303
    db.expire_all()
    assert not db.get(Client, c.id).active


def test_another_organisations_principal_cannot_be_stopped(
    db, world, root, principal_of, as_principal
):
    c = ops.register_client(db, root, client_id="other-stop", naan="99999",
                            manager_id=world["b"].id, scopes="ark:mint")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    assert cli.post(f"/admin/client/{c.id}/active", data={"active": ""}).status_code == 403
    db.expire_all()
    assert db.get(Client, c.id).active


# ------------------------------------------- Choosing the kind of credential


def test_the_kinds_offered_follow_the_configuration(db, world, root, with_auth):
    """With two mechanisms enabled, both kinds can be chosen."""
    c = ops.register_client(db, root, client_id="k2", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    page = with_auth(["apikey", "oauth2"]).get(f"/admin/client/{c.id}").text
    assert 'value="api_key"' in page and 'value="client_secret"' in page
    # With both available, the note explaining why only one is offered is absent.
    # ARKHE_AUTH appears in other notes, so this looks for that note itself.
    assert "one-kind" not in page


def test_when_only_one_kind_is_offered_the_page_says_why(db, world, root, with_auth):
    """Not a blank space: say what to add."""
    c = ops.register_client(db, root, client_id="k1", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    page = with_auth(["apikey"]).get(f"/admin/client/{c.id}").text
    assert 'value="client_secret"' not in page
    assert "one-kind" in page and "oauth2" in page


def test_the_type_field_suggests_values_without_restricting_them(world, principal_of, as_principal):
    """The ERC what element defines no vocabulary, so the screen must not impose
    one."""
    c = as_principal(principal_of(manager=world["a"]))
    page = c.get("/admin/mint").text
    assert "<datalist" in page and 'value="Dataset"' in page
    # It is not a select, so a value outside the list can be sent
    free = c.post("/admin/mint", data={"url": "https://x/1", "type": "anything at all"})
    assert free.status_code == 200


def test_a_type_outside_the_list_is_stored(db, world, principal_of, as_principal):
    from arkhe.db.models import Ark

    c = as_principal(principal_of(manager=world["a"]))
    c.post("/admin/mint", data={"url": "https://x/2", "type": "our own category"})
    saved = db.scalars(db.query(Ark).filter_by(type="our own category").statement).all()
    assert saved, "a type outside the list was not stored"


# ------------------------------- The screen shows how a principal gets in


def test_a_machine_using_the_server_does_not_look_unconfigured(db, world, root, with_auth):
    """A count of credentials makes a correctly configured principal look unfinished.

    With oidc alone, machines hold no credentials either. The screen says the
    authorisation server rather than "0 credentials".
    """
    from arkhe.api import i18n

    ops.register_client(db, root, client_id="idp-only", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    page = with_auth(["oidc"]).get("/admin/clients").text
    assert 'data-entry="idp"' in page
    assert "0 " + i18n.JA["cl.live"] not in page


def test_a_machine_with_a_key_is_shown_as_having_one(db, world, root, with_auth):

    c = ops.register_client(db, root, client_id="with-key", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    ops.issue_credential(db, root, client_pk=c.id)
    db.commit()
    assert 'data-entry="key"' in with_auth(["apikey"]).get("/admin/clients").text


def test_something_really_unconfigured_is_shown_as_such(db, world, root, with_auth):
    """"Delegated to the authorisation server" and "cannot get in yet" are not the
    same."""

    c = ops.register_client(db, root, client_id="nothing", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    cli = with_auth(["apikey"])          # no oidc and no key, so no way in
    assert 'data-entry="none"' in cli.get("/admin/clients").text
    # The detail page says what to do about it
    assert "ARKHE_AUTH" in cli.get(f"/admin/client/{c.id}").text


def test_a_stopped_principal_is_refused_whatever_the_route(db, world, root):
    """What the screen says about the route is a description, not the
    authorisation."""
    from arkhe.auth.errors import AuthError
    from arkhe.auth.oidc import OidcVerifier

    c = ops.register_client(db, root, client_id="idp-stop", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    ops.set_client_active(db, root, client_pk=c.id, active=False)
    db.commit()
    v = OidcVerifier.__new__(OidcVerifier)
    v.issuer = "https://kc.example.org/realms/arkhe"
    v.decode = lambda _t: {"azp": "idp-stop", "scope": "ark:mint"}
    with pytest.raises(AuthError):
        v.authenticate(db, "t")


def test_a_key_for_a_disabled_mechanism_does_not_count(db, world, root, with_auth):
    """Showing a key that cannot be used would be untrue.

    An old API key left behind in an oidc-only deployment is exactly that.
    """

    c = ops.register_client(db, root, client_id="stale-key", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    ops.issue_credential(db, root, client_pk=c.id)   # api_key
    db.commit()
    page = with_auth(["oidc"]).get(f"/admin/client/{c.id}").text
    # Look at the marker rather than the wording, which also appears in headings
    assert 'data-entry="idp"' in page
    assert 'data-entry="key"' not in page


def test_the_page_does_not_claim_the_client_exists_there(db, world, root, with_auth):
    """arkhe never asks the authorisation server.

    Claiming that a principal can get in would make one with no client over there look
    finished. The page states what is delegated and where to check.
    """

    c = ops.register_client(db, root, client_id="not-in-kc", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    page = with_auth(["oidc"]).get(f"/admin/client/{c.id}").text
    assert 'data-entry="idp"' in page
    # The Japanese wording is written as an escape: it is text from the Japanese UI.
    assert "arkhe \u304b\u3089\u306f\u5206\u304b\u308a\u307e\u305b\u3093" in page \
        or "not something arkhe" in page


# ------------------------------------------------------- Choosing the scopes


def test_scopes_are_chosen_with_checkboxes(world, principal_of, as_principal):
    """Free text would let an unchecked spelling into the ledger."""
    from arkhe.domain.authz import SCOPES

    page = as_principal(principal_of(manager=world["a"])).get("/admin/client/new").text
    for sc in SCOPES:
        assert f'value="{sc}"' in page
    assert '<input id="scopes"' not in page      # no free-text field left


def test_only_the_chosen_scopes_are_stored(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    c.post("/admin/client/new", data={
        "client_id": "picked", "scopes": ["ark:mint", "ark:tombstone"]})
    made = db.scalar(db.query(Client).filter_by(client_id="picked").statement)
    assert set(made.allowed_scopes.split()) == {"ark:mint", "ark:tombstone"}


def test_anything_outside_the_vocabulary_is_dropped(db, world, principal_of, as_principal):
    """A value that was never offered is not used."""
    c = as_principal(principal_of(manager=world["a"]))
    c.post("/admin/client/new", data={
        "client_id": "sneaky-scope", "scopes": ["ark:mint", "ark:everything"]})
    made = db.scalar(db.query(Client).filter_by(client_id="sneaky-scope").statement)
    assert made.allowed_scopes == "ark:mint"


def test_choosing_nothing_leaves_the_minimum(db, world, principal_of, as_principal):
    """Registering with nothing would create a principal that can do nothing, so
    minting is kept."""
    c = as_principal(principal_of(manager=world["a"]))
    c.post("/admin/client/new", data={"client_id": "nothing-picked"})
    made = db.scalar(db.query(Client).filter_by(client_id="nothing-picked").statement)
    assert made.allowed_scopes == "ark:mint"


# ------------- Principals an organisation admin creates stay in that organisation


def test_they_cannot_be_pinned_to_another_organisations_shoulder(
    db, world, principal_of, as_principal
):
    """Sending a shoulder_id that was never offered does not work."""
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/admin/client/new", data={
        "client_id": "cross-shoulder", "shoulder_id": str(world["sh_b"].id),
        "scopes": ["ark:mint"]})
    assert r.status_code in (400, 403)
    assert db.scalar(db.query(Client).filter_by(client_id="cross-shoulder").statement) is None


def test_they_cannot_belong_to_another_organisation(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    c.post("/admin/client/new", data={
        "client_id": "cross-org", "manager_id": str(world["b"].id), "scopes": ["ark:mint"]})
    made = db.scalar(db.query(Client).filter_by(client_id="cross-org").statement)
    assert made.manager_id == world["a"].id      # falls back to their own


def test_they_cannot_be_created_under_another_naan(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/admin/client/new", data={
        "client_id": "cross-naan", "naan": "88888", "scopes": ["ark:mint"]})
    assert r.status_code == 403
    assert db.scalar(db.query(Client).filter_by(client_id="cross-naan").statement) is None


def test_they_cannot_be_given_a_wider_authority(db, world, principal_of, as_principal):
    """Sending authority=naan or system does not widen anything.

    The route does not accept the field at all, so it is dropped. Having no entrance is
    surer than refusing at one.
    """
    c = as_principal(principal_of(manager=world["a"]))
    for auth in ("naan", "system"):
        c.post("/admin/client/new", data={
            "client_id": f"climb-{auth}", "authority": auth, "scopes": ["ark:mint"]})
        made = db.scalar(db.query(Client).filter_by(client_id=f"climb-{auth}").statement)
        assert made is not None and made.authority == "manager", auth


def test_the_principal_created_can_only_mint_in_its_own_organisation(
    db, world, root, principal_of, as_principal
):
    """Not only registration but minting stays inside the organisation."""
    from arkhe.auth.errors import Forbidden
    from arkhe.domain import authz

    cli = as_principal(principal_of(manager=world["a"]))
    cli.post("/admin/client/new", data={"client_id": "org-repo", "scopes": ["ark:mint"]})
    made = db.scalar(db.query(Client).filter_by(client_id="org-repo").statement)

    p = principal_of(manager=world["a"], client_id="org-repo")
    # Omitted, it uses the organisation default
    assert authz.shoulder_for(db, p, None).manager_id == world["a"].id
    # Naming another organisation's shoulder does not work
    with pytest.raises(Forbidden):
        authz.shoulder_for(db, p, world["sh_b"].shoulder)
    assert made.manager_id == world["a"].id


# --------------------- What an organisation is trusted with, and what is limited


def test_a_mechanism_that_is_not_allowed_does_not_authenticate(db, world, root):
    """Stopping new credentials is not enough.

    Keys issued before the restriction would survive, and keep working while everyone
    believes the restriction is in force. It applies at authentication too.
    """
    from arkhe.auth import apikey
    from arkhe.auth.errors import AuthError

    c = ops.register_client(db, root, client_id="pre-key", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    issued = ops.issue_credential(db, root, client_pk=c.id)
    db.commit()
    assert apikey.authenticate(db, issued.secret).client_id == "pre-key"

    ops.set_org_policy(db, root, manager_id=world["a"].id, mechanisms=["oidc"])
    db.commit()
    with pytest.raises(AuthError):
        apikey.authenticate(db, issued.secret)


def test_no_credential_is_issued_for_a_mechanism_that_is_not_allowed(db, world, root):
    from arkhe.domain.authz import Invalid

    c = ops.register_client(db, root, client_id="no-key", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    ops.set_org_policy(db, root, manager_id=world["a"].id, mechanisms=["oidc"])
    db.commit()
    with pytest.raises(Invalid):
        ops.issue_credential(db, root, client_pk=c.id)


def test_self_registration_can_be_turned_off(db, world, root, principal_of, as_principal):
    from arkhe.auth.errors import Forbidden

    ops.set_org_policy(db, root, manager_id=world["a"].id, may_self_register=False)
    db.commit()
    with pytest.raises(Forbidden):
        ops.register_client(db, principal_of(manager=world["a"]), client_id="blocked",
                            naan="99999", manager_id=world["a"].id, scopes="ark:mint")
    # Whoever hands out the namespace can still create one
    ops.register_client(db, root, client_id="by-naan", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint")
    db.commit()

    # The screen does not offer it either
    cli = as_principal(principal_of(manager=world["a"]))
    assert "/admin/client/new" not in cli.get("/admin/clients").text


def test_the_scope_ceiling_cannot_be_exceeded(db, world, root, principal_of):
    """It holds whoever creates the principal. To make an exception, move the
    ceiling."""
    from arkhe.domain.authz import Invalid

    ops.set_org_policy(db, root, manager_id=world["a"].id,
                       max_scopes=["ark:mint", "ark:update"])
    db.commit()
    with pytest.raises(Invalid):
        ops.register_client(db, principal_of(manager=world["a"]), client_id="over",
                            naan="99999", manager_id=world["a"].id,
                            scopes="ark:mint ark:tombstone")
    # The same for whoever hands out the namespace: nothing above the stated ceiling
    with pytest.raises(Invalid):
        ops.register_client(db, root, client_id="over2", naan="99999",
                            manager_id=world["a"].id, scopes="ark:tombstone")


def test_an_organisation_cannot_lift_its_own_restrictions(db, world, root, principal_of):
    from arkhe.auth.errors import Forbidden

    ops.set_org_policy(db, root, manager_id=world["a"].id, mechanisms=["oidc"],
                       may_self_register=False, max_scopes=["ark:mint"])
    db.commit()
    p = principal_of(manager=world["a"])
    for kw in ({"mechanisms": []}, {"may_self_register": True}, {"max_scopes": []}):
        with pytest.raises(Forbidden):
            ops.set_org_policy(db, p, manager_id=world["a"].id, **kw)


def test_restrictions_can_be_set_from_the_screen(db, world, principal_of, as_principal):
    from arkhe.db.models import Manager

    c = as_principal(principal_of(authority=Authority.NAAN))
    r = c.post(f"/admin/manager/{world['a'].id}", data={
        "commitment": "", "quota": "", "policy": "1",
        "allowed_auth": ["oidc"], "self_register": "", "max_scopes": ["ark:mint"]})
    assert r.status_code == 303
    db.expire_all()
    m = db.get(Manager, world["a"].id)
    assert m.allowed_auth == "oidc" and not m.may_self_register and m.max_scopes == "ark:mint"


def test_a_form_without_those_fields_does_not_clear_them(
    db, world, root, principal_of, as_principal
):
    """Saving as the organisation must not wipe restrictions set from above."""
    from arkhe.db.models import Manager

    ops.set_org_policy(db, root, manager_id=world["a"].id, mechanisms=["oidc"])
    db.commit()
    c = as_principal(principal_of(manager=world["a"]))
    c.post(f"/admin/manager/{world['a'].id}", data={"commitment": "permanent-stable"})
    db.expire_all()
    assert db.get(Manager, world["a"].id).allowed_auth == "oidc"


def test_the_caller_address_is_kept_in_the_audit_log(db, world, principal_of, as_principal):
    """The address carried on the principal reaches the audit row.

    Where it is recorded, in the request layer, is covered by test_admin.py: here
    authentication is substituted, so that step does not run.
    """
    from dataclasses import replace

    from arkhe.db.models import AuditEvent

    p = replace(principal_of(authority=Authority.NAAN), ip="198.51.100.7")
    as_principal(p).post(f"/admin/manager/{world['a'].id}",
                         data={"commitment": "permanent-stable"})
    ev = db.scalars(db.query(AuditEvent).filter_by(action="set_commitment").statement).all()
    assert ev and ev[-1].ip == "198.51.100.7"


def test_the_audit_page_shows_the_caller_address(world, principal_of, as_principal):
    from arkhe.api import i18n

    c = as_principal(principal_of(authority=Authority.NAAN))
    c.post(f"/admin/manager/{world['a'].id}", data={"commitment": "permanent-stable"})
    page = c.get("/admin/audit").text
    assert i18n.JA["au.ip"] in page
    assert "X-Forwarded-For" in page or "x-forwarded-for" in page.lower()


# -------------------------------------------------- Listing minted ARKs


@pytest.fixture
def minted(db, world, root):
    """One ARK in each of three organisations, so that reach can be checked."""
    from arkhe.domain import minting

    made = {}
    for key in ("a", "b", "c"):
        sh = world[key].default_shoulder
        ark, _ = minting.mint(db, shoulder=sh, created_by=f"{key}-repo",
                              url=f"https://{key}.example.org/1", title=f"object of {key}")
        made[key] = ark
    db.commit()
    return made


def test_the_system_administrator_sees_every_ark(minted, principal_of, as_principal):
    page = as_principal(principal_of(authority=Authority.SYSTEM)).get("/admin/arks").text
    for a in minted.values():
        assert a.ark in page


def test_a_naan_administrator_sees_only_that_naan(minted, world, principal_of, as_principal):
    page = as_principal(principal_of(authority=Authority.NAAN, naan="99999")).get(
        "/admin/arks").text
    assert minted["a"].ark in page and minted["b"].ark in page
    assert minted["c"].ark not in page      # another NAAN


def test_an_organisation_admin_sees_only_its_own(minted, world, principal_of, as_principal):
    page = as_principal(principal_of(manager=world["a"])).get("/admin/arks").text
    assert minted["a"].ark in page
    assert minted["b"].ark not in page      # another organisation, same NAAN
    assert minted["c"].ark not in page


def test_a_pinned_principal_sees_only_that_shoulder(
    db, world, root, minted, principal_of, as_principal
):
    """What can be minted and what can be seen are narrowed the same way."""
    from arkhe.domain import minting

    other, _ = minting.mint(db, shoulder=world["sh_b"], created_by="x", url="https://x/9")
    db.commit()
    p = principal_of(manager=world["a"], shoulder=world["sh_a"])
    page = as_principal(p).get("/admin/arks").text
    assert minted["a"].ark in page and other.ark not in page


def test_searching_does_not_widen_the_reach(minted, world, principal_of, as_principal):
    """A filter must never surface another organisation's rows."""
    page = as_principal(principal_of(manager=world["a"])).get(
        "/admin/arks?q=example.org").text
    assert minted["a"].ark in page
    assert minted["b"].ark not in page and minted["c"].ark not in page


def test_the_list_is_paginated(db, world, root, principal_of, as_principal):
    """The count only grows; a page that simply lists everything stops being
    usable."""
    from arkhe.api.admin import PAGE
    from arkhe.domain import minting

    for i in range(PAGE + 3):
        minting.mint(db, shoulder=world["a"].default_shoulder, created_by="bulk",
                     url=f"https://bulk.example.org/{i}")
    db.commit()
    c = as_principal(principal_of(manager=world["a"]))
    first = c.get("/admin/arks").text
    assert first.count("ark:") >= PAGE
    assert "page=2" in first                       # there is a next page
    assert c.get("/admin/arks?page=2").status_code == 200


def test_another_organisations_history_cannot_be_opened(
    db, world, minted, principal_of, as_principal
):
    """Something absent from the list must not be reachable by typing the URL.

    This checks that the detail page shares the list's reach.
    """
    c = as_principal(principal_of(manager=world["a"]))
    assert c.get(f"/admin/arks/{minted['a'].ark}").status_code == 200
    assert c.get(f"/admin/arks/{minted['b'].ark}").status_code == 403
    assert c.get(f"/admin/arks/{minted['c'].ark}").status_code == 403


def test_the_history_is_visible_on_the_screen(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://one.example/1"}).json()["ark"]
    c.put("/api/update", json={"ark": key, "url": "https://two.example/2"})
    page = c.get("/admin/arks/" + key.removeprefix("ark:")).text
    assert "https://one.example/1" in page and "https://two.example/2" in page


# --------------------- Still usable as things grow: search and pagination


def test_the_principal_list_is_paginated(db, world, root, principal_of, as_principal):
    """Listing everything stops working once there is a lot of it."""
    from arkhe.api.admin import PAGE

    for i in range(PAGE + 2):
        ops.register_client(db, root, client_id=f"bulk-{i:03}", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    c = as_principal(principal_of(manager=world["a"]))
    first = c.get("/admin/clients").text
    assert "page=2" in first
    assert c.get("/admin/clients?page=2").status_code == 200


def test_principals_can_be_searched(db, world, root, principal_of, as_principal):
    ops.register_client(db, root, client_id="findme-repo", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint")
    ops.register_client(db, root, client_id="other-repo", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    page = as_principal(principal_of(manager=world["a"])).get(
        "/admin/clients?q=findme").text
    assert "findme-repo" in page and "other-repo" not in page


def test_searching_principals_does_not_widen_the_reach(db, world, root, principal_of, as_principal):
    """A filter must never surface another organisation's rows."""
    ops.register_client(db, root, client_id="b-secret", naan="99999",
                        manager_id=world["b"].id, scopes="ark:mint")
    db.commit()
    page = as_principal(principal_of(manager=world["a"])).get(
        "/admin/clients?q=secret").text
    assert "b-secret" not in page


def test_the_audit_log_is_paginated(db, world, principal_of, as_principal):
    """Capped at the most recent 200, there was no way to see anything older."""
    from arkhe.api.admin import PAGE

    c = as_principal(principal_of(authority=Authority.NAAN))
    for _ in range(PAGE + 2):
        c.post(f"/admin/manager/{world['a'].id}", data={"commitment": "permanent-stable"})
    first = c.get("/admin/audit").text
    assert "page=2" in first
    assert c.get("/admin/audit?page=2").status_code == 200


def test_the_audit_log_can_be_searched(db, world, principal_of, as_principal):
    """Look at the rows themselves: set_commitment also appears as an example in a
    form field, so searching the whole page would match that."""
    import re

    def rows(html):
        return re.findall(r'data-label="[^"]*">([^<]*set_commitment[^<]*)<', html)

    c = as_principal(principal_of(authority=Authority.NAAN))
    c.post(f"/admin/manager/{world['a'].id}", data={"commitment": "permanent-stable"})
    assert rows(c.get("/admin/audit?q=set_commit").text)
    assert not rows(c.get("/admin/audit?q=nothing-matches-this").text)


def test_the_counts_on_the_list_cover_only_what_is_visible(db, world, principal_of, as_principal):
    """This used to aggregate the whole ark table on every request.

    ARKs only accumulate, so opening the page meant a full scan each time. The queries
    issued are inspected to confirm they are narrowed by reach.
    """
    seen = []

    from sqlalchemy import event

    engine = db.get_bind()

    def spy(conn, cursor, statement, params, context, many):  # noqa: ARG001
        if "count(" in statement.lower() and " ark" in statement.lower():
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", spy)
    try:
        as_principal(principal_of(manager=world["a"])).get("/admin/")
    finally:
        event.remove(engine, "before_cursor_execute", spy)

    assert seen, "no aggregate query was issued"
    assert any("shoulder_id IN" in s or "shoulder_id in" in s for s in seen), (
        "the aggregate is not narrowed by reach"
    )


def test_the_ark_list_can_be_filtered_by_organisation(minted, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.NAAN))
    both = c.get("/admin/arks").text
    assert minted["a"].ark in both and minted["b"].ark in both
    only_a = c.get(f"/admin/arks?org={world['a'].id}").text
    assert minted["a"].ark in only_a and minted["b"].ark not in only_a


def test_a_filter_does_not_widen_the_reach(minted, world, principal_of, as_principal):
    """Naming an organisation out of reach returns nothing."""
    c = as_principal(principal_of(manager=world["a"]))
    page = c.get(f"/admin/arks?org={world['b'].id}").text
    assert minted["b"].ark not in page and minted["a"].ark not in page


def test_an_organisation_admin_is_not_shown_the_filter(minted, world, principal_of, as_principal):
    """Only one organisation is visible, so a filter with one choice adds work."""
    page = as_principal(principal_of(manager=world["a"])).get("/admin/arks").text
    assert 'name="org"' not in page


def test_the_ark_detail_page_shows_the_description(db, world, principal_of, as_principal):
    """This is what ? and ?? publish, so the screen and the public face can be
    compared."""
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={
        "url": "https://x/1", "title": "a title", "who": "an author", "when": "2026",
        "type": "Dataset", "source": "somewhere",
    }).json()["ark"].removeprefix("ark:")
    page = c.get(f"/admin/arks/{key}").text
    for v in ("a title", "an author", "2026", "Dataset", "somewhere"):
        assert v in page, v


def test_no_markdown_is_left_in_the_wording():
    """The translations are rendered as HTML. Backticks and asterisks written as they
    are would appear on the screen, which happened more than once.
    """
    from arkhe.api import i18n

    for lang, cat in i18n.CATALOGS.items():
        for key, value in cat.items():
            assert "`" not in value, f"{lang}/{key}: use <code> instead of a backtick"
            assert "**" not in value, f"{lang}/{key}: use <b> instead of asterisks"


def test_each_file_has_the_same_keys_in_both_languages():
    """The Japanese and English keys match within each file.

    A missing key overall fails at startup, but that is the last line of defence, not
    the first. Matching per file means a one-sided addition shows up in that diff.
    """
    from arkhe.api import i18n

    for part in i18n._PARTS:
        only_ja = sorted(set(part.JA) - set(part.EN))
        only_en = sorted(set(part.EN) - set(part.JA))
        assert not only_ja and not only_en, (
            f"{part.__name__}: only in Japanese={only_ja} only in English={only_en}"
        )


def test_restrictions_can_be_set_while_onboarding(db, world, principal_of, as_principal):
    """Left until later, some of them are never applied."""
    from arkhe.db.models import Manager

    c = as_principal(principal_of(authority=Authority.NAAN))
    r = c.post("/admin/manager/new", data={
        "naan": "99999", "name": "a new organisation", "shoulder": "/n1",
        "commitment": "permanent-stable", "quota": "",
        "policy": "1", "allowed_auth": ["oidc"], "self_register": "",
        "max_scopes": ["ark:mint"],
    })
    assert r.status_code == 303
    m = db.scalar(db.query(Manager).filter_by(name="a new organisation").statement)
    assert m.allowed_auth == "oidc"
    assert not m.may_self_register
    assert m.max_scopes == "ark:mint"


def test_the_restriction_fields_are_hidden_from_an_organisation_admin(
    world, principal_of, as_principal
):
    """Better to show that it is not theirs to decide than to show a control that
    does nothing."""
    from arkhe.api import i18n

    page = as_principal(principal_of(manager=world["a"])).get(
        f"/admin/manager/{world['a'].id}").text
    assert i18n.JA["op.title"] not in page
    # The commitment level, which is theirs, is shown
    assert i18n.JA["manager.f.commitment"] in page


# ------------- Rules for a namespace, and how an organisation narrows them


def test_a_namespace_rule_applies_to_everything_under_it(db, world, root):
    """The rule belongs to the NAAN. Applying it per organisation does not scale."""
    from arkhe.domain.authz import Invalid

    ops.set_naan_policy(db, root, naan="99999", max_scopes=["ark:mint"])
    db.commit()
    # The organisation set nothing, and the ceiling still applies
    with pytest.raises(Invalid):
        ops.register_client(db, root, client_id="over-naan", naan="99999",
                            manager_id=world["a"].id, scopes="ark:tombstone")


def test_an_organisation_can_narrow_but_not_widen(db, world, root):
    from arkhe.db.models import Naan
    from arkhe.domain.admin_ops import policy_for

    ops.set_naan_policy(db, root, naan="99999", max_scopes=["ark:mint", "ark:update"])
    ops.set_org_policy(db, root, manager_id=world["a"].id, max_scopes=["ark:mint"])
    ops.set_org_policy(db, root, manager_id=world["b"].id,
                       max_scopes=["ark:mint", "ark:update", "ark:tombstone"])
    db.commit()
    naan = db.get(Naan, "99999")
    # Narrowing takes effect
    assert policy_for(naan, world["a"]).max_scopes == "ark:mint"
    # Widening cannot reach past what the NAAN allows
    assert set(policy_for(naan, world["b"]).max_scopes.split()) == {"ark:mint", "ark:update"}


def test_self_registration_needs_the_naan_to_allow_it(db, world, root):
    from arkhe.db.models import Naan
    from arkhe.domain.admin_ops import policy_for

    ops.set_naan_policy(db, root, naan="99999", may_self_register=False)
    ops.set_org_policy(db, root, manager_id=world["a"].id, may_self_register=True)
    db.commit()
    assert not policy_for(db.get(Naan, "99999"), world["a"]).may_self_register


def test_a_namespace_rule_applies_at_authentication_too(db, world, root):
    """Looking only at the organisation would let the namespace default slip."""
    from arkhe.auth import apikey
    from arkhe.auth.errors import AuthError

    c = ops.register_client(db, root, client_id="naan-wide-stop", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    issued = ops.issue_credential(db, root, client_pk=c.id)
    db.commit()
    assert apikey.authenticate(db, issued.secret).client_id == "naan-wide-stop"

    ops.set_naan_policy(db, root, naan="99999", mechanisms=["oidc"])
    db.commit()
    with pytest.raises(AuthError):
        apikey.authenticate(db, issued.secret)


def test_the_rules_can_be_set_from_the_naan_screen(db, world, principal_of, as_principal):
    from arkhe.db.models import Naan

    c = as_principal(principal_of(authority=Authority.NAAN))
    r = c.post("/admin/naan/99999", data={
        "policy": "NP | NR", "minter": "", "rules": "1",
        "allowed_auth": ["oidc"], "self_register": "", "max_scopes": ["ark:mint"],
    })
    assert r.status_code == 303
    db.expire_all()
    n = db.get(Naan, "99999")
    assert n.allowed_auth == "oidc" and not n.may_self_register
    assert n.max_scopes == "ark:mint" and n.na_policy == "NP | NR"


# --------------- Principals from the authorisation server with no registration
#
# One wrong character means 401, which is the most common way this setup gets stuck,
# and it fails silently. At the moment of refusal the exact string is in hand, so it is
# kept rather than thrown away, and nobody has to type it again.


@contextmanager
def _oidc_says(subject: str, issuer: str = "https://kc.example.org/realms/arkhe"):
    """Set up the situation where the authorisation server issued a token for this
    principal.

    Only signature verification is substituted. Matching against the ledger and the
    recording are real, because that is what is being looked at.
    """
    from arkhe.auth import deps
    from arkhe.auth.oidc import OidcVerifier

    v = OidcVerifier.__new__(OidcVerifier)
    v.issuer = issuer
    v.decode = lambda _t: {"azp": subject, "scope": "ark:mint"}
    orig = deps.oidc_verifier
    deps.oidc_verifier = lambda _s: v
    try:
        yield deps
    finally:
        deps.oidc_verifier = orig


def _reject(db, subject, ip="", issuer="https://kc.example.org/realms/arkhe"):
    """Have it refused as unregistered, returning the AuthError that was raised."""
    from arkhe.auth.errors import AuthError
    from arkhe.settings import Settings

    cfg = Settings(auth=["oidc"], oidc_issuer=issuer, database_url="sqlite://")
    with _oidc_says(subject, issuer) as deps, pytest.raises(AuthError) as e:
        deps.authenticate("dummy", db, cfg, ip)
    return e.value


def test_an_unregistered_principal_is_recorded_with_its_identifier(db, world):
    """Keep the exact string, so it can be registered without retyping."""
    from arkhe.db.models import UnknownSubject

    _reject(db, "example-invenoi", ip="10.0.0.9")  # misspelt

    row = db.scalar(db.query(UnknownSubject).statement)
    assert row.subject == "example-invenoi"
    assert row.issuer == "https://kc.example.org/realms/arkhe"
    assert row.seen == 1 and row.ip == "10.0.0.9"


def test_the_same_principal_bumps_a_counter_instead_of_adding_rows(db, world):
    """The table is bounded by the number of clients at the authorisation server; it
    does not grow without limit."""
    from arkhe.db.models import UnknownSubject

    for _ in range(3):
        _reject(db, "example-invenoi")

    rows = list(db.scalars(db.query(UnknownSubject).statement))
    assert len(rows) == 1 and rows[0].seen == 3


def test_a_401_is_still_a_401(db, world):
    """The record is a convenience for operators, not part of the decision.

    The reason returned is not expanded either, so nothing reveals which principals are
    in the ledger.
    """
    rejected = _reject(db, "nobody")
    assert rejected.code.number == "ARKHE-1202" and rejected.detail == {}


def test_registering_removes_it_from_the_list(db, world, root, principal_of, as_principal):
    """Nothing sweeps the table. The match is made on each request, so nothing is left
    behind."""
    from arkhe.api import i18n

    _reject(db, "kc-repo")
    c = as_principal(principal_of(authority=Authority.NAAN))
    page = c.get("/admin/clients").text
    assert "kc-repo" in page
    # No retyping: the identifier is carried from the list into the registration form.
    assert "/admin/client/new?client_id=kc-repo" in page

    ops.register_client(db, root, client_id="kc-repo", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    assert i18n.JA["uk.title"] not in c.get("/admin/clients").text


def test_an_organisation_admin_is_not_shown_the_list(db, world, root, principal_of, as_principal):
    """There is no telling which organisation they belong to, so showing the list
    would mix in another organisation's client ids."""
    from arkhe.api import i18n

    _reject(db, "something-from-elsewhere")
    page = as_principal(principal_of(manager=world["a"])).get("/admin/clients").text
    assert i18n.JA["uk.title"] not in page and "something-from-elsewhere" not in page


def test_the_registration_form_opens_with_the_identifier_filled_in(
    db, world, principal_of, as_principal
):
    """No retyping: the value the authorisation server signed becomes the default."""
    c = as_principal(principal_of(authority=Authority.NAAN))
    page = c.get("/admin/client/new", params={"client_id": "example-invenoi"}).text
    assert 'value="example-invenoi"' in page


def test_a_stopped_principal_is_not_listed_as_unregistered(db, world, root):
    """Something stopped on purpose is not mixed in with what was forgotten.

    Mixed together, clearing the list would mean registering it again, which undoes the
    stopping. The answer is 401 either way; only the record differs.
    """
    from arkhe.db.models import UnknownSubject

    c = ops.register_client(db, root, client_id="kc-stopped", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    ops.set_client_active(db, root, client_pk=c.id, active=False)
    db.commit()

    stopped = _reject(db, "kc-stopped")
    assert stopped.code.number == "ARKHE-1202" and stopped.detail == {}
    assert db.scalar(db.query(UnknownSubject).statement) is None


# --------------------------------------------------------------------------
# Refusals come back in the language of the screen
# --------------------------------------------------------------------------


def test_a_refusal_comes_back_in_the_screen_language(db, world, root, principal_of, as_principal):
    """A screen that switches languages while its refusals do not drops the reader out
    of their own language exactly when they are stuck.

    The wording comes from the same catalogue as the screens, so a gap fails at startup.
    """
    c = as_principal(principal_of(manager=world["a"]))  # organisation level: no NAAN admin

    ja = c.get("/admin/naan/new?lang=ja")
    en = c.get("/admin/naan/new?lang=en")
    assert ja.status_code == en.status_code == 403
    # The Japanese wording is written as an escape: it comes from the Japanese UI.
    assert ja.json()["detail"] == (
        "NAAN \u306e\u767b\u9332\u306f\u30b7\u30b9\u30c6\u30e0\u7ba1\u7406\u8005\u306e\u307f"
    )
    assert en.json()["detail"] == "Only a system administrator registers a NAAN."

    # Accept-Language switches it too, when no explicit ?lang= is given.
    header = c.get("/admin/naan/new", headers={"Accept-Language": "en-GB,en;q=0.9"})
    assert header.json()["detail"].startswith("Only a system administrator")


def test_a_login_refusal_also_comes_back_in_that_language(db, root, factory):
    """auth/password.py raises with a catalogue key: that layer knows nothing about
    the request or the language."""
    from arkhe.api.i18n import EN, JA

    for key in ("e.bad_credentials", "e.locked", "e.password_expired"):
        assert JA[key] and EN[key] and JA[key] != EN[key]
