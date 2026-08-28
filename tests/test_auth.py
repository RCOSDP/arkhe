"""3 つの認証機構。**どれで認証しても Principal 1 つに集約される。**"""

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


def test_apikey_で認証できる(db, client_with_keys):
    _, key, _ = client_with_keys
    p = apikey.authenticate(db, key)
    assert p.client_id == "a-web" and p.mechanism == "apikey"
    assert p.scopes == frozenset({"ark:mint", "ark:update"})


@pytest.mark.parametrize("bad", ["", "arkhe_wrong", "garbage", "arkhe_"])
def test_apikey_不正な鍵は一律で拒む(db, client_with_keys, bad):
    with pytest.raises(AuthError):
        apikey.authenticate(db, bad)


def test_apikey_失効させた鍵は通らない(db, root, client_with_keys):
    from sqlalchemy import select

    from arkhe.db.models import Credential

    _, key, _ = client_with_keys
    cred = db.scalars(select(Credential)).first()
    ops.revoke_credential(db, root, credential_id=cred.id)
    db.commit()
    with pytest.raises(AuthError):
        apikey.authenticate(db, key)


def test_oauth2_client_credentialsで発行し検証できる(db, client_with_keys):
    _, _, sec = client_with_keys
    tok = oauth2.issue_token(db, client_id="a-web", client_secret=sec, secret_key=SECRET)
    assert tok["token_type"] == "Bearer"
    p = oauth2.authenticate(db, tok["access_token"], secret_key=SECRET)
    assert p.client_id == "a-web" and p.mechanism == "oauth2"


def test_oauth2_登録に無いscopeは取れない(db, client_with_keys):
    """**権限昇格そのもの。** 黙って削らず invalid_scope で返す。"""
    _, _, sec = client_with_keys
    with pytest.raises(Forbidden) as e:
        oauth2.issue_token(
            db, client_id="a-web", client_secret=sec,
            requested_scope="ark:mint ark:admin", secret_key=SECRET,
        )
    assert e.value.detail["error"] == "invalid_scope"


def test_oauth2_要求すると狭くなるが広がらない(db, client_with_keys):
    _, _, sec = client_with_keys
    tok = oauth2.issue_token(
        db, client_id="a-web", client_secret=sec, requested_scope="ark:mint", secret_key=SECRET
    )
    p = oauth2.authenticate(db, tok["access_token"], secret_key=SECRET)
    assert p.scopes == frozenset({"ark:mint"})


def test_oauth2_主体を止めるとトークンが即座に効かなくなる(db, client_with_keys):
    """自己完結の JWT でも、到達範囲は毎回 Client 表から引くので即時に失効する。"""
    c, _, sec = client_with_keys
    tok = oauth2.issue_token(db, client_id="a-web", client_secret=sec, secret_key=SECRET)
    c.active = False
    db.commit()
    with pytest.raises(AuthError):
        oauth2.authenticate(db, tok["access_token"], secret_key=SECRET)


def test_oauth2_誤ったsecretでは発行されない(db, client_with_keys):
    with pytest.raises(AuthError):
        oauth2.issue_token(db, client_id="a-web", client_secret="wrong", secret_key=SECRET)


@pytest.mark.parametrize(
    "kw,why",
    [
        ({"auth": ["oauth2"], "token_secret": "short"}, "短い鍵"),
        ({"auth": ["oauth2"]}, "鍵なし"),
        ({"auth": ["oidc"]}, "issuer なし"),
        ({"auth": []}, "機構なし"),
    ],
)
def test_設定の抜けは起動時に落とす(kw, why):
    """**既定の秘密値は持たない。** 設定し忘れで弱い値のまま動くより、その場で止める。"""
    with pytest.raises(ValueError):
        Settings(**kw).check()


def test_break_glassには期限が要る(db, world, root):
    """恒久的な万能鍵を作らせない。"""
    from arkhe.domain.authz import Invalid

    with pytest.raises(Invalid):
        ops.register_client(
            db, root, client_id="bg", naan="99999", authority=Authority.NAAN.value
        )
