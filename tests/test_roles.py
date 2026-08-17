"""プロセスの役割ごとに、出す口が変わることを固定する。

**minter は外部公開しうる。** だから管理画面を同居させない——セッション認証の
Django admin がインターネットに露出する。
"""

from __future__ import annotations

import pytest


def _urls_for(settings, role):
    from tests.test_resolution import _use_role

    _use_role(settings, role)
    from jc2ark.entrypoints import urls

    return urls


@pytest.fixture
def role(settings):
    def _set(name):
        return _urls_for(settings, name)

    yield _set
    _urls_for(settings, "minter")


def _paths(urls):
    return {str(p.pattern) for p in urls.urlpatterns}


def test_minter_does_not_expose_the_admin(role):
    """**これが分離の目的。** minter が公開されても管理画面は出ない。"""
    p = _paths(role("minter"))
    assert "mint" in p and "o/" in p
    assert not any("admin" in x for x in p)


def test_admin_role_exposes_only_the_admin(role):
    p = _paths(role("admin"))
    assert p == {"admin/", "healthz"}  # healthz は probe 用（全ロール共通）
    assert "mint" not in p, "管理画面のプロセスから採番させない"
    assert "o/" not in p, "トークン発行もさせない"


def test_resolver_exposes_neither(role):
    p = _paths(role("resolver"))
    assert not any("admin" in x for x in p)
    assert "mint" not in p and "o/" not in p


@pytest.mark.django_db
def test_admin_is_404_on_the_minter(client, settings):
    _urls_for(settings, "minter")
    try:
        assert client.get("/admin/").status_code == 404
    finally:
        _urls_for(settings, "minter")


@pytest.mark.django_db
def test_mint_is_404_on_the_admin_role(client, settings):
    _urls_for(settings, "admin")
    try:
        assert client.post("/mint", data="{}", content_type="application/json").status_code == 404
    finally:
        _urls_for(settings, "minter")


def test_unknown_role_is_rejected(monkeypatch):
    """設定ミスは**起動時に落とす**（動いてから気づくより早い）。"""
    import importlib

    monkeypatch.setenv("JC2ARK_ROLE", "nonsense")
    from jc2ark.entrypoints import settings as s

    with pytest.raises(ValueError, match="minter / resolver / admin"):
        importlib.reload(s)
    monkeypatch.setenv("JC2ARK_ROLE", "minter")
    importlib.reload(s)


# --------------------------------------------------------------------------
# probe は業務エンドポイントに依存させない
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["minter", "resolver", "admin"])
@pytest.mark.django_db
def test_every_role_answers_healthz(client, settings, name):
    """**構成を変えても probe が壊れないようにする。**

    minter から admin を外したとき、`/admin/login/` を見ていた probe が 404 に
    なり、新しい Pod が Ready にならずロールアウトが止まった。probe は業務
    エンドポイントに依存させない。
    """
    from tests.test_resolution import _use_role

    _use_role(settings, name)
    try:
        r = client.get("/healthz", HTTP_HOST="localhost")
        assert r.status_code == 200
        assert r.json() == {"role": name, "db": "ok"}
    finally:
        _use_role(settings, "minter")
