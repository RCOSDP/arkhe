"""認可。**arklet で見つかった欠陥が再発しないことを固定する。**

M3  update が shoulder を見ておらず、同一 NAAN の任意の ARK を書き換えられた
M4  読み取りに認可が無かった
M5  順序不定の queryset を入力と zip し、別の ARK に他レコードの値を書き込みえた
R1  {naan, shoulder} を本文で受けていたため、他組織の名前空間に採番できた
"""

from __future__ import annotations

import pytest

from arkhe.auth.errors import Forbidden, InsufficientScope
from arkhe.db.models import Authority
from arkhe.domain import authz, minting
from arkhe.domain.authz import Invalid, NotFound

# ------------------------------------------------------------- shoulder の決定


def test_shoulder省略時は組織の既定が使われる(db, world, principal_of):
    p = principal_of(manager=world["a"])
    assert authz.shoulder_for(db, p, None).shoulder == "/a1"


def test_shoulder自組織のものは明示できる(db, world, root, principal_of):
    from arkhe.domain import admin_ops as ops

    extra = ops.add_shoulder(db, root, naan="99999", shoulder="/a2", manager_id=world["a"].id)
    db.commit()
    p = principal_of(manager=world["a"])
    assert authz.shoulder_for(db, p, "/a2").id == extra.id


def test_R1_他組織の名前空間は指定しても届かない(db, world, principal_of):
    """**arklet はここが穴で、設定ミスでも詐称でも他組織に採番できた。**"""
    p = principal_of(manager=world["a"])
    with pytest.raises(Forbidden):
        authz.shoulder_for(db, p, "/b2")


def test_R1_存在しないshoulderと他組織のshoulderを区別させない(db, world, principal_of):
    """**存在の有無を漏らさない。**

    実在する他組織の shoulder と、そもそも無い shoulder が**同じ形の拒否**に
    なること。区別できると総当たりで他組織の構成を探れる。返る文字列に差が出るのは
    呼び出し側が送った値がそのまま入るところだけなので、そこを伏せて比べる。
    """
    p = principal_of(manager=world["a"])
    with pytest.raises(Forbidden) as a:
        authz.shoulder_for(db, p, "/b2")  # 実在する（B組織のもの）
    with pytest.raises(Forbidden) as b:
        authz.shoulder_for(db, p, "/zz")  # 実在しない
    assert str(a.value).replace("/b2", "…") == str(b.value).replace("/zz", "…")


def test_shoulder固定された主体は固定先だけ(db, world, principal_of):
    p = principal_of(manager=world["a"], shoulder=world["sh_a"])
    assert authz.shoulder_for(db, p, None).shoulder == "/a1"
    with pytest.raises(Forbidden):
        authz.shoulder_for(db, p, "/b2")


def test_NAAN単位は明示が必須(db, world, principal_of):
    """既定を持たせない——誤って他組織の shoulder に打つ事故を防ぐ。"""
    p = principal_of(authority=Authority.NAAN)
    with pytest.raises(Invalid):
        authz.shoulder_for(db, p, None)
    assert authz.shoulder_for(db, p, "/b2").shoulder == "/b2"


def test_NAAN単位でも他NAANには届かない(db, world, principal_of):
    p = principal_of(authority=Authority.NAAN, naan="99999")
    with pytest.raises(Invalid):
        authz.shoulder_for(db, p, "/c3")


def test_system_は全NAANに届く(db, world, principal_of):
    p = principal_of(authority=Authority.SYSTEM, naan="")
    assert authz.shoulder_for(db, p, "/c3").naan == "88888"


def test_system_でも曖昧なら勝手に選ばない(db, world, root, principal_of):
    """同じ shoulder 文字列が複数 NAAN にありうる。**どれかを黙って選ばない。**"""
    from arkhe.domain import admin_ops as ops

    ops.add_shoulder(db, root, naan="88888", shoulder="/a1")
    db.commit()
    p = principal_of(authority=Authority.SYSTEM, naan="")
    with pytest.raises(Invalid) as e:
        authz.shoulder_for(db, p, "/a1")
    assert sorted(e.value.detail["naans"]) == ["88888", "99999"]


# ------------------------------------------------------------- 既存 ARK への到達


def test_M3_他組織のARKは更新できない(db, world, principal_of):
    """**arklet の update は shoulder を見ておらず、同一 NAAN の任意の ARK を
    書き換えられた。** 採番より重い——永続識別子の乗っ取りになる。"""
    ark, _ = minting.mint(db, shoulder=world["sh_b"], created_by="b")
    db.commit()
    p = principal_of(manager=world["a"])
    with pytest.raises(Forbidden):
        authz.assert_may_touch(db, p, ark)


def test_M3_自組織のARKは更新できる(db, world, principal_of):
    ark, _ = minting.mint(db, shoulder=world["sh_a"], created_by="a")
    db.commit()
    authz.assert_may_touch(db, principal_of(manager=world["a"]), ark)


def test_M3_NAAN単位は配下すべてに届く(db, world, principal_of):
    ark, _ = minting.mint(db, shoulder=world["sh_b"], created_by="b")
    db.commit()
    authz.assert_may_touch(db, principal_of(authority=Authority.NAAN), ark)


def test_M3_NAAN単位でも他NAANのARKには届かない(db, world, principal_of):
    ark, _ = minting.mint(db, shoulder=world["sh_c"], created_by="c")
    db.commit()
    with pytest.raises(Forbidden):
        authz.assert_may_touch(db, principal_of(authority=Authority.NAAN, naan="99999"), ark)


# ------------------------------------------------------------- 読み取りと一括


def test_M4_読み取りも到達範囲に絞る(db, world, principal_of):
    """**arklet は読み取りに認可を一切していなかった。**"""
    mine, _ = minting.mint(db, shoulder=world["sh_a"], created_by="a")
    theirs, _ = minting.mint(db, shoulder=world["sh_b"], created_by="b")
    db.commit()
    got = authz.visible_arks(db, principal_of(manager=world["a"]), [mine.ark, theirs.ark])
    assert [a.ark for a in got] == [mine.ark]


def test_M5_辞書で引き当てる(db, world, principal_of):
    """**arklet は順序不定の queryset を入力と zip していた**ため、別の ARK に
    他レコードの値を書き込みうるデータ破壊バグがあった。"""
    arks = [minting.mint(db, shoulder=world["sh_a"], created_by="a")[0] for _ in range(5)]
    db.commit()
    keys = [a.ark for a in arks]
    found = authz.fetch_for_update(db, principal_of(manager=world["a"]), keys)
    assert all(found[k].ark == k for k in keys)


def test_M5_一件でも欠ければ全体を失敗させる(db, world, principal_of):
    """**部分適用しない。** 件数が合わないのを黙って切り詰めるのが arklet の欠陥。"""
    ark, _ = minting.mint(db, shoulder=world["sh_a"], created_by="a")
    db.commit()
    with pytest.raises(NotFound):
        authz.fetch_for_update(db, principal_of(manager=world["a"]), [ark.ark, "99999/nope"])


def test_M5_範囲外が混ざっても全体を失敗させる(db, world, principal_of):
    mine, _ = minting.mint(db, shoulder=world["sh_a"], created_by="a")
    theirs, _ = minting.mint(db, shoulder=world["sh_b"], created_by="b")
    db.commit()
    with pytest.raises(NotFound):
        authz.fetch_for_update(db, principal_of(manager=world["a"]), [mine.ark, theirs.ark])


# ------------------------------------------------------------- scope と上限


def test_scope_が足りなければ拒む(principal_of):
    p = principal_of(scopes={"ark:read"})
    with pytest.raises(InsufficientScope) as e:
        authz.require_scope(p, "ark:mint")
    assert e.value.required == "ark:mint"


def test_R3_組織単位の日次上限(db, world, principal_of, root):
    world["a"].quota_per_day = 2
    db.commit()
    p = principal_of(manager=world["a"])
    minting.mint(db, shoulder=world["sh_a"], created_by="a")
    minting.mint(db, shoulder=world["sh_a"], created_by="a")
    db.commit()
    with pytest.raises(authz.Throttled):
        authz.assert_within_quota(db, p)


def test_R3_break_glassは上限の対象外(db, world, principal_of):
    """障害対応で止まっては困る。"""
    world["a"].quota_per_day = 0
    db.commit()
    authz.assert_within_quota(db, principal_of(authority=Authority.NAAN))


# ------------------------------------------------------------- shoulder の状態


def test_リザーブ枠では採番しない(db, world, root):
    from arkhe.domain import admin_ops as ops

    sh = ops.add_shoulder(db, root, naan="99999", shoulder="/rs")
    db.commit()
    sh.status = "reserved"
    with pytest.raises(Forbidden):
        authz.assert_shoulder_mintable(sh)


def test_委譲されたshoulderは行き先を添えて拒む(db, world, root):
    from arkhe.domain import admin_ops as ops

    sh = ops.add_shoulder(db, root, naan="99999", shoulder="/dg")
    db.commit()
    ops.set_shoulder_status(
        db, root, shoulder_id=sh.id, status="delegated", minter="https://mint.example.org"
    )
    db.commit()
    with pytest.raises(authz.ShoulderDelegated) as e:
        authz.assert_shoulder_mintable(sh)
    assert e.value.minter == "https://mint.example.org"


# ------------------------------------------------------------- 監査


def test_R2_NAAN以上の操作は記録される(db, world, principal_of):
    from sqlalchemy import select

    from arkhe.db.models import AuditEvent

    before = len(db.scalars(select(AuditEvent)).all())  # 台帳の組み立てぶん
    authz.audit(db, principal_of(authority=Authority.NAAN), "mint", "99999/x")
    authz.audit(db, principal_of(manager=world["a"]), "mint", "99999/y")
    db.commit()
    added = db.scalars(select(AuditEvent)).all()[before:]
    # **組織単位（manager）の操作は記録しない。** 届く範囲が狭いほど、
    # 全件記録の必要は下がる。
    assert [r.target for r in added] == ["99999/x"]
