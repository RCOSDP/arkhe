"""テストの土台。**本番と同じ経路を通す**——認可も採番も差し替えない。

DB は SQLite の in-memory。`StaticPool` を使うのは、既定だと接続ごとに別の DB に
なってしまうため（TestClient は別スレッドから引く）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from arkhe.api import admin as admin_router
from arkhe.api import mint as mint_router
from arkhe.api import resolve as resolve_router
from arkhe.app import _install_handlers
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
    """システム管理者。台帳を組み立てるのに使う。"""
    return Principal(client_id="test-root", naan="", authority=Authority.SYSTEM)


@pytest.fixture
def world(db, root):
    """NAAN 1 つ・機関 2 つの最小の台帳。

    **機関を 2 つ置くのが要点。** 1 つだと「他機関に届かないこと」を確かめられない。
    """
    ops.create_naan(db, root, naan="99999", name="RA", na_policy="NP | NR, OP, CC | 2026")
    ops.create_naan(db, root, naan="88888", name="別 RA")
    db.flush()
    a, sh_a = ops.onboard_manager(db, root, naan="99999", name="A機関", shoulder="/a1")
    b, sh_b = ops.onboard_manager(db, root, naan="99999", name="B機関", shoulder="/b2")
    c, sh_c = ops.onboard_manager(db, root, naan="88888", name="C機関", shoulder="/c3")
    db.commit()
    return {
        "a": a, "b": b, "c": c,
        "sh_a": sh_a, "sh_b": sh_b, "sh_c": sh_c,
    }


ALL_SCOPES = frozenset({"ark:mint", "ark:update", "ark:read", "ark:tombstone"})


@pytest.fixture
def principal_of():
    """到達範囲を変えた主体を作る。"""

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
    """**認証だけを差し替える。認可は本物を通す。**"""

    def use(principal: Principal) -> TestClient:
        # API と管理画面で主体の解決経路が違う（管理画面はセッションや前段ヘッダも
        # 見る）。**どちらも差し替える**——テストで見たいのは認可であって、
        # 「どうやって認証したか」ではない。
        app.dependency_overrides[deps.current_principal] = lambda: principal
        app.dependency_overrides[admin_router.admin_principal] = lambda: principal
        return TestClient(app, follow_redirects=False)

    return use
