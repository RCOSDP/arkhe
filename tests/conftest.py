"""Fixtures for the unit tests. They go through the real path: neither authorisation
nor minting is substituted.

The database is SQLite in memory. StaticPool is needed because otherwise every
connection gets its own database, and TestClient calls from another thread.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from arkhe import observability
from arkhe.api import admin as admin_router
from arkhe.api import mint as mint_router
from arkhe.api import resolve as resolve_router
from arkhe.app import (
    _install_ark_label_case,
    _install_handlers,
    _install_security_headers,
)
from arkhe.auth import deps
from arkhe.auth.principal import Principal
from arkhe.db import session as session_mod
from arkhe.db.models import Authority, Base
from arkhe.domain import admin_ops as ops
from arkhe.settings import Settings, get_settings


@pytest.fixture
def engine():
    e = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(e)
    return e


@pytest.fixture
def factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def db(factory) -> Session:
    s = factory()
    yield s
    s.close()


@pytest.fixture
def root() -> Principal:
    """The system administrator, used to build the ledger."""
    return Principal(client_id="test-root", naan="", authority=Authority.SYSTEM)


@pytest.fixture
def world(db, root):
    """The smallest ledger: one NAAN and two organisations.

    Two organisations is the point. With one, there is no way to check that reach stops
    at the organisation.
    """
    ops.create_naan(db, root, naan="99999", name="RA", na_policy="NP | NR, OP, CC | 2026")
    ops.create_naan(db, root, naan="88888", name="another RA")
    db.flush()
    a, sh_a = ops.onboard_manager(db, root, naan="99999", name="org A", shoulder="/a1")
    b, sh_b = ops.onboard_manager(db, root, naan="99999", name="org B", shoulder="/b2")
    c, sh_c = ops.onboard_manager(db, root, naan="88888", name="org C", shoulder="/c3")
    db.commit()
    return {
        "a": a, "b": b, "c": c,
        "sh_a": sh_a, "sh_b": sh_b, "sh_c": sh_c,
    }


ALL_SCOPES = frozenset({"ark:mint", "ark:update", "ark:read", "ark:tombstone"})


@pytest.fixture
def principal_of():
    """Build a principal with a given reach."""

    def make(authority=Authority.MANAGER, naan="99999", manager=None, shoulder=None,
             scopes=ALL_SCOPES, client_id="test-client"):
        return Principal(
            client_id=client_id,
            naan=naan,
            authority=authority,
            manager_id=manager.id if manager is not None else None,
            shoulder_id=shoulder.id if shoulder is not None else None,
            scopes=frozenset(scopes),
            mechanism="apikey",
        )

    return make


@pytest.fixture
def settings() -> Settings:
    return Settings(auth=["apikey"], database_url="sqlite://")


@pytest.fixture
def app(factory, settings):
    a = FastAPI()
    _install_handlers(a)
    _install_ark_label_case(a)
    _install_security_headers(a)
    observability.install(a)
    a.include_router(mint_router.router)
    a.include_router(resolve_router.router)
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


@pytest.fixture
def as_principal(app):
    """Substitute authentication only. Authorisation runs for real."""

    def use(principal: Principal) -> TestClient:
        # The API and the admin interface resolve the principal differently: the admin
        # interface also looks at the session and at headers from the proxy in front.
        # Substitute both, because what these tests look at is authorisation, not how
        # the caller authenticated.
        app.dependency_overrides[deps.current_principal] = lambda: principal
        app.dependency_overrides[admin_router.admin_principal] = lambda: principal
        return TestClient(app, follow_redirects=False)

    return use
