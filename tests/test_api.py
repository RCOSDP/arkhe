"""HTTP の口。**認証だけ差し替え、認可は本物を通す。**"""

from __future__ import annotations

import pytest

from arkhe.db.models import Authority


def test_採番して解決できる(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/api/mint", json={"url": "https://example.org/1", "title": "A"})
    assert r.status_code == 201
    key = r.json()["ark"].removeprefix("ark:/")
    assert c.get(f"/ark:/{key}").headers["location"] == "https://example.org/1"


def test_F4_同じrequest_idの再送は採番しない(world, principal_of, as_principal):
    """**応答が失われただけのときに番号を増やさない。** ARK は再割当てしないので、
    死んだ番号が増えるのは取り返しがつかない。"""
    c = as_principal(principal_of(manager=world["a"]))
    a = c.post("/api/mint", json={"request_id": "job-1"})
    b = c.post("/api/mint", json={"request_id": "job-1"})
    assert (a.status_code, b.status_code) == (201, 200)
    assert a.json()["ark"] == b.json()["ark"]


def test_F4_request_idは主体ごとに独立(world, principal_of, as_principal):
    """他組織の request_id と衝突しないし、鍵の推測で他組織の ARK を引けない。"""
    a = as_principal(principal_of(manager=world["a"], client_id="a")).post(
        "/api/mint", json={"request_id": "same"}
    )
    b = as_principal(principal_of(manager=world["b"], client_id="b")).post(
        "/api/mint", json={"request_id": "same"}
    )
    assert a.json()["ark"] != b.json()["ark"]


def test_一括採番は入力の順序で返す(world, principal_of, as_principal):
    """再送ぶんと新規ぶんが混ざるので、呼び出し側が突き合わせられるように並びを保つ。"""
    c = as_principal(principal_of(manager=world["a"]))
    c.post("/api/mint", json={"request_id": "r2"})
    r = c.post(
        "/api/mint/bulk",
        json={"data": [{"request_id": "r1"}, {"request_id": "r2"}, {"request_id": "r3"}]},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["created"] == 2 and body["replayed"] == 1
    assert len(body["minted"]) == 3


def test_一括採番は一件でも範囲外なら何も作らない(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/api/mint/bulk", json={"data": [{}, {"shoulder": "/b2"}]})
    assert r.status_code == 403


def test_M4_他組織のARKは読めない(db, world, principal_of, as_principal):
    from arkhe.domain import minting

    theirs, _ = minting.mint(db, shoulder=world["sh_b"], created_by="b")
    db.commit()
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/api/query", json={"data": [f"ark:/{theirs.ark}"]})
    assert r.json()["data"] == []


def test_tombstone_は削除ではない(world, principal_of, as_principal):
    """**識別子とメタデータは残る。** 消せるのは対象への到達性だけ。"""
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://x/1", "title": "T"}).json()["ark"]
    r = c.put("/api/tombstone", json={"ark": key, "commitment": "対象は失われた"})
    assert r.status_code == 200 and r.json()["url"] == ""
    assert r.json()["title"] == "T"  # メタデータは残る
    # D6: 転送先が無いので、裸の suffix に飛ばさず記述を返す
    assert c.get(f"/{key}").status_code == 200


def test_tombstoneはupdateとscopeが別(world, principal_of, as_principal):
    """墓碑化は「どこにあるか」ではなく「もう無い」という宣言。投入バッチのような
    日常の書き手には渡さない。"""
    c = as_principal(principal_of(manager=world["a"], scopes={"ark:mint", "ark:update"}))
    key = c.post("/api/mint", json={}).json()["ark"]
    assert c.put("/api/tombstone", json={"ark": key}).status_code == 403


def test_委譲されたshoulderへの採番は307で案内する(db, world, root, principal_of, as_principal):
    """**プロキシしない。** 代理で呼ぶと、応答が失われたとき「向こうでは採番された
    がこちらは知らない ARK」が生まれる。"""
    from arkhe.domain import admin_ops as ops

    ops.set_shoulder_status(
        db, root, shoulder_id=world["sh_a"].id, status="delegated",
        minter="https://mint.example.org",
    )
    db.commit()
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/api/mint", json={})
    assert r.status_code == 307
    assert r.headers["location"] == "https://mint.example.org"


def test_ark表記のゆれを吸収する(world, principal_of, as_principal):
    """`ark:/x` でも `x` でも受け、解決側と同じ正規化を通す。

    **ハイフンが無視できるのは name 部だけ。** NAAN は文字列そのもの（N2）なので、
    `9999-9` は別の NAAN であり 400 になるのが正しい。
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"].removeprefix("ark:/")
    naan, name = key.split("/", 1)
    hyphenated = f"{naan}/{name[:3]}-{name[3:]}"  # name 部に入れる
    for form in (f"ark:/{key}", key, hyphenated):
        assert c.put(
            "/api/update", json={"ark": form, "url": "https://x/2"}
        ).status_code == 200, form
    # NAAN にハイフンを入れたものは別の NAAN。**受け付けてはいけない。**
    bad = c.put("/api/update", json={"ark": f"{naan[:4]}-{naan[4:]}/{name}", "url": "x"})
    assert bad.status_code in (400, 404)


def test_well_known_ark(world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    r = c.get("/.well-known/ark")
    assert r.status_code == 200
    assert {n["naan"] for n in r.json()["naans"]} == {"99999", "88888"}


@pytest.mark.parametrize("resolver", [False, True], ids=["minter", "resolver"])
def test_healthzはどのモードでも応える(factory, resolver):
    """**probe の口はモードによらず要る。**

    以前は resolve ルータにしか載っておらず、minter と admin は liveness probe に
    404 を返し続けて kubelet に殺されていた。
    """
    from fastapi.testclient import TestClient

    from arkhe.app import create_app
    from arkhe.settings import Settings

    app = create_app(
        Settings(
            resolver=resolver, database_url="sqlite://", auth=["apikey"],
            admin_login="bearer",
        )
    )
    assert TestClient(app).get("/healthz").json() == {"ok": True}
