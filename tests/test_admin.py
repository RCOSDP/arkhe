"""The admin interface and the operations behind it.

What the screens show and what is actually authorised go through the same decision.
Keeping them apart creates the hole where the button is hidden but the URL still
works.
"""

from __future__ import annotations

import pytest

from arkhe.auth.errors import Forbidden
from arkhe.db.models import Authority, Client, ShoulderStatus
from arkhe.domain import admin_ops as ops
from arkhe.domain.authz import Invalid

# ------------------------------------------------------- Transitions that are refused


def test_a_retired_namespace_cannot_be_reopened(db, world, root):
    """Reopening a retired namespace is how an NR violation starts: we cannot rule out
    that the same name was used elsewhere in the meantime."""
    ops.set_shoulder_status(db, root, shoulder_id=world["sh_a"].id, status="retired")
    db.commit()
    with pytest.raises(Invalid) as e:
        ops.set_shoulder_status(db, root, shoulder_id=world["sh_a"].id, status="active")
    assert "retired" in e.value.detail["reason"]


def test_delegation_does_not_require_a_minter_url(db, world, root):
    """Delegating records that we do not mint here; it does not announce where minting
    happens.

    In a closed network there is nothing to announce. Requiring a URL would only produce
    invented values, an internal host name or a page for people, put there to satisfy
    the constraint. The guide suggested exactly that for a while.
    """
    sh = ops.set_shoulder_status(db, root, shoulder_id=world["sh_a"].id, status="delegated")
    db.commit()
    assert sh.status == ShoulderStatus.DELEGATED
    assert sh.minter == "" and sh.about == ""

    # Record it when there is an endpoint to call. It can be added later.
    ops.set_shoulder_status(
        db, root, shoulder_id=world["sh_a"].id, status="delegated",
        minter="https://mint.example.org",
    )
    db.commit()
    assert world["sh_a"].minter == "https://mint.example.org"


def test_an_organisation_and_its_namespace_are_created_together(db, world):
    """One without the other is useless: an organisation that cannot mint."""
    assert world["a"].default_shoulder_id == world["sh_a"].id


# --------------------------------------------------------- The tiers of authority


def test_only_the_system_administrator_creates_naans(db, world, principal_of):
    with pytest.raises(Forbidden):
        ops.create_naan(db, principal_of(authority=Authority.NAAN), naan="77777", name="x")


def test_nobody_grants_a_wider_reach_than_their_own(db, world, principal_of):
    p = principal_of(manager=world["a"])
    with pytest.raises(Forbidden):
        ops.register_client(
            db, p, client_id="evil", naan="99999", authority=Authority.SYSTEM.value
        )


def test_a_principal_cannot_be_created_for_another_organisation(db, world, principal_of):
    p = principal_of(manager=world["a"])
    with pytest.raises(Forbidden):
        ops.register_client(
            db, p, client_id="x", naan="99999", manager_id=world["b"].id
        )


# ------------------------------------------------------------------- The screens


def test_an_organisation_admin_sees_only_its_own_reach(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    body = c.get("/admin/").text
    assert "org A" in body
    assert "org B" not in body  # another organisation under the same NAAN is hidden
    assert "88888" not in body


def test_the_audit_log_is_not_shown_to_an_organisation_admin(db, world, principal_of, as_principal):
    """Who did what and when belongs to whoever holds the namespace."""
    c = as_principal(principal_of(manager=world["a"]))
    assert c.get("/admin/audit").status_code == 403
    c2 = as_principal(principal_of(authority=Authority.NAAN))
    assert c2.get("/admin/audit").status_code == 200


def test_minting_works_from_the_screen(db, world, principal_of, as_principal):
    """It goes through the same path as the API, authz then minting. No shortcut exists
    for the screens."""
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/admin/mint", data={"url": "https://example.org/manual"})
    assert r.status_code == 200 and "ark:99999/a1" in r.text


def test_the_screen_cannot_mint_into_another_organisation(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    assert c.post("/admin/mint", data={"shoulder": "/b2"}).status_code == 403


def test_without_the_minting_scope_the_page_does_not_open(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"], scopes={"ark:read"}))
    assert c.get("/admin/mint").status_code == 403


# ------------------------------------------------------------------ Localisation


@pytest.mark.parametrize(
    # The Japanese needle is written as an escape: it is text from the Japanese UI.
    "lang,needle", [("ja", "\u7d44\u7e54\u7ba1\u7406"), ("en", "Organisations")]
)
def test_the_language_can_be_switched(db, world, principal_of, as_principal, lang, needle):
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    assert needle in c.get("/admin/", params={"lang": lang}).text


def test_the_chosen_language_is_remembered(db, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    r = c.get("/admin/", params={"lang": "en"})
    assert r.cookies.get("arkhe_lang") == "en"


def test_accept_language_is_honoured(db, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    r = c.get("/admin/", headers={"accept-language": "en-US,en;q=0.9"})
    assert "Organisations" in r.text


def test_no_translation_is_missing():
    from arkhe.api import i18n

    for lang, cat in i18n.CATALOGS.items():
        assert set(cat) == set(i18n.JA), f"{lang} is missing keys"


def test_every_scope_has_a_description():
    """A new scope needs new wording in every language.

    A key missing from one language is caught by the check above, but adding to SCOPES
    and forgetting all languages leaves them consistent and passes. That happened:
    ark:hold showed the raw key sc.ark:hold on the screen.

    The OpenAPI clientCredentials scopes come from here too, so a gap leaks a key into
    the specification.
    """
    from arkhe.api import i18n
    from arkhe.domain import authz

    for lang, cat in i18n.CATALOGS.items():
        missing = [f"sc.{s}{sfx}" for s in authz.SCOPES for sfx in ("", ".d")
                   if f"sc.{s}{sfx}" not in cat]
        assert not missing, f"scope wording missing from {lang}: {missing}"


def test_reserved_can_only_be_set_when_the_shoulder_is_created(db, world, root):
    """There is no way back from active to reserved: a namespace that has been
    mintable cannot later be called unused."""
    sh = ops.add_shoulder(db, root, naan="99999", shoulder="/rv", status="reserved")
    db.commit()
    assert sh.status == ShoulderStatus.RESERVED
    with pytest.raises(Invalid):
        ops.add_shoulder(db, root, naan="99999", shoulder="/bad", status="retired")


def test_a_reserved_shoulder_can_be_made_mintable(db, world, root):
    sh = ops.add_shoulder(db, root, naan="99999", shoulder="/rv", status="reserved")
    db.commit()
    ops.set_shoulder_status(db, root, shoulder_id=sh.id, status="active")
    assert sh.status == ShoulderStatus.ACTIVE


def test_the_language_switcher_is_always_present(db, world, principal_of, as_principal):
    """Not a row of segments: more languages would stretch it until it breaks, so it
    is a list opened from an icon. The Popover API handles opening and closing, which
    gives clicking outside and Esc for free, with no JavaScript."""
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    body = c.get("/admin/").text
    assert 'popovertarget="lang-menu"' in body
    assert 'id="lang-menu" popover' in body
    # Every available language is listed and the current one is marked
    from arkhe.api import i18n

    for code, label in i18n.LANGS.items():
        assert f'href="?lang={code}"' in body and label in body
    assert 'class="menu-i on"' in body


# ------------------------------------------------ Ways in to the admin interface
#
# A browser cannot set an Authorization header. Bearer is enough for the API, but
# people need another way in, so there are three, chosen by configuration.


@pytest.fixture
def raw_app(factory):
    """A plain app with authentication left alone, so the entrance itself is tested."""
    from fastapi import FastAPI

    from arkhe import observability
    from arkhe.api import admin as admin_router
    from arkhe.app import _install_handlers
    from arkhe.db import session as session_mod
    from arkhe.settings import get_settings

    def build(settings):
        a = FastAPI()
        _install_handlers(a)
        observability.install(a)
        a.include_router(admin_router.router)

        def one_session():
            s = factory()
            try:
                yield s
            finally:
                s.close()

        a.dependency_overrides[session_mod.get_session] = one_session
        a.dependency_overrides[get_settings] = lambda: settings
        return a

    return build


def _settings(**kw):
    import secrets

    from arkhe.settings import Settings

    return Settings(
        auth=["apikey"], database_url="sqlite://",
        session_secret=secrets.token_urlsafe(48), session_secure=False, **kw
    )


def test_bearer_mode_has_no_login_page(db, world, raw_app):
    """A setup meant for automation and curl. It answers 401 and offers nothing for a
    browser."""
    from fastapi.testclient import TestClient

    c = TestClient(raw_app(_settings(admin_login="bearer")), follow_redirects=False)
    assert c.get("/admin/").status_code == 401
    assert c.get("/admin/login").status_code == 404


def test_oidc_mode_sends_anonymous_callers_to_the_login_page(db, world, raw_app):
    """Not 401. A browser cannot add the header, so a 401 leaves the person with
    nothing to do."""
    from fastapi.testclient import TestClient

    cfg = _settings(admin_login="oidc", oidc_issuer="https://kc.example.org",
                    admin_client_id="arkhe-admin")
    c = TestClient(raw_app(cfg), follow_redirects=False)
    r = c.get("/admin/")
    assert r.status_code == 302 and r.headers["location"].startswith("/admin/login")


def test_proxy_mode_trusts_the_header_from_the_proxy(db, world, root, raw_app):
    from fastapi.testclient import TestClient

    # Register a person. A machine principal cannot sign in from outside.
    ops.register_client(db, root, client_id="alice@example.ac.jp", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint", subject_type="person")
    db.commit()
    cli = TestClient(raw_app(_settings(admin_login="proxy")), follow_redirects=False)
    # With no header it goes to the login page, which this setup does not have
    assert cli.get("/admin/").status_code == 302
    r = cli.get("/admin/", headers={"X-Forwarded-User": "alice@example.ac.jp"})
    assert r.status_code == 200 and "org A" in r.text


def test_proxy_mode_refuses_an_identity_that_is_not_in_the_ledger(db, world, raw_app):
    """Authenticating at the authorisation server and being allowed to touch this
    namespace are different things."""
    from fastapi.testclient import TestClient

    cli = TestClient(raw_app(_settings(admin_login="proxy")), follow_redirects=False)
    r = cli.get("/admin/", headers={"X-Forwarded-User": "stranger@example.com"})
    assert r.status_code == 302  # sent to the login page, which means kept out


def test_the_session_is_signed_and_cannot_be_forged(db, world, root, raw_app):
    from fastapi.testclient import TestClient

    from arkhe.auth import session as sess

    ops.register_client(db, root, client_id="bob", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint", subject_type="person")
    db.commit()
    cfg = _settings(admin_login="proxy")
    cli = TestClient(raw_app(cfg), follow_redirects=False)

    good = sess.issue("bob", secret=cfg.session_secret, ttl=600)
    cli.cookies.set(sess.COOKIE, good)
    assert cli.get("/admin/").status_code == 200

    # Signed with a different key, so it is refused
    forged = sess.issue("bob", secret="x" * 48, ttl=600)
    cli.cookies.set(sess.COOKIE, forged)
    assert cli.get("/admin/").status_code == 302


def test_a_machine_principal_cannot_sign_in_from_outside(db, world, root, raw_app):
    """Even if the proxy is misconfigured and the header arrives from outside, nobody
    can become the bulk-loading batch.

    Placing the proxy correctly would prevent it, but one wrong setting turning into
    "rewrite everything" is too fragile. People and machines are different kinds, which
    closes the path itself.
    """
    from fastapi.testclient import TestClient

    ops.register_client(db, root, client_id="batch", naan="99999",
                        manager_id=world["a"].id, scopes="ark:mint")  # machine by default
    db.commit()
    cli = TestClient(raw_app(_settings(admin_login="proxy")), follow_redirects=False)
    assert cli.get("/admin/", headers={"X-Forwarded-User": "batch"}).status_code == 302


def test_a_person_holds_no_credentials(db, world, root):
    """Identity is vouched for elsewhere. A key held here would still work after the
    account was disabled there."""
    c = ops.register_client(db, root, client_id="carol@example.ac.jp", naan="99999",
                            manager_id=world["a"].id, subject_type="person")
    db.commit()
    with pytest.raises(Invalid):
        ops.issue_credential(db, root, client_pk=c.id)


def test_a_person_cannot_authenticate_with_an_api_key(db, world, root):
    """The other direction is closed too: even if a key were created somehow, it does
    not authenticate."""
    from arkhe.auth import apikey
    from arkhe.db.models import Credential, CredentialKind

    c = ops.register_client(db, root, client_id="dave@example.ac.jp", naan="99999",
                            manager_id=world["a"].id, subject_type="person")
    db.flush()
    raw, prefix, hashed = apikey.generate_key()
    db.add(Credential(client_pk=c.id, kind=CredentialKind.API_KEY.value,
                      prefix=prefix, hashed=hashed))
    db.commit()
    from arkhe.auth.errors import AuthError

    with pytest.raises(AuthError):
        apikey.authenticate(db, raw)


# ----------------------------------------------------- Usernames and passwords
#
# A way in for organisations with no identity provider of their own. Where oidc or
# proxy is available, they are better: identities stay in one place.


@pytest.fixture
def with_password(db, world, root):
    """Create one person and give them a password."""
    c = ops.register_client(db, root, client_id="alice@example.ac.jp", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint",
                            subject_type="person")
    db.flush()
    ops.set_password(db, root, client_pk=c.id, password="correct-horse-battery")
    db.commit()
    return c


def _pw_client(raw_app):
    from fastapi.testclient import TestClient

    return TestClient(raw_app(_settings(admin_login="password")), follow_redirects=False)


def test_a_password_signs_you_in(db, world, with_password, raw_app):
    cli = _pw_client(raw_app)
    assert cli.get("/admin/").status_code == 302  # anonymous goes to the login page
    assert cli.get("/admin/login").status_code == 200
    r = cli.post("/admin/login", data={"username": "alice@example.ac.jp",
                                       "password": "correct-horse-battery"})
    assert r.status_code == 302 and r.headers["location"] == "/admin/"
    assert "org A" in cli.get("/admin/").text


def test_a_wrong_password_does_not_sign_you_in(db, world, with_password, raw_app):
    cli = _pw_client(raw_app)
    r = cli.post("/admin/login", data={"username": "alice@example.ac.jp", "password": "wrong"})
    assert r.status_code == 401
    assert cli.get("/admin/").status_code == 302


def test_an_unknown_user_and_a_wrong_password_look_the_same(db, world, with_password, raw_app):
    """If "no such user" were distinguishable, the list of users could be found by
    trying names."""
    cli = _pw_client(raw_app)
    a = cli.post("/admin/login", data={"username": "alice@example.ac.jp", "password": "wrong"})
    b = cli.post("/admin/login", data={"username": "nobody@example.ac.jp", "password": "wrong"})
    assert a.status_code == b.status_code == 401
    from arkhe.api import i18n

    assert i18n.JA["login.failed"] in a.text and i18n.JA["login.failed"] in b.text


def test_repeated_failures_lock_the_account_for_a_while(db, world, with_password, raw_app):
    """Offering a login page without this leaves it open to guessing."""
    from arkhe.auth import password as pw

    cli = _pw_client(raw_app)
    for _ in range(pw.MAX_ATTEMPTS):
        cli.post("/admin/login", data={"username": "alice@example.ac.jp", "password": "wrong"})
    # Even the correct password is refused
    r = cli.post("/admin/login", data={"username": "alice@example.ac.jp",
                                       "password": "correct-horse-battery"})
    assert r.status_code == 401


def test_a_short_password_is_refused(db, world, root):
    c = ops.register_client(db, root, client_id="bob@example.ac.jp", naan="99999",
                            manager_id=world["a"].id, subject_type="person")
    db.flush()
    with pytest.raises(Invalid):
        ops.set_password(db, root, client_pk=c.id, password="short")


def test_a_machine_principal_gets_no_password(db, world, root):
    """A machine does not remember a password; giving it one just adds another secret
    written down somewhere."""
    c = ops.register_client(db, root, client_id="batch2", naan="99999",
                            manager_id=world["a"].id)
    db.flush()
    with pytest.raises(Invalid):
        ops.set_password(db, root, client_pk=c.id, password="long-enough-password")


def test_changing_the_password_stops_the_old_one(db, world, root, with_password, raw_app):
    """The old row is disabled rather than deleted, so when it changed is still
    known."""
    ops.set_password(db, root, client_pk=with_password.id, password="a-brand-new-secret")
    db.commit()
    cli = _pw_client(raw_app)
    old = cli.post("/admin/login", data={"username": "alice@example.ac.jp",
                                         "password": "correct-horse-battery"})
    assert old.status_code == 401
    new = cli.post("/admin/login", data={"username": "alice@example.ac.jp",
                                         "password": "a-brand-new-secret"})
    assert new.status_code == 302


def test_the_login_page_cannot_redirect_to_another_site(db, world, with_password, raw_app):
    """An external URL in next would make this a stepping stone that sends people
    elsewhere right after they sign in."""
    cli = _pw_client(raw_app)
    r = cli.post("/admin/login", data={"username": "alice@example.ac.jp",
                                       "password": "correct-horse-battery",
                                       "next": "https://evil.example.com/"})
    assert r.headers["location"] == "/admin/"


def test_a_shoulder_pinned_principal_inherits_the_organisation(db, world, root):
    """A shoulder already determines the organisation.

    Requiring both separately produces principals with the manager left out, which are
    refused at the door, in the confusing form of "the shoulder is right but it still
    does not work".
    """
    sh = world["a"].default_shoulder
    c = ops.register_client(
        db, root, client_id="pinned", naan=sh.naan, shoulder_id=sh.id,
        scopes="ark:mint",
    )
    db.commit()
    assert c.manager_id == sh.manager_id


def test_a_shoulder_that_disagrees_with_the_organisation_is_refused(db, world, root):
    """Neither one wins silently: only the caller knows which was intended."""
    from arkhe.domain.authz import Invalid

    sh = world["a"].default_shoulder
    with pytest.raises(Invalid):
        ops.register_client(
            db, root, client_id="mismatch", naan=sh.naan, shoulder_id=sh.id,
            manager_id=world["b"].id, scopes="ark:mint",
        )


def test_the_commitment_level_can_be_restated(db, world, root):
    """So that nobody is left on the default.

    Without this, every organisation runs as permanent-dynamic and ?? publishes a
    software default as if the organisation had declared it.
    """
    m = world["a"]
    ops.set_commitment(db, root, manager_id=m.id, level="permanent-unchanging")
    db.commit()
    assert m.commitment_level == "permanent-unchanging"


def test_the_commitment_level_can_be_lowered(db, world, root):
    """Restating it is more honest than keeping a promise that cannot be kept."""
    m = world["a"]
    ops.set_commitment(db, root, manager_id=m.id, level="not-guaranteed")
    db.commit()
    assert m.commitment_level == "not-guaranteed"


def test_an_unknown_commitment_level_is_refused(db, world, root):
    """The value is published as it stands by ??, so a typo would announce, in the
    organisation's name, a level it never stated."""
    from arkhe.domain.authz import Invalid

    with pytest.raises(Invalid):
        ops.set_commitment(db, root, manager_id=world["a"].id, level="permanent")


def test_another_organisations_commitment_cannot_be_changed(db, world, principal_of):
    """The promise belongs to that organisation."""
    from arkhe.auth.errors import Forbidden

    p = principal_of(manager=world["a"])
    with pytest.raises(Forbidden):
        ops.set_commitment(db, p, manager_id=world["b"].id, level="not-guaranteed")


def test_the_commitment_can_be_stated_while_onboarding(db, world, root):
    """Settle it while onboarding. Fixing it later always leaves defaults behind."""
    m, _ = ops.onboard_manager(
        db, root, naan="99999", name="org that stated a commitment", shoulder="/c1",
        commitment_level="permanent-stable",
    )
    db.commit()
    assert m.commitment_level == "permanent-stable"


# ------------------------------------------------------------------ Signing out


def test_signing_out_of_oidc_ends_the_session_at_the_server_too(db, world, raw_app, monkeypatch):
    """Dropping our cookie is not signing out.

    Opening /admin/ again goes to the authorisation server, and if the session there is
    alive the person comes straight back without being asked anything. From where they
    stand, signing out does not work.
    """
    from fastapi.testclient import TestClient

    from arkhe.auth import login as login_flow

    monkeypatch.setattr(
        login_flow, "_discovery",
        {"end_session_endpoint": "https://kc.example.org/realms/arkhe/logout"},
    )
    cfg = _settings(admin_login="oidc", oidc_issuer="https://kc.example.org",
                    admin_client_id="arkhe-admin")
    r = TestClient(raw_app(cfg), follow_redirects=False).post("/admin/logout")
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://kc.example.org/realms/arkhe/logout")
    assert "client_id=arkhe-admin" in loc
    # Send where to return to, or the person is stranded on the server's page.
    assert "post_logout_redirect_uri=" in loc
    # The ID token is not sent: holding it would mean keeping it in the cookie, which
    # passes 4 KB where claims are many, and browsers drop it without a word.
    assert "id_token_hint" not in loc


def test_a_server_without_end_session_is_handled_locally(db, world, raw_app, monkeypatch):
    """Some authorisation servers do not support logout initiated by the relying
    party. Do not fail."""
    from fastapi.testclient import TestClient

    from arkhe.auth import login as login_flow

    monkeypatch.setattr(login_flow, "_discovery", {"token_endpoint": "https://kc/token"})
    cfg = _settings(admin_login="oidc", oidc_issuer="https://kc.example.org",
                    admin_client_id="arkhe-admin")
    r = TestClient(raw_app(cfg), follow_redirects=False).post("/admin/logout")
    assert r.status_code == 302 and r.headers["location"] == "/admin/"


def test_password_sign_out_stays_local(db, world, raw_app):
    """No external server is involved, so there is only one session to end."""
    from fastapi.testclient import TestClient

    r = TestClient(
        raw_app(_settings(admin_login="password")), follow_redirects=False
    ).post("/admin/logout")
    assert r.status_code == 302 and r.headers["location"] == "/admin/"
    assert 'arkhe_session=""' in r.headers.get("set-cookie", "") or \
           "Max-Age=0" in r.headers.get("set-cookie", "")


# ------------------------------------------- Getting back to the login page


def test_an_expired_round_trip_leads_back_to_the_login_page(db, world, raw_app):
    """Never leave a dead end.

    This used to return plain text, leaving the person to edit the URL by hand.
    """
    from fastapi.testclient import TestClient

    cfg = _settings(admin_login="oidc", oidc_issuer="https://kc.example.org",
                    admin_client_id="arkhe-admin")
    r = TestClient(raw_app(cfg), follow_redirects=False).get("/admin/callback?code=x&state=y")
    assert r.status_code == 400
    assert 'href="/admin/login"' in r.text        # there is a way back
    assert "arkhe" in r.text and "<style" in r.text  # styled like the login page


def test_a_refusal_from_the_server_uses_the_same_page(db, world, raw_app, monkeypatch):
    from fastapi.testclient import TestClient

    from arkhe.auth import session as sess

    cfg = _settings(admin_login="oidc", oidc_issuer="https://kc.example.org",
                    admin_client_id="arkhe-admin")
    cli = TestClient(raw_app(cfg), follow_redirects=False)
    flow = sess.issue("flow", secret=cfg.session_secret, ttl=600,
                      extra={"flow": '{"state": "s1", "verifier": "v", "next": "/admin/"}'})
    cli.cookies.set("arkhe_login", flow)
    r = cli.get("/admin/callback?state=s1&error=access_denied")
    assert r.status_code == 403
    assert "access_denied" in r.text and 'href="/admin/login"' in r.text


def test_a_setup_without_a_login_page_still_explains_itself(db, world, raw_app):
    """A plain 404 leaves the person with no idea what happened."""
    from fastapi.testclient import TestClient

    r = TestClient(raw_app(_settings(admin_login="proxy")), follow_redirects=False).get(
        "/admin/login"
    )
    assert r.status_code == 404 and 'href="/admin/"' in r.text


def test_the_caller_address_is_recorded_before_anything_else(db, world, root, raw_app):
    """What only the request layer knows is recorded there.

    Without it the audit log fills with empty addresses, which is easy to miss because
    the screens keep working. A long X-Forwarded-For is sent to a one-proxy setup, and
    the entry kept is the rightmost, not the one the client wrote.
    """
    from datetime import UTC, datetime, timedelta

    from fastapi.testclient import TestClient

    from arkhe.db.models import AuditEvent

    # The audit log keeps NAAN level and above, so sign in with that reach.
    ops.register_client(db, root, client_id="alice@example.ac.jp", naan="99999",
                        scopes="ark:mint", subject_type="person",
                        authority="naan",
                        expires_at=datetime.now(UTC) + timedelta(days=1))
    db.commit()
    cli = TestClient(raw_app(_settings(admin_login="proxy", trusted_proxies=1)),
                     follow_redirects=False)
    r = cli.post(
        f"/admin/manager/{world['a'].id}",
        data={"commitment": "permanent-stable"},
        headers={"X-Forwarded-User": "alice@example.ac.jp",
                 "X-Forwarded-For": "203.0.113.9, 10.0.0.9"},
    )
    assert r.status_code == 303, r.text[:200]
    ev = db.scalars(db.query(AuditEvent).filter_by(action="set_commitment").statement).all()
    assert ev and ev[-1].ip == "10.0.0.9"


def test_signing_out_does_not_work_over_get(db, world, raw_app):
    """SameSite=Lax still sends the cookie on a top-level GET.

    Left as GET, another site could sign people out with <img src=".../logout">.
    """
    from fastapi.testclient import TestClient

    r = TestClient(raw_app(_settings(admin_login="password")), follow_redirects=False).get(
        "/admin/logout"
    )
    assert r.status_code == 405


def test_readyz_probes_the_database(db, world, raw_app):
    """It used to share /healthz, so it kept answering Ready with the database
    down."""
    from fastapi.testclient import TestClient

    from arkhe.app import create_app
    from arkhe.settings import get_settings

    cfg = _settings()
    app = create_app(cfg)
    app.dependency_overrides[get_settings] = lambda: cfg
    c = TestClient(app, follow_redirects=False)
    assert c.get("/healthz").status_code == 200

    # Point it at a database that is not reachable: the real shape of the failure,
    # rather than a broken dependency.
    bad = _settings()
    bad = bad.model_copy(update={"database_url": "postgresql+psycopg://x@127.0.0.1:1/none"})
    gone = create_app(bad)
    g = TestClient(gone, follow_redirects=False)
    # Liveness is unchanged, since the process is alive, but readiness is not.
    assert g.get("/healthz").status_code == 200
    assert g.get("/readyz").status_code == 503


def test_the_request_id_comes_back_in_the_response(db, world, raw_app):
    """So that someone can say "look up this id" when reporting a problem."""
    from fastapi.testclient import TestClient

    c = TestClient(raw_app(_settings()), follow_redirects=False)
    r = c.get("/healthz", headers={"X-Request-Id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
    # If the proxy did not set one, make one here
    assert TestClient(raw_app(_settings())).get("/healthz").headers.get("x-request-id")


# ------------------------------------------- Recording who came and went


def test_a_successful_sign_in_is_recorded(db, world, root, raw_app):
    """Sign-ins are recorded whoever they belong to; reach does not thin them out."""
    from fastapi.testclient import TestClient

    from arkhe.db.models import AuditEvent

    ops.register_client(db, root, client_id="alice", naan="99999",
                        manager_id=world["a"].id, subject_type="person")
    c = db.scalar(db.query(Client).filter_by(client_id="alice").statement)
    ops.set_password(db, root, client_pk=c.id, password="correct-horse-battery")
    db.commit()

    cli = TestClient(raw_app(_settings(admin_login="password")), follow_redirects=False)
    r = cli.post("/admin/login", data={"username": "alice",
                                       "password": "correct-horse-battery"})
    assert r.status_code == 302
    ev = db.scalars(db.query(AuditEvent).filter_by(action="sign_in").statement).all()
    # Recorded even for an organisation-level person, which audit() would skip
    assert len(ev) == 1 and ev[0].client_id == "alice" and ev[0].detail["ok"] is True


def test_a_failed_sign_in_is_recorded_above_all(db, world, root, raw_app):
    """The record people want to read before the successful ones.

    The username that was typed is kept; the password, of course, is not.
    """
    from fastapi.testclient import TestClient

    from arkhe.db.models import AuditEvent

    cli = TestClient(raw_app(_settings(admin_login="password")), follow_redirects=False)
    assert cli.post("/admin/login",
                    data={"username": "mallory", "password": "hunter2"}).status_code == 401
    ev = db.scalars(db.query(AuditEvent).filter_by(action="sign_in").statement).all()
    assert len(ev) == 1
    assert ev[0].client_id == "mallory" and ev[0].detail["ok"] is False
    assert "hunter2" not in str(ev[0].detail), "the password was recorded"


def test_signing_out_is_recorded_too(db, world, root, raw_app):
    from fastapi.testclient import TestClient

    from arkhe.db.models import AuditEvent

    ops.register_client(db, root, client_id="bob", naan="99999",
                        manager_id=world["a"].id, subject_type="person")
    c = db.scalar(db.query(Client).filter_by(client_id="bob").statement)
    ops.set_password(db, root, client_pk=c.id, password="correct-horse-battery")
    db.commit()
    cli = TestClient(raw_app(_settings(admin_login="password")), follow_redirects=False)
    cli.post("/admin/login", data={"username": "bob", "password": "correct-horse-battery"})
    cli.post("/admin/logout")
    ev = db.scalars(db.query(AuditEvent).filter_by(action="sign_out").statement).all()
    assert len(ev) == 1 and ev[0].client_id == "bob"
