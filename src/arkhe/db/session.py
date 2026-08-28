"""エンジンとセッション。**minter と resolver で接続先を分ける。**

Django 版の DB ルータに相当する。resolver は読み取りしかしないので、読み取り専用
ロールとレプリカに向けられる。`ARKHE_READ_DATABASE_URL` が未設定なら同じ DB を使う。
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from arkhe.settings import Settings, get_settings


@lru_cache
def _engines(url: str, read_url: str) -> tuple[Engine, Engine]:
    write = create_engine(url, pool_pre_ping=True, future=True)
    read = write if read_url == url else create_engine(read_url, pool_pre_ping=True, future=True)
    return write, read


def engines(settings: Settings | None = None) -> tuple[Engine, Engine]:
    s = settings or get_settings()
    return _engines(s.database_url, s.read_url)


def session_factory(*, read_only: bool = False, settings: Settings | None = None):
    write, read = engines(settings)
    return sessionmaker(bind=read if read_only else write, expire_on_commit=False, future=True)


def get_session(*, read_only: bool = False) -> Iterator[Session]:
    """FastAPI の依存として使う。**例外時は必ず巻き戻す。**"""
    factory = session_factory(read_only=read_only)
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
