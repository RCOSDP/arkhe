"""The three authentication mechanisms. All of them end at one Principal."""

from __future__ import annotations

import secrets

import pytest

from arkhe.auth import apikey, oauth2
from arkhe.auth.errors import AuthError, Forbidden
from arkhe.db.models import Authority, CredentialKind
from arkhe.domain import admin_ops as ops
from arkhe.settings import Settings

SECRET = secrets.token_urlsafe(48)


@pytest.fixture
def client_with_keys(db, world, root):
    c = ops.register_client(
        db, root, client_id="a-web", naan="99999", manager_id=world["a"].id,
        scopes="ark:mint ark:update",
    )
    db.flush()
    key = ops.issue_credential(db, root, client_pk=c.id, kind=CredentialKind.API_KEY.value)
    sec = ops.issue_credential(db, root, client_pk=c.id, kind=CredentialKind.CLIENT_SECRET.value)
    db.commit()
    return c, key.secret, sec.secret


def test_an_api_key_authenticates(db, client_with_keys):
    _, key, _ = client_with_keys
    p = apikey.authenticate(db, key)
    assert p.client_id == "a-web" and p.mechanism == "apikey"
    assert p.scopes == frozenset({"ark:mint", "ark:update"})


@pytest.mark.parametrize("bad", ["", "arkhe_wrong", "garbage", "arkhe_"])
def test_a_bad_api_key_is_always_refused(db, client_with_keys, bad):
    with pytest.raises(AuthError):
        apikey.authenticate(db, bad)


def test_a_revoked_api_key_stops_working(db, root, client_with_keys):
    from sqlalchemy import select

    from arkhe.db.models import Credential

    _, key, _ = client_with_keys
    cred = db.scalars(select(Credential)).first()
    ops.revoke_credential(db, root, credential_id=cred.id)
    db.commit()
    with pytest.raises(AuthError):
        apikey.authenticate(db, key)


def test_client_credentials_issues_a_token_that_verifies(db, client_with_keys):
    _, _, sec = client_with_keys
    tok = oauth2.issue_token(db, client_id="a-web", client_secret=sec, secret_key=SECRET)
    assert tok["token_type"] == "Bearer"
    p = oauth2.authenticate(db, tok["access_token"], secret_key=SECRET)
    assert p.client_id == "a-web" and p.mechanism == "oauth2"


def test_a_scope_that_was_not_registered_cannot_be_taken(db, client_with_keys):
    """That would be privilege escalation. The scope is refused with invalid_scope
    rather than trimmed silently."""
    _, _, sec = client_with_keys
    with pytest.raises(Forbidden) as e:
        oauth2.issue_token(
            db, client_id="a-web", client_secret=sec,
            requested_scope="ark:mint ark:admin", secret_key=SECRET,
        )
    # The shape RFC 6749 section 5.2 defines, with our own code alongside.
    assert e.value.detail["error"] == "invalid_scope"
    assert e.value.detail["code"] == "ARKHE-1305"


def test_asking_can_narrow_a_token_but_never_widen_it(db, client_with_keys):
    _, _, sec = client_with_keys
    tok = oauth2.issue_token(
        db, client_id="a-web", client_secret=sec, requested_scope="ark:mint", secret_key=SECRET
    )
    p = oauth2.authenticate(db, tok["access_token"], secret_key=SECRET)
    assert p.scopes == frozenset({"ark:mint"})


def test_stopping_a_principal_invalidates_its_tokens_at_once(db, client_with_keys):
    """Even with a self-contained JWT, the reach is read from the Client table on
    every request, so it stops immediately."""
    c, _, sec = client_with_keys
    tok = oauth2.issue_token(db, client_id="a-web", client_secret=sec, secret_key=SECRET)
    c.active = False
    db.commit()
    with pytest.raises(AuthError):
        oauth2.authenticate(db, tok["access_token"], secret_key=SECRET)


def test_a_wrong_secret_issues_nothing(db, client_with_keys):
    with pytest.raises(AuthError):
        oauth2.issue_token(db, client_id="a-web", client_secret="wrong", secret_key=SECRET)


@pytest.mark.parametrize(
    "kw,why",
    [
        ({"auth": ["oauth2"], "token_secret": "short"}, "the key is too short"),
        ({"auth": ["oauth2"]}, "no key at all"),
        ({"auth": ["oidc"]}, "no issuer"),
        ({"auth": []}, "no mechanism"),
    ],
)
def test_missing_settings_fail_at_startup(kw, why):
    """There is no default secret. Stopping here beats running on a weak value that
    someone forgot to set."""
    with pytest.raises(ValueError):
        Settings(**kw).check()


def test_a_resolver_needs_no_authentication_settings():
    """Resolution needs no authentication and carries no admin interface, so there is
    no reason to distribute an unused session key to every resolver."""
    Settings(resolver=True, auth=[], admin_login="oidc", session_secret="").check()


def test_the_same_settings_still_stop_a_minter():
    """The exception applies to resolvers only; nothing was loosened in general."""
    with pytest.raises(ValueError, match="ARKHE_SESSION_SECRET"):
        Settings(
            resolver=False, auth=["oidc"], oidc_issuer="https://kc/realms/x",
            admin_login="oidc", session_secret="",
        ).check()


def test_break_glass_needs_an_expiry(db, world, root):
    """A permanent master key must not be creatable."""
    from arkhe.domain.authz import Invalid

    with pytest.raises(Invalid):
        ops.register_client(
            db, root, client_id="bg", naan="99999", authority=Authority.NAAN.value
        )


# --------------------------------------- Issuing our own tokens, without Keycloak


@pytest.fixture
def standalone(factory):
    """A plain app with ARKHE_AUTH=oauth2: no external authorisation server."""
    from fastapi.testclient import TestClient

    from arkhe.app import create_app
    from arkhe.db import session as session_mod
    from arkhe.settings import Settings, get_settings

    cfg = Settings(auth=["oauth2"], database_url="sqlite://", token_secret=SECRET)
    app = create_app(cfg)

    def one_session():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[session_mod.get_session] = one_session
    app.dependency_overrides[get_settings] = lambda: cfg
    return TestClient(app, follow_redirects=False)


def test_a_token_can_be_taken_and_used_without_keycloak(
    db, world, root, client_with_keys, standalone
):
    """The API can be called the OAuth2 way with nothing else installed."""
    _, _, secret = client_with_keys
    r = standalone.post(
        "/oauth/token",
        data={"grant_type": "client_credentials", "client_id": "a-web",
              "client_secret": secret},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "Bearer" and body["expires_in"] > 0
    assert r.headers["cache-control"] == "no-store"  # RFC 6749 §5.1

    m = standalone.post(
        "/api/mint",
        json={"url": "https://example.org/1"},
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert m.status_code == 201


def test_credentials_can_also_be_sent_with_basic_auth(db, world, client_with_keys, standalone):
    """RFC 6749 section 2.3.1 recommends Basic and permits the body. Client libraries
    in the wild use both."""
    import base64

    _, _, secret = client_with_keys
    creds = base64.b64encode(f"a-web:{secret}".encode()).decode()
    r = standalone.post(
        "/oauth/token", data={"grant_type": "client_credentials"},
        headers={"Authorization": f"Basic {creds}"},
    )
    assert r.status_code == 200


def test_no_grant_other_than_client_credentials(db, world, standalone):
    """Say plainly what is not implemented, rather than let a caller discover it
    later."""
    r = standalone.post("/oauth/token", data={"grant_type": "authorization_code", "code": "x"})
    assert r.status_code == 400 and r.json()["error"] == "unsupported_grant_type"


def test_wrong_credentials_give_invalid_client(db, world, client_with_keys, standalone):
    r = standalone.post(
        "/oauth/token",
        data={"grant_type": "client_credentials", "client_id": "a-web", "client_secret": "no"},
    )
    assert r.status_code == 401 and r.json()["error"] == "invalid_client"
    # An unknown client gets the same answer, so names cannot be found by trying
    r2 = standalone.post(
        "/oauth/token",
        data={"grant_type": "client_credentials", "client_id": "nope", "client_secret": "no"},
    )
    assert r2.json() == r.json()


def test_a_deployment_without_oauth2_has_no_token_endpoint(db, world, app):
    """A deployment that does not use it should not expose it."""
    from fastapi.testclient import TestClient

    c = TestClient(app, follow_redirects=False)
    assert c.post("/oauth/token", data={"grant_type": "client_credentials"}).status_code == 404


# ------------------------------------------------------- Recording the caller


@pytest.mark.parametrize(
    "trusted,xff,peer,want,why",
    [
        (0, "1.2.3.4", "10.0.0.1", "10.0.0.1", "by default no proxy is trusted"),
        (0, "", "10.0.0.1", "10.0.0.1", "with no header, the direct peer"),
        (1, "1.2.3.4, 10.0.0.9", "10.0.0.1", "10.0.0.9", "one hop: the rightmost"),
        (2, "1.2.3.4, 10.0.0.9, 10.0.0.8", "10.0.0.1", "10.0.0.9",
         "two hops: the second from the right"),
        # What is missing is never filled in from what the client claims.
        (2, "1.2.3.4", "10.0.0.1", "10.0.0.1", "shorter than expected: fall back"),
        (1, "", "10.0.0.1", "10.0.0.1", "no header: fall back"),
    ],
)
def test_the_caller_address_depends_on_how_many_proxies_are_trusted(trusted, xff, peer, want, why):
    """Anyone can set X-Forwarded-For.

    Taking the leftmost entry unconditionally fills the audit log with strings an
    attacker chose, which is worse than recording the direct peer.
    """
    from types import SimpleNamespace

    from arkhe.auth.deps import client_ip

    req = SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers={"x-forwarded-for": xff} if xff else {},
    )
    assert client_ip(req, Settings(trusted_proxies=trusted)) == want, why


def test_a_forged_leftmost_entry_is_not_used():
    """With one trusted proxy, a long header does not make the client's entry count."""
    from types import SimpleNamespace

    from arkhe.auth.deps import client_ip

    req = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.1"),
        headers={"x-forwarded-for": "203.0.113.9, 198.51.100.7, 10.0.0.9"},
    )
    assert client_ip(req, Settings(trusted_proxies=1)) == "10.0.0.9"
