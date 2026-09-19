"""That the migrations actually run.

The rest of the suite builds its tables with Base.metadata.create_all. That is fast, but
it runs no migration at all, so a broken migration stays hidden until someone types
alembic upgrade head. That happened: following the Quickstart on SQLite failed at the
third migration.

The round trip on PostgreSQL is scripts/check.sh's job, and that is the one that counts,
because SQLite accepts schemas PostgreSQL rejects. What is checked here is different:
whether the procedure in the documentation works as written.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _alembic(*args: str, url: str) -> subprocess.CompletedProcess:
    """Take the same path a user takes. Calling alembic as a library skips env.py, and
    there was a failure hiding on the path that skips it."""
    env = {
        **os.environ,
        "ARKHE_DATABASE_URL": url,
        "ARKHE_AUTH": "apikey",
        # Just enough to pass the settings check for a deployment with no admin login.
        "ARKHE_ADMIN_LOGIN": "bearer",
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )


def test_migrations_run_to_head_on_sqlite_too(tmp_path):
    """Exactly the procedure the Quickstart describes.

    SQLite has no ALTER for adding or dropping constraints, so create_foreign_key and
    drop_constraint have to go through batch mode, which rebuilds the table and copies
    the rows. Written plainly they stop with NotImplementedError, and that is invisible
    while only PostgreSQL is being checked.
    """
    url = f"sqlite:///{tmp_path / 'arkhe.db'}"
    up = _alembic("upgrade", "head", url=url)
    assert up.returncode == 0, up.stderr[-3000:]

    down = _alembic("downgrade", "base", url=url)
    assert down.returncode == 0, down.stderr[-3000:]

    again = _alembic("upgrade", "head", url=url)
    assert again.returncode == 0, again.stderr[-3000:]


def test_the_migrated_schema_matches_the_models(tmp_path):
    """Compare a database built by the migrations with one built by create_all.

    The rest of the suite looks at the second one, so if they differ it is possible for
    the tests to pass while the production schema is something else.

    Column widths are not compared. As migration d2a7f4b81c63 notes, SQLite ignores
    varchar lengths, so the widening migration is not run there. What is compared is
    which tables and columns exist.
    """
    import sqlalchemy as sa

    from arkhe.db.models import Base

    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    assert _alembic("upgrade", "head", url=url).returncode == 0

    migrated = sa.inspect(sa.create_engine(url))
    fresh = sa.create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    Base.metadata.create_all(fresh)
    declared = sa.inspect(fresh)

    tables = set(declared.get_table_names())
    assert tables <= set(migrated.get_table_names()), "a table is missing after migrating"
    for table in sorted(tables):
        want = {c["name"] for c in declared.get_columns(table)}
        got = {c["name"] for c in migrated.get_columns(table)}
        assert want == got, (
            f"{table}: columns differ (missing {want - got}, unexpected {got - want})"
        )
