"""Engines and sessions. The minter and the resolver connect to different databases.

This does what a database router does in the Django version. A resolver only reads, so
it can be pointed at a read-only role and at a replica. With ARKHE_READ_DATABASE_URL
unset, both use the same database.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from arkhe.settings import Settings, get_settings


@lru_cache
def _engines(
    url: str, read_url: str, size: int, overflow: int, recycle: int, pre_ping: bool
) -> tuple[Engine, Engine]:
    """Build the write and read engines, keyed by URL.

    They hold pools, so they must not be rebuilt per request. The key is the URL rather
    than the settings object, so that several Settings pointing at the same database
    share one pool. The pool values are part of the key too: a different size is a
    different pool.
    """
    # Pool size multiplies by the number of workers. On the defaults that is up to 15
    # connections per process, so two resolvers with four workers each reach 120, past
    # PostgreSQL's default max_connections of 100. Hence the knobs.
    pool = {
        "pool_size": size,
        "max_overflow": overflow,
        "pool_recycle": recycle or -1,
        "pool_pre_ping": pre_ping,
        "future": True,
    }
    write = create_engine(url, **pool)
    read = write if read_url == url else create_engine(read_url, **pool)
    return write, read


def engines(settings: Settings | None = None) -> tuple[Engine, Engine]:
    """Return (write, read) for these settings. With the same read_url it is the same
    engine, so a deployment without ARKHE_READ_DATABASE_URL does not open two pools."""
    s = settings or get_settings()
    return _engines(
        s.database_url, s.read_url, s.db_pool_size, s.db_max_overflow, s.db_pool_recycle,
        s.db_pre_ping,
    )


def session_factory(*, read_only: bool = False, settings: Settings | None = None):
    """Return a session factory. read_only decides which engine it binds to.

    Taking it as an argument is fine here, because this is not a FastAPI dependency and
    so it does not appear in the query string. On a request path only get_session is
    called, and that decides from the role. The CLI and seed_demo use the write side.
    """
    write, read = engines(settings)
    return sessionmaker(bind=read if read_only else write, expire_on_commit=False, future=True)


def get_session(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[Session]:
    """The FastAPI dependency. Any exception rolls the session back.

    It takes no plain arguments. FastAPI exposes a dependency's arguments as query
    parameters, so while read_only was one, ?read_only=true appeared on every endpoint
    and a write could be aimed at a replica from outside. Anything received through
    Depends does not become a query parameter, which is why the settings arrive this
    way.

    Which database is used follows the role of the process (ARKHE_RESOLVER) and is not
    switched per request. The role is read from the settings this app actually uses:
    reading get_settings(), which caches the environment, would mean looking at
    different settings from the app built with create_app(settings=...), and an app
    meant to be a resolver could end up connected to the write database.
    """
    factory = session_factory(read_only=settings.resolver, settings=settings)
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
