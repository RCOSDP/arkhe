"""管理画面から台帳を組む操作。

**画面の出し分けと実際の認可が同じ判定であること**を見る。別々になっていると
「ボタンは出ないが POST は通る」穴ができる——ここで確かめたいのはそれ。
"""

from __future__ import annotations

import pytest

from arkhe.db.models import Authority, Client, Manager, Naan, Shoulder
from arkhe.domain import admin_ops as ops

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


# ------------------------------------------------------ 利用者と鍵の発行


def test_画面から鍵を発行できる(db, world, root, principal_of, as_principal):
    """**平文はこの応答にしか載らない。** 保存しているのはハッシュだけ。"""
    c = ops.register_client(db, root, client_id="repo", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    r = cli.post(f"/admin/client/{c.id}/key", data={"kind": "api_key"})
    assert r.status_code == 200
    db.expire_all()
    cred = db.get(Client, c.id).credentials[0]
    assert cred.active and cred.prefix in r.text
    # **平文は保存していない。** 画面に出たものが DB に無いことを確かめる。
    secret = r.text.split('class="secret">')[1].split("<")[0].strip()
    assert secret and secret not in cred.hashed


def test_再読み込みでは鍵は出てこない(db, world, root, principal_of, as_principal):
    """発行のたびに一度きり。リダイレクトで戻すと消える、を型で示す。"""
    c = ops.register_client(db, root, client_id="repo2", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    cli.post(f"/admin/client/{c.id}/key", data={"kind": "api_key"})
    assert 'class="secret"' not in cli.get(f"/admin/client/{c.id}").text


def test_人には鍵を発行しない(db, world, root, principal_of, as_principal):
    """**人に鍵を配ると、その人が組織を離れても鍵が生き残る。**"""
    c = ops.register_client(db, root, client_id="alice@example.ac.jp", naan="99999",
                            manager_id=world["a"].id, subject_type="person")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    assert cli.post(f"/admin/client/{c.id}/key", data={"kind": "api_key"}).status_code == 400
    # 画面にも発行の口を出さない
    assert "/key" not in cli.get(f"/admin/client/{c.id}").text


def test_他組織の利用者の鍵は発行できない(db, world, root, principal_of, as_principal):
    c = ops.register_client(db, root, client_id="other", naan="99999",
                            manager_id=world["b"].id, scopes="ark:mint")
    db.commit()
    cli = as_principal(principal_of(manager=world["a"]))
    assert cli.get(f"/admin/client/{c.id}").status_code == 403
    assert cli.post(f"/admin/client/{c.id}/key", data={"kind": "api_key"}).status_code == 403


def test_失効させても行は残る(db, world, root, principal_of, as_principal):
    """**いつ失効したかを残す。** 誰の鍵だったかが辿れなくなってはいけない。"""
    from arkhe.db.models import Credential

    c = ops.register_client(db, root, client_id="rot", naan="99999",
                            manager_id=world["a"].id, scopes="ark:mint")
    issued = ops.issue_credential(db, root, client_pk=c.id)
    db.commit()
    cid = issued.credential.id
    cli = as_principal(principal_of(manager=world["a"]))
    r = cli.post(f"/admin/client/{c.id}/revoke", data={"credential_id": cid})
    assert r.status_code == 303
    db.expire_all()
    cred = db.get(Credential, cid)
    assert cred is not None and not cred.active and cred.expires_at is not None


def test_組織管理者は自組織の利用者を登録できる(db, world, principal_of, as_principal):
    """画面の判定を `admin_ops` より厳しくしない（出せるはずのものが出せなくなる）。"""
    cli = as_principal(principal_of(manager=world["a"]))
    r = cli.post("/admin/client/new", data={
        "client_id": "own-repo", "scopes": "ark:mint", "person": "",
    })
    assert r.status_code == 303
    made = db.scalar(db.query(Client).filter_by(client_id="own-repo").statement)
    assert made.manager_id == world["a"].id


def test_組織管理者は他組織を選べない(db, world, principal_of, as_principal):
    """選択肢を出していない値が送られてきても、自組織に落とす。"""
    cli = as_principal(principal_of(manager=world["a"]))
    r = cli.post("/admin/client/new", data={
        "client_id": "sneaky", "manager_id": str(world["b"].id), "scopes": "ark:mint",
    })
    assert r.status_code == 303
    made = db.scalar(db.query(Client).filter_by(client_id="sneaky").statement)
    assert made.manager_id == world["a"].id


# ------------------------------------------- 押せないものは出さない


def test_組織管理者に監査ログを見せない(world, principal_of, as_principal):
    """**押しても断られるだけの導線は出さない。**

    監査ログは NAAN 単位以上にしか見せないので、組織単位の管理者には
    リンクごと出さない（出すと、押して 403 を見るまで分からない）。
    """
    c = as_principal(principal_of(manager=world["a"]))
    home = c.get("/admin/").text
    assert "/admin/audit" not in home
    assert c.get("/admin/audit").status_code == 403   # 直接叩けば当然断る


def test_NAAN管理者には監査ログを見せる(world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.NAAN))
    assert "/admin/audit" in c.get("/admin/").text
    assert c.get("/admin/audit").status_code == 200


def test_採番できない主体には採番の導線を出さない(world, principal_of, as_principal):
    """scope で決まる。**出し分けとルートの判定は同じもの。**"""
    c = as_principal(principal_of(manager=world["a"], scopes=["ark:read"]))
    assert "/admin/mint" not in c.get("/admin/").text
    assert c.get("/admin/mint").status_code == 403


def test_採番できる主体には出す(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"], scopes=["ark:mint"]))
    assert "/admin/mint" in c.get("/admin/").text
    assert c.get("/admin/mint").status_code == 200


def test_所属の無い主体には利用者の登録を出さない(world, principal_of, as_principal):
    """自組織が無ければ誰の利用者も作れない。"""
    c = as_principal(principal_of(manager=None))
    assert "/admin/client/new" not in c.get("/admin/clients").text
    assert c.get("/admin/client/new").status_code == 403


def test_組織管理者には利用者の登録を出す(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    assert "/admin/client/new" in c.get("/admin/clients").text
    assert c.get("/admin/client/new").status_code == 200


def test_出ている導線は全て開ける(world, principal_of, as_principal):
    """**出し分けと認可がずれていないこと**の総当たり確認。

    画面に出ているリンクを片端から開き、1 つでも断られたら出し分けが間違っている。
    """
    import re

    for p in (principal_of(authority=Authority.SYSTEM),
              principal_of(authority=Authority.NAAN),
              principal_of(manager=world["a"])):
        c = as_principal(p)
        seen, todo = set(), ["/admin/", "/admin/clients"]
        while todo:
            path = todo.pop()
            if path in seen:
                continue
            seen.add(path)
            r = c.get(path)
            assert r.status_code == 200, f"{p.authority} に出ている {path} が {r.status_code}"
            for href in re.findall(r'href="(/admin/[^"?#]*)"', r.text):
                if href not in seen and not href.endswith(("logout", "login")):
                    todo.append(href)
