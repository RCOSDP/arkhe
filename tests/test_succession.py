"""承継と離脱。**管理主体がどう変わっても、識別子は壊さない。**

`NR`（再割当てしない）を宣言している以上、配ってしまった名前は振り直せない——
振り直すことは元の識別子を殺すこと。だから解決は続け、変えるのは「誰が新規に
採番するか」と「どこへ転送するか」だけ。
"""

from __future__ import annotations

import pytest

from arkhe.db.repository import SqlArkRepository
from arkhe.domain import admin_ops as ops
from arkhe.domain import minting
from arkhe.domain.authz import Invalid
from arkhe.domain.resolution import Outcome, resolve


def _resolve(db, key):
    naan, name = key.split("/", 1)
    return resolve(SqlArkRepository(db), naan, name)


def test_承継しても解決先は変わらない(db, world, root):
    arks = [
        minting.mint(db, shoulder=world["sh_a"], created_by="a", url=f"https://a/{i}")[0]
        for i in range(3)
    ]
    db.commit()
    keys = [a.ark for a in arks]

    ops.succeed(db, root, predecessor_id=world["a"].id, successor_id=world["b"].id)
    db.commit()

    for i, k in enumerate(keys):
        r = _resolve(db, k)
        assert r.outcome is Outcome.REDIRECT
        assert r.location == f"https://a/{i}"  # **無傷**


def test_承継すると名前空間の預かり主が変わる(db, world, root):
    ops.succeed(db, root, predecessor_id=world["a"].id, successor_id=world["b"].id)
    db.commit()
    assert world["sh_a"].manager_id == world["b"].id
    assert world["a"].succeeded_by_id == world["b"].id
    assert world["a"].active is False


def test_承継後は旧名前空間で新規採番できない(db, world, root):
    ops.succeed(db, root, predecessor_id=world["a"].id, successor_id=world["b"].id, retire=True)
    db.commit()
    assert world["sh_a"].status == "retired"


def test_承継はNAANを跨げない(db, world, root):
    """跨ぐと識別子の形が変わる＝別の名前になってしまう。"""
    with pytest.raises(Invalid):
        ops.succeed(db, root, predecessor_id=world["a"].id, successor_id=world["c"].id)


def test_離脱_転送先を機関のリゾルバへ一括で向け直す(db, world, root):
    arks = [
        minting.mint(db, shoulder=world["sh_a"], created_by="a", url="https://old/x")[0]
        for _ in range(2)
    ]
    db.commit()
    r = ops.depart(
        db, root, manager_id=world["a"].id,
        resolver_template="https://repo.example.ac.jp/ark/${blade}",
    )
    db.commit()
    assert r["rewritten"] == 2
    for a in arks:
        res = _resolve(db, a.ark)
        assert res.location.startswith("https://repo.example.ac.jp/ark/")


def test_離脱_未登録の名前も機関のリゾルバへ流れる(db, world, root):
    """**継続作業を要求する形にすると放置されて死んだリンクが残る。**
    以後の運用が機関側に閉じるよう、shoulder にも同じ委譲を置く。"""
    from arkhe.arkspec.betanumeric import check_digit_base, noid_check_digit

    ops.depart(
        db, root, manager_id=world["a"].id,
        resolver_template="https://repo.example.ac.jp/ark/${blade}",
    )
    db.commit()
    stem = "a1zzzzzzzz"
    name = stem + noid_check_digit(check_digit_base("99999", stem))
    res = _resolve(db, f"99999/{name}")
    assert res.outcome is Outcome.REDIRECT
    assert res.reason == "delegated by shoulder"


def test_離脱_新規採番は止まるが解決は続く(db, world, root):
    ark, _ = minting.mint(db, shoulder=world["sh_a"], created_by="a", url="https://old/x")
    db.commit()
    ops.depart(db, root, manager_id=world["a"].id)
    db.commit()
    assert world["sh_a"].status == "retired"
    assert _resolve(db, ark.ark).outcome is Outcome.REDIRECT  # **解決は続く**


def test_離脱_更新権限だけ残せる(db, world, root):
    """scope を分けた設計がここで効く——新規採番はできないが、転送先の付け替えは
    自分でできる。"""
    r = ops.depart(db, root, manager_id=world["a"].id, keep_update_label="self-managed")
    db.commit()
    assert r["update_secret"]
    from arkhe.auth import apikey

    p = apikey.authenticate(db, r["update_secret"])
    assert p.scopes == frozenset({"ark:update"})


def test_離脱で古い鍵は止まるが行は残る(db, world, root):
    from sqlalchemy import select

    from arkhe.db.models import Client

    ops.register_client(db, root, client_id="a-web", naan="99999", manager_id=world["a"].id)
    db.commit()
    ops.depart(db, root, manager_id=world["a"].id)
    db.commit()
    still = db.scalar(select(Client).where(Client.client_id == "a-web"))
    assert still is not None and still.active is False  # 誰の鍵だったかを残す
