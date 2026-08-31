"""エンジンとセッション。**minter と resolver で接続先を分ける。**

Django 版の DB ルータに相当する。resolver は読み取りしかしないので、読み取り専用
ロールとレプリカに向けられる。`ARKHE_READ_DATABASE_URL` が未設定なら同じ DB を使う。
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
def _engines(url: str, read_url: str) -> tuple[Engine, Engine]:
    """書き込み用と読み取り用のエンジンを作る。**URL で覚える。**

    プールを持つので、要求ごとに作り直してはいけない。設定の器ではなく URL を鍵に
    するのは、同じ接続先を指す `Settings` が複数あってもプールを 1 つに保つため。
    """
    write = create_engine(url, pool_pre_ping=True, future=True)
    read = write if read_url == url else create_engine(read_url, pool_pre_ping=True, future=True)
    return write, read


def engines(settings: Settings | None = None) -> tuple[Engine, Engine]:
    """設定から (書き込み, 読み取り) を引く。`read_url` が同じなら**同一の器**を返す
    ——`ARKHE_READ_DATABASE_URL` を置いていない構成で、接続先が二重にならない。"""
    s = settings or get_settings()
    return _engines(s.database_url, s.read_url)


def session_factory(*, read_only: bool = False, settings: Settings | None = None):
    """セッションの作り手を返す。**`read_only` で向き先が変わる。**

    ここは引数で受けてよい（FastAPI の依存ではないので、クエリには出ない）。
    要求の経路から呼ぶのは `get_session` だけで、そちらは役割から決める。
    CLI と `seed_demo` は書き込み側を使う。
    """
    write, read = engines(settings)
    return sessionmaker(bind=read if read_only else write, expire_on_commit=False, future=True)


def get_session(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[Session]:
    """FastAPI の依存として使う。**例外時は必ず巻き戻す。**

    **平の引数を取らない。** FastAPI は依存の引数をクエリパラメータとして公開するので、
    `read_only` を平の引数で受けていたころは `?read_only=true` が全エンドポイントに
    生えていた——**採番の書き込みを、外からレプリカへ向けられた**。`Depends` で
    受けるものはクエリにならないので、設定はこの形で通す。

    向き先を決めるのは**プロセスの役割**（`ARKHE_RESOLVER`）であって、要求ごとに
    切り替えるものではない。**その役割は、この app が実際に使っている設定から引く**
    ——`get_settings()`（環境変数のキャッシュ）を直に読むと、`create_app(settings=…)`
    で建てた app とは別の設定を見ることになり、resolver として建てたつもりの app が
    書き込み DB に繋ぐ、といったずれが起きる。
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
