"""マイグレーションが**実際に流れること**。

テストは `Base.metadata.create_all` で表を作る——速いが、**マイグレーションを
1 行も通らない**。だから移行の壊れは、ここに検査を置かないかぎり、誰かが
`alembic upgrade head` を打つまで見つからない。実際そうなっていた：
Quickstart に書いてあるとおり SQLite で打つと、3 本目で落ちていた。

**PostgreSQL での往復は `scripts/check.sh` が見る**（SQLite は PostgreSQL が
弾くスキーマを通すので、あちらが本番）。ここで見るのは別のこと——**文書に
書いた手順が、書いたとおりに動くか**である。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _alembic(*args: str, url: str) -> subprocess.CompletedProcess:
    """**利用者と同じ道を通す。** ライブラリとして呼ぶと `env.py` を迂回できて
    しまうが、迂回した先に落ちる場所があった。"""
    env = {
        **os.environ,
        "ARKHE_DATABASE_URL": url,
        "ARKHE_AUTH": "apikey",
        # 設定の検査に引っかからないように、口の無い構成の既定だけ与える。
        "ARKHE_ADMIN_LOGIN": "bearer",
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )


def test_SQLiteでもマイグレーションが頭まで流れる(tmp_path):
    """**Quickstart に書いてある手順そのもの。**

    SQLite には制約を付け外しする `ALTER` が無いので、`create_foreign_key` や
    `drop_constraint` は batch（表を作り直して移し替える）を通す必要がある。
    素で書くと `NotImplementedError` で止まる——**PostgreSQL だけで検証して
    いるあいだ、それが見えない。**
    """
    url = f"sqlite:///{tmp_path / 'arkhe.db'}"
    up = _alembic("upgrade", "head", url=url)
    assert up.returncode == 0, up.stderr[-3000:]

    down = _alembic("downgrade", "base", url=url)
    assert down.returncode == 0, down.stderr[-3000:]

    again = _alembic("upgrade", "head", url=url)
    assert again.returncode == 0, again.stderr[-3000:]


def test_移行後のスキーマがモデルと同じ形をしている(tmp_path):
    """**移行を流した DB と、`create_all` で作った DB を突き合わせる。**

    テストが見ているのは後者なので、ここが揃っていないと「テストは緑だが
    本番のスキーマは違う」が成立してしまう。

    列の**幅は見ない**——`d2a7f4b81c63` が書いているとおり、SQLite では
    varchar の長さを見ないので広げる移行を流していない。ここで見るのは
    **表と列と、その有無**である。
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
    assert tables <= set(migrated.get_table_names()), "移行で作られていない表がある"
    for table in sorted(tables):
        want = {c["name"] for c in declared.get_columns(table)}
        got = {c["name"] for c in migrated.get_columns(table)}
        assert want == got, (
            f"{table}: 宣言と移行後で列が違う（不足 {want - got} / 余り {got - want}）"
        )
