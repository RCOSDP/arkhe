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
    # url は正しい値にする——ここで見たいのは **NAAN の綴り**であって、
    # 転送先の検証ではない。
    bad = c.put(
        "/api/update",
        json={"ark": f"{naan[:4]}-{naan[4:]}/{name}", "url": "https://x/3"},
    )
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


def test_公開ページに保護ヘッダが付く(world, principal_of, as_principal):
    """**転送先の検証が破れても、スクリプトは実行させない。**

    `?info` は認証を要さない公開ページで、載る文字列を決めるのは採番した側。
    多層で守る。
    """
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/api/mint", json={"url": "https://example.org/1", "title": "x"})
    key = r.json()["ark"].removeprefix("ark:/")
    # **200 を返す経路で見る。** 404 でもヘッダは付くので、それでは
    # 「公開ページに付いている」ことの確認にならない。
    info = c.get(f"/ark:/{key}?info")
    assert info.status_code == 200
    h = info.headers
    assert "script-src 'none'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff"
    # **API ドキュメントだけは緩める。** Swagger UI は CDN から script を読むので、
    # 素の CSP を当てると真っ白になる（読み込み先は限る）。
    docs = c.get("/api/docs").headers["content-security-policy"]
    assert "script-src 'none'" not in docs
    assert "cdn.jsdelivr.net" in docs


# ------------------------------------------- 行き先が変わった記録


def test_付け替えは組織が行っても残る(db, world, principal_of, as_principal):
    """**監査は NAAN 単位以上しか残さない。**

    採番も付け替えも組織が行うので、監査だけでは肝心の変更が落ちる。
    """
    from arkhe.db.models import ArkChange

    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://before.example/1"}).json()["ark"]
    c.put("/api/update", json={"ark": key, "url": "https://after.example/2"})

    rows = db.scalars(db.query(ArkChange).statement).all()
    assert len(rows) == 1
    assert rows[0].before_url == "https://before.example/1"
    assert rows[0].after_url == "https://after.example/2"
    assert rows[0].action == "update"


def test_行き先が変わらなければ残さない(db, world, principal_of, as_principal):
    """題名だけ直したときにまで履歴を積まない（読めなくなる）。"""
    from arkhe.db.models import ArkChange

    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://same.example/1"}).json()["ark"]
    c.put("/api/update", json={"ark": key, "url": "https://same.example/1", "title": "改題"})
    assert db.scalars(db.query(ArkChange).statement).all() == []


def test_墓碑化も残る(db, world, principal_of, as_principal):
    """**転送先の付け替えとは意味が違う**ので、action で区別して残す。"""
    from arkhe.db.models import ArkChange

    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://gone.example/1"}).json()["ark"]
    c.put("/api/tombstone", json={"ark": key, "commitment": "取り下げ"})
    rows = db.scalars(db.query(ArkChange).statement).all()
    assert [r.action for r in rows] == ["tombstone"]
    assert rows[0].before_url == "https://gone.example/1"


def test_一括の付け替えも一件ずつ残る(db, world, principal_of, as_principal):
    from arkhe.db.models import ArkChange

    c = as_principal(principal_of(manager=world["a"]))
    keys = [c.post("/api/mint", json={"url": f"https://b.example/{i}"}).json()["ark"]
            for i in range(3)]
    c.put("/api/update/bulk",
          json={"data": [{"ark": k, "url": f"https://a.example/{i}"}
                         for i, k in enumerate(keys)]})
    assert len(db.scalars(db.query(ArkChange).statement).all()) == 3


def test_誰が変えたかが残る(db, world, principal_of, as_principal):
    from arkhe.db.models import ArkChange

    c = as_principal(principal_of(manager=world["a"], client_id="repo-1"))
    key = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"]
    c.put("/api/update", json={"ark": key, "url": "https://x/2"})
    assert db.scalars(db.query(ArkChange).statement).all()[0].by == "repo-1"


def test_開けない行き先は転送せず記述を返す(world, principal_of, as_principal):
    """**登録できることと、ブラウザを送ってよいことは別。**

    `urn:` は正当な行き先だがブラウザは開けない。302 で渡すと、利用者には
    「壊れたリンク」に見える——記述を返すほうが答えになっている。
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post(
        "/api/mint", json={"url": "urn:isbn:0451450523", "title": "紙の本"}
    ).json()["ark"].removeprefix("ark:/")
    r = c.get(f"/ark:/{key}")
    assert r.status_code == 200                     # 302 ではない
    assert "urn:isbn:0451450523" in r.text          # 行き先は見せる
    assert '<a href="urn:' not in r.text            # ただしリンクにはしない


def test_開ける行き先は転送する(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post(
        "/api/mint", json={"url": "https://ok.example/1"}
    ).json()["ark"].removeprefix("ark:/")
    r = c.get(f"/ark:/{key}")
    assert r.status_code == 302 and r.headers["location"] == "https://ok.example/1"


@pytest.mark.parametrize("resolver", [False, True], ids=["minter", "resolver"])
def test_内部のつまみがクエリに漏れない(resolver):
    """**FastAPI は依存の引数をクエリパラメータとして公開する。**

    `get_session(*, read_only=…)` を依存に置いていたころ、`?read_only=true` が
    **全パスに生えていた**——`POST /api/mint?read_only=true` で、採番の書き込みを
    外からレプリカへ向けられる。接続先を決めるのは役割であって、要求ではない。
    """
    from arkhe.app import create_app
    from arkhe.settings import Settings

    spec = create_app(
        Settings(
            resolver=resolver, database_url="sqlite://", auth=["apikey"],
            admin_login="bearer",
        )
    ).openapi()

    leaked = [
        f"{method.upper()} {path} ?{q['name']}"
        for path, ops in spec["paths"].items()
        for method, op in ops.items()
        for q in op.get("parameters", [])
        if q.get("in") == "query" and q["name"] == "read_only"
    ]
    assert not leaked, leaked


def test_解決は読み取り側の接続を使う(monkeypatch):
    """**`ARKHE_READ_DATABASE_URL` を効かせる。** 設定を読むだけで誰も使っていな
    かったので、resolver は書き込みエンジンから読んでいた——レプリカを立てても
    向かない。参照リファレンスに載っている以上、設定は効かなければならない。
    """
    from arkhe.db import session as session_mod
    from arkhe.settings import Settings

    cfg = Settings(
        resolver=True,
        database_url="sqlite:///primary.sqlite3",
        read_database_url="sqlite:///replica.sqlite3",
    )
    monkeypatch.setattr(session_mod, "get_settings", lambda: cfg)
    write, read = session_mod.engines(cfg)
    assert write is not read  # 前提が崩れていたら以下は何も確かめていない

    gen = session_mod.get_session()
    try:
        assert next(gen).get_bind() is read
    finally:
        gen.close()


def _spec(**over):
    from arkhe.app import create_app
    from arkhe.settings import Settings

    base = dict(database_url="sqlite://", admin_login="bearer", token_secret="x" * 48)
    return create_app(Settings(**(base | over))).openapi()


def test_トークンの取り方が仕様書に載る():
    """**「どこで取るか」を機械可読で言う。** URL は README にしかなく、OpenAPI
    からクライアントを起こすと認証の取得手順が落ちていた。

    広告した URL が実在することまで見る——prefix を変えたときに、仕様書だけが
    古い場所を指し続けるのを防ぐ。
    """
    from arkhe.domain import authz

    spec = _spec(auth=["apikey", "oauth2"])
    flow = spec["components"]["securitySchemes"]["oauth2"]["flows"]["clientCredentials"]

    assert flow["tokenUrl"] in spec["paths"]              # 実在する口を指している
    assert set(flow["scopes"]) == set(authz.SCOPES)       # 語彙は 1 か所から
    assert "security" not in spec["paths"][flow["tokenUrl"]]["post"]  # 取る口自体は素通し

    # **bearer と並ぶ**（どちらでもよい）。片方に寄せると、apikey での利用が
    # 仕様書の上では通らないことになる。
    assert {"oauth2": []} in spec["paths"]["/api/mint"]["post"]["security"]
    assert {"bearer": []} in spec["paths"]["/api/mint"]["post"]["security"]


@pytest.mark.parametrize(
    "over", [{"auth": ["apikey"]}, {"resolver": True, "auth": ["apikey"]}],
    ids=["minter-apikey", "resolver"],
)
def test_口の無い構成では取り方を広告しない(over):
    """**無い口を指さない。** 広告だけ残ると、生成したクライアントが 404 を踏む。"""
    spec = _spec(**over)
    assert "oauth2" not in spec.get("components", {}).get("securitySchemes", {})
    assert "/oauth/token" not in spec["paths"]
