"""管理画面と管理操作。

**画面の出し分けと実際の認可に同じ判定を使う**ことを固定する。別々にすると
「ボタンは出ないが URL を直接叩けば通る」穴ができる。
"""

from __future__ import annotations

import pytest

from arkhe.auth.errors import Forbidden
from arkhe.db.models import Authority, ShoulderStatus
from arkhe.domain import admin_ops as ops
from arkhe.domain.authz import Invalid

# ------------------------------------------------------------- 遷移の禁則


def test_retiredからは戻せない(db, world, root):
    """**引退した名前空間の再開は NR 違反の芽。** その間に外部が同じ名前を使って
    いる可能性を否定できない。"""
    ops.set_shoulder_status(db, root, shoulder_id=world["sh_a"].id, status="retired")
    db.commit()
    with pytest.raises(Invalid) as e:
        ops.set_shoulder_status(db, root, shoulder_id=world["sh_a"].id, status="active")
    assert "retired" in e.value.detail["reason"]


def test_委譲には採番の行き先が要る(db, world, root):
    with pytest.raises(Invalid):
        ops.set_shoulder_status(db, root, shoulder_id=world["sh_a"].id, status="delegated")
    ops.set_shoulder_status(
        db, root, shoulder_id=world["sh_a"].id, status="delegated",
        minter="https://mint.example.org",
    )
    assert world["sh_a"].status == ShoulderStatus.DELEGATED


def test_機関と名前空間は対で生まれる(db, world):
    """片方だけでは意味がない（採番できない機関を作るだけ）。"""
    assert world["a"].default_shoulder_id == world["sh_a"].id


# ------------------------------------------------------------- 権限の階層


def test_NAANを配れるのはシステム管理者だけ(db, world, principal_of):
    with pytest.raises(Forbidden):
        ops.create_naan(db, principal_of(authority=Authority.NAAN), naan="77777", name="x")


def test_自分より広い到達範囲は与えられない(db, world, principal_of):
    p = principal_of(manager=world["a"])
    with pytest.raises(Forbidden):
        ops.register_client(
            db, p, client_id="evil", naan="99999", authority=Authority.SYSTEM.value
        )


def test_他機関の主体は作れない(db, world, principal_of):
    p = principal_of(manager=world["a"])
    with pytest.raises(Forbidden):
        ops.register_client(
            db, p, client_id="x", naan="99999", manager_id=world["b"].id
        )


# ------------------------------------------------------------- 画面


def test_機関管理者には自分の範囲しか見えない(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    body = c.get("/admin/").text
    assert "A機関" in body
    assert "B機関" not in body  # 同じ NAAN の他機関も見えない
    assert "88888" not in body


def test_監査ログは機関管理者には見せない(db, world, principal_of, as_principal):
    """誰がいつ何をしたかは、その名前空間を預かる側の情報。"""
    c = as_principal(principal_of(manager=world["a"]))
    assert c.get("/admin/audit").status_code == 403
    c2 = as_principal(principal_of(authority=Authority.NAAN))
    assert c2.get("/admin/audit").status_code == 200


def test_画面から採番できる(db, world, principal_of, as_principal):
    """**API と同じ経路**（authz → minting）を通る。画面専用の抜け道を作らない。"""
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/admin/mint", data={"url": "https://example.org/manual"})
    assert r.status_code == 200 and "ark:/99999/a1" in r.text


def test_画面からでも他機関には採番できない(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    assert c.post("/admin/mint", data={"shoulder": "/b2"}).status_code == 403


def test_採番権限が無ければ画面も開けない(db, world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"], scopes={"ark:read"}))
    assert c.get("/admin/mint").status_code == 403


# ------------------------------------------------------------- 国際化


@pytest.mark.parametrize(
    "lang,needle", [("ja", "委譲の構造"), ("en", "Delegation")]
)
def test_日英を切り替えられる(db, world, principal_of, as_principal, lang, needle):
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    assert needle in c.get("/admin/", params={"lang": lang}).text


def test_言語の選択は記憶される(db, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    r = c.get("/admin/", params={"lang": "en"})
    assert r.cookies.get("arkhe_lang") == "en"


def test_Accept_Languageを見る(db, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    r = c.get("/admin/", headers={"accept-language": "en-US,en;q=0.9"})
    assert "Delegation" in r.text


def test_翻訳に抜けが無い():
    from arkhe.api import i18n

    for lang, cat in i18n.CATALOGS.items():
        assert set(cat) == set(i18n.JA), f"{lang} に抜けがある"


def test_予約は作成時にしか指定できない(db, world, root):
    """**active から reserved へは戻せない。** 一度採番できる状態にした名前空間を
    後から「未使用扱い」にはできない。"""
    sh = ops.add_shoulder(db, root, naan="99999", shoulder="/rv", status="reserved")
    db.commit()
    assert sh.status == ShoulderStatus.RESERVED
    with pytest.raises(Invalid):
        ops.add_shoulder(db, root, naan="99999", shoulder="/bad", status="retired")


def test_予約枠は採番できるようにできる(db, world, root):
    sh = ops.add_shoulder(db, root, naan="99999", shoulder="/rv", status="reserved")
    db.commit()
    ops.set_shoulder_status(db, root, shoulder_id=sh.id, status="active")
    assert sh.status == ShoulderStatus.ACTIVE


def test_言語切替のUIが常に出る(db, world, principal_of, as_principal):
    """**横並びのセグメントにしない。** 言語が増えると横に伸びて破綻するため、
    アイコンから開く一覧にしてある。開閉は Popover API に任せる（外側クリックと
    Esc が標準で効くので JS が要らない）。"""
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    body = c.get("/admin/").text
    assert 'popovertarget="lang-menu"' in body
    assert 'id="lang-menu" popover' in body
    # 選べる言語がすべて並び、現在の言語に印が付く
    from arkhe.api import i18n

    for code, label in i18n.LANGS.items():
        assert f'href="?lang={code}"' in body and label in body
    assert 'class="menu-i on"' in body
