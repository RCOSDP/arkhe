"""運用コマンド。**画面と同じ式を通ることを確かめる。**

CLI は `_root()` でシステム管理者として動くので、ここで見たいのは認可ではなく
**絞り込みと打ち切り**——「これで全部」と読み違えないこと。
"""

from __future__ import annotations

from typer.testing import CliRunner

from arkhe import cli
from arkhe.auth.principal import Principal
from arkhe.db.models import Authority
from arkhe.domain import minting
from arkhe.domain.queries import narrow_arks, visible_arks

runner = CliRunner()


def _run(factory, *args):
    """CLI を叩く。**DB だけ差し替える**（認可も出力も本物を通す）。"""
    from contextlib import contextmanager

    @contextmanager
    def session():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    orig, cli._session = cli._session, session
    try:
        return runner.invoke(cli.app, list(args))
    finally:
        cli._session = orig


def _mint(db, shoulder, n, *, by="minter", url="https://例.jp/{i}", title=""):
    out = []
    for i in range(n):
        ark, _ = minting.mint(
            db, shoulder=shoulder, created_by=by, url=url.format(i=i), title=title
        )
        out.append(ark)
    db.commit()
    return out


def test_ark_listは発行したarkを出す(db, factory, world):
    _mint(db, world["sh_a"], 2)
    r = _run(factory, "ark", "list")
    assert r.exit_code == 0
    assert r.stdout.count("ark:/99999/a1") == 2
    # **行き先が出ること。** 一覧から目で追って写す列なので、これが無いと使えない。
    assert "https://例.jp/0" in r.stdout


def test_該当が無いときは黙らない(db, factory, world):
    r = _run(factory, "ark", "list")
    assert r.exit_code == 0
    assert "該当なし" in r.output or "nothing matched" in r.output


def test_打ち切ったことを知らせる(db, factory, world):
    _mint(db, world["sh_a"], 5)
    r = _run(factory, "ark", "list", "--limit", "2")
    assert r.exit_code == 0
    # 上限ちょうどで止まり、**続きの入り口を示す**。示さなければ「これで全部」と読まれる。
    assert r.stdout.count("ark:/") == 2
    assert "--offset 2" in r.output


def test_打ち切っていないときは知らせない(db, factory, world):
    _mint(db, world["sh_a"], 2)
    r = _run(factory, "ark", "list", "--limit", "2")
    assert "--offset" not in r.output


def test_offsetで続きが取れる(db, factory, world):
    _mint(db, world["sh_a"], 5)
    first = _run(factory, "ark", "list", "--limit", "2").stdout
    rest = _run(factory, "ark", "list", "--limit", "2", "--offset", "2").stdout
    got = {ln.split()[0] for ln in (first + rest).splitlines() if ln.startswith("ark:/")}
    assert len(got) == 4  # 重複なく続いている


def test_naanと組織で絞る(db, factory, world):
    _mint(db, world["sh_a"], 1)
    _mint(db, world["sh_b"], 1)
    _mint(db, world["sh_c"], 1)  # 別 NAAN

    assert _run(factory, "ark", "list", "--naan", "88888").stdout.count("ark:/") == 1
    out = _run(factory, "ark", "list", "--org", str(world["a"].id)).stdout
    assert "ark:/99999/a1" in out and "ark:/99999/b2" not in out


def test_検索はark行き先題名の3つを見る(db, factory, world):
    """**画面と同じ 3 項目。** 運用で手元にあるのがどれか分からないため。"""
    _mint(db, world["sh_a"], 1, url="https://見つかる.jp/x", title="無関係")
    _mint(db, world["sh_b"], 1, url="https://別.jp/y", title="探したい題名")

    assert _run(factory, "ark", "list", "-q", "見つかる").stdout.count("ark:/") == 1
    assert _run(factory, "ark", "list", "-q", "探したい").stdout.count("ark:/") == 1
    # ARK そのものでも引ける
    assert _run(factory, "ark", "list", "-q", "a1").stdout.count("ark:/") == 1


def test_絞り込みは到達範囲の外に出る鍵にならない(db, world):
    """**画面と CLI が同じ式を通る**ことの肝。

    組織単位の主体が別組織を `--org` に指定しても、`visible_arks` で先に
    絞ってあるので何も出ない。
    """
    _mint(db, world["sh_a"], 1)
    _mint(db, world["sh_b"], 1)
    only_a = Principal(
        client_id="c", naan="99999", authority=Authority.MANAGER, manager_id=world["a"].id
    )
    stmt = narrow_arks(visible_arks(only_a), org=str(world["b"].id))
    assert db.scalars(stmt).all() == []
