"""管理画面から台帳を組む操作。

**画面の出し分けと実際の認可が同じ判定であること**を見る。別々になっていると
「ボタンは出ないが POST は通る」穴ができる——ここで確かめたいのはそれ。
"""

from __future__ import annotations

import pytest

from arkhe.db.models import Authority, Manager, Naan, Shoulder

# ------------------------------------------------ 約束の水準（組織自身の宣言）


def test_組織管理者は自組織の約束を変えられる(db, world, principal_of, as_principal):
    """**約束は組織自身のもの。** 述べる主体が述べられなければ意味がない。"""
    a = world["a"]
    c = as_principal(principal_of(manager=a))
    r = c.post(f"/admin/manager/{a.id}", data={"commitment": "permanent-unchanging"})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Manager, a.id).commitment_level == "permanent-unchanging"


def test_組織管理者は他組織の約束を変えられない(db, world, principal_of, as_principal):
    a, b = world["a"], world["b"]
    c = as_principal(principal_of(manager=a))
    r = c.post(f"/admin/manager/{b.id}", data={"commitment": "not-guaranteed"})
    assert r.status_code == 403
    db.expire_all()
    assert db.get(Manager, b.id).commitment_level != "not-guaranteed"


def test_システム管理者はどの組織の約束も変えられる(db, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.SYSTEM))
    r = c.post(f"/admin/manager/{world['c'].id}", data={"commitment": "descriptive-only"})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Manager, world["c"].id).commitment_level == "descriptive-only"


def test_組織管理者は自組織の採番上限を外せない(db, world, principal_of, as_principal):
    """**上限は配った側が課すもの。** 課された側が外せては意味がない。"""
    a = world["a"]
    a.quota_per_day = 10
    db.commit()
    c = as_principal(principal_of(manager=a))
    r = c.post(f"/admin/manager/{a.id}", data={"commitment": "permanent-stable", "quota": ""})
    assert r.status_code == 303          # 約束のほうは通る
    db.expire_all()
    assert db.get(Manager, a.id).quota_per_day == 10   # 上限は動かない


# ---------------------------------------- NAA ポリシー（名前空間を配る側の宣言）


def test_NAAポリシーは組織管理者には変えられない(db, world, principal_of, as_principal):
    """**NAAN 配下の全組織にかかる宣言。** 1 組織が他組織の分まで書き換えられない。"""
    before = db.get(Naan, "99999").na_policy
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/admin/naan/99999", data={"policy": "書き換えた", "minter": ""})
    assert r.status_code == 403
    db.expire_all()
    assert db.get(Naan, "99999").na_policy == before


def test_NAAN管理者はポリシーを宣言できる(db, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.NAAN))
    r = c.post("/admin/naan/99999", data={"policy": "NP | NR, OP, CC | 2027 |", "minter": ""})
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Naan, "99999").na_policy == "NP | NR, OP, CC | 2027 |"


def test_NAANの登録はシステム管理者だけ(db, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.NAAN))
    assert c.get("/admin/naan/new").status_code == 403
    assert c.post(
        "/admin/naan/new", data={"naan": "77777", "name": "x"}
    ).status_code == 403


# ------------------------------------------------------------ 画面が届く範囲


def test_NAANの設定画面は組織管理者には開けない(world, principal_of, as_principal):
    """**開ける条件と保存できる条件を揃える。**

    開けてしまうと、編集できるように見えるフォームが保存で 403 になる。
    出し分けと認可がずれているのと同じ。
    """
    c = as_principal(principal_of(manager=world["a"]))
    assert c.get("/admin/naan/99999").status_code == 403


def test_他組織の設定画面は開けない(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    assert c.get(f"/admin/manager/{world['b'].id}").status_code == 403


def test_自組織の設定画面は開ける(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    r = c.get(f"/admin/manager/{world['a'].id}")
    assert r.status_code == 200
    assert "permanent-dynamic" in r.text


def test_一覧に自組織への導線が出る(world, principal_of, as_principal):
    """**約束は組織自身のものなので、組織管理者にも導線を出す。**"""
    a = world["a"]
    r = as_principal(principal_of(manager=a)).get("/admin/")
    assert f"/admin/manager/{a.id}" in r.text
    # NAAN の設定と shoulder の操作は出さない（届かないので）
    assert "/admin/naan/99999" not in r.text
    assert "/admin/naan/new" not in r.text


# -------------------------------------------------------------- 組み立て操作


def test_オンボードは画面からもできる(db, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.NAAN))
    r = c.post("/admin/manager/new", data={
        "naan": "99999", "name": "D組織", "shoulder": "/d4",
        "commitment": "permanent-stable", "quota": "100",
    })
    assert r.status_code == 303
    m = db.scalar(db.query(Manager).filter_by(name="D組織").statement)
    assert m.commitment_level == "permanent-stable"
    assert m.quota_per_day == 100
    # **組織と名前空間は必ず対で作られる。**
    assert db.get(Shoulder, m.default_shoulder_id).shoulder == "/d4"


def test_shoulderはretiredから戻せない(db, world, principal_of, as_principal):
    """画面から入っても不変条件は同じ——判定は `admin_ops` にしかない。"""
    sh = world["sh_a"]
    c = as_principal(principal_of(authority=Authority.NAAN))
    assert c.post(f"/admin/shoulder/{sh.id}", data={"status": "retired"}).status_code == 303
    db.expire_all()
    r = c.post(f"/admin/shoulder/{sh.id}", data={"status": "active"})
    # **403 ではなく 400。** 権限の問題ではなく、誰にも許されていない操作。
    assert r.status_code == 400
    db.expire_all()
    assert db.get(Shoulder, sh.id).status == "retired"


@pytest.mark.parametrize("level", ["permanent", "eternal", ""])
def test_知らない水準は画面からも入らない(db, world, principal_of, as_principal, level):
    a = world["a"]
    before = a.commitment_level
    c = as_principal(principal_of(manager=a))
    r = c.post(f"/admin/manager/{a.id}", data={"commitment": level})
    db.expire_all()
    if level == "":
        assert r.status_code == 303      # 空は「変えない」
    else:
        assert r.status_code == 400
    assert db.get(Manager, a.id).commitment_level == before
