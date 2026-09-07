"""HTTP の口。**認証だけ差し替え、認可は本物を通す。**"""

from __future__ import annotations

import pytest

from arkhe.auth.deps import Db
from arkhe.db.models import Authority


def test_採番して解決できる(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/api/mint", json={"url": "https://example.org/1", "title": "A"})
    assert r.status_code == 201
    key = r.json()["ark"].removeprefix("ark:")
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


def test_F4_同じrequest_idが一塊のなかで重複しても壊れない(world, principal_of, as_principal):
    """**控えは (client, request_id) で一意。** 同じ `request_id` が 1 回の要求に
    2 行あると、控えを 2 度書こうとして IntegrityError になり 500 で落ちていた。

    同じ `request_id` は「同じ 1 つの依頼」という意味なので、**1 件だけ採番して
    両方の行に同じ ARK を返す**——再送の扱いと同じ約束を、塊の内側にも通す。
    """
    c = as_principal(principal_of(manager=world["a"]))
    r = c.post("/api/mint/bulk", json={"data": [
        {"request_id": "same", "url": "https://example.org/1"},
        {"request_id": "same", "url": "https://example.org/2"},
        {"url": "https://example.org/3"},
    ]})
    assert r.status_code == 201
    body = r.json()
    assert body["minted"][0]["ark"] == body["minted"][1]["ark"]   # 同じ番号
    assert body["minted"][2]["ark"] != body["minted"][0]["ark"]   # 無印は独立
    assert (body["created"], body["replayed"]) == (2, 1)


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
    key = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"].removeprefix("ark:")
    naan, name = key.split("/", 1)
    hyphenated = f"{naan}/{name[:3]}-{name[3:]}"  # name 部に入れる
    # §2.2: 新旧どちらのラベルも**永久に**受ける。生成が新形式になっても受理は減らさない。
    for form in (f"ark:{key}", f"ark:/{key}", key, hyphenated):
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


def test_F1_仕様が要求する長さのNAANで採番して解決できる(db, root, principal_of, as_principal):
    """§2.3「受け取る実装は NAAN 16 オクテットまで対応しなければならない」。

    **10 で弾いていたのは arklet の `int()` を守るための定数**で、N2（NAAN を
    整数化しない）を決めた時点で理由は消えていた。**端から端まで通ることを見る**
    ——解析だけ通っても、列が狭ければ採番で落ちる。
    """
    from arkhe.domain import admin_ops as ops

    long_naan = "bcdfghjkmnpqrstv"  # 16 オクテットの betanumeric
    assert len(long_naan) == 16
    ops.create_naan(db, root, naan=long_naan, name="長い NAAN の RA")
    db.flush()
    manager, _ = ops.onboard_manager(db, root, naan=long_naan, name="D組織", shoulder="/d4")
    db.commit()

    c = as_principal(principal_of(naan=long_naan, manager=manager))
    r = c.post("/api/mint", json={"url": "https://long.example.org/1"})
    assert r.status_code == 201
    key = r.json()["ark"].removeprefix("ark:")
    assert key.startswith(f"{long_naan}/")
    assert c.get(f"/ark:/{key}").headers["location"] == "https://long.example.org/1"


def test_F1_名前は仕様の下限まで受け_超えたら理由を返す(world, principal_of, as_principal):
    """§3.1「Base Name ＋ Qualifier は 255 オクテットまで対応しなければならない」。

    **超えたぶんは DB のエラーで落とさない。** 索引できないという我々の事情なので、
    そう言って 400 を返す（仕様も「長い文字列を作る側は、受け取る実装が索引でき
    ないかもしれないと理解すべき」と書いている）。
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"]
    base = key.removeprefix("ark:").split("/", 1)[1]

    fits = "/" + "z" * (255 - len(base) - 1)      # base + 修飾子でちょうど 255
    r = c.post("/api/register", json={"ark": key, "qualifier": fits, "url": "https://x/2"})
    assert r.status_code == 201
    assert len(r.json()["ark"].removeprefix("ark:").split("/", 1)[1]) == 255

    over = fits + "z"                              # 1 オクテット超える
    bad = c.post("/api/register", json={"ark": key, "qualifier": over, "url": "https://x/3"})
    assert bad.status_code == 400
    assert bad.json()["code"] == "ARKHE-1004"
    assert bad.json()["detail"] == {"length": 256, "limit": 255}


def _delegate(db, root, shoulder):
    """shoulder を委譲状態にする（取り込みの前提）。"""
    from arkhe.domain import admin_ops as ops

    ops.set_shoulder_status(
        db, root, shoulder_id=shoulder.id, status="delegated",
        minter="https://closed.example/api",
    )
    db.commit()


def _valid_name(naan: str, stem: str) -> str:
    """検査桁の正しい名前を組む（外の minter が採ったつもりの名前）。"""
    from arkhe.arkspec.betanumeric import check_digit_base, noid_check_digit

    return stem + noid_check_digit(check_digit_base(naan, stem))


def test_取り込みは委譲した名前空間にしか入らない(db, world, root, principal_of, as_principal):
    """**閉じた側で採番した名前を、あとから公開側に出すための口**（C-2 → C-1）。

    採番と分けてあるのは、**名前を呼び出し側が選ぶ**から——`mint` が構造で守って
    いた「衝突しない」「検査桁が正しい」「自分の名前空間の内側」が、全部検査に移る。
    """
    _delegate(db, root, world["sh_a"])
    c = as_principal(principal_of(manager=world["a"], scopes={"ark:import"}))
    name = _valid_name("99999", "a1closed01")

    r = c.post("/api/import", json={
        "ark": f"ark:99999/{name}", "title": "閉域で採番したもの",
        "url": "https://repo.example/records/9",
    })
    assert r.status_code == 201 and r.json()["ark"] == f"ark:99999/{name}"

    # **二度は入らない。** 採番と同じで、既に在るものを黙って上書きしない（E1）。
    again = c.post("/api/import", json={"ark": f"ark:99999/{name}"})
    assert again.status_code == 400 and again.json()["code"] == "ARKHE-1005"

    # 検査桁が合わなければ入らない——**外から来た名前を信じる唯一の手立て**。
    bad = c.post("/api/import", json={"ark": f"ark:99999/{name[:-1]}z"})
    assert bad.status_code == 400 and bad.json()["code"] == "ARKHE-1012"

    # 委譲していない shoulder には入らない（自分の採番と衝突しうる）。
    other = _valid_name("99999", "b2closed01")
    r2 = c.post("/api/import", json={"ark": f"ark:99999/{other}"})
    assert r2.status_code in (400, 403)


def test_取り込みの範囲は上位が下位を覆う(db, world, root, principal_of, as_principal):
    """**上位の権威は下位を覆い、下位は上位に届かない。** 採番の到達範囲と同じ判定。"""
    _delegate(db, root, world["sh_a"])
    _delegate(db, root, world["sh_b"])
    n_a = _valid_name("99999", "a1reach001")
    n_b = _valid_name("99999", "b2reach001")

    # 組織 A の主体は、B の shoulder には届かない。
    a = as_principal(principal_of(manager=world["a"], scopes={"ark:import"}))
    assert a.post("/api/import", json={"ark": f"ark:99999/{n_b}"}).status_code == 403
    assert a.post("/api/import", json={"ark": f"ark:99999/{n_a}"}).status_code == 201

    # NAAN 単位の主体は、その NAAN の下ならどの shoulder にも届く（上位が下位を覆う）。
    naan_wide = as_principal(
        principal_of(authority=Authority.NAAN, naan="99999", scopes={"ark:import"})
    )
    assert naan_wide.post("/api/import", json={"ark": f"ark:99999/{n_b}"}).status_code == 201

    # 他 NAAN には届かない。
    n_c = _valid_name("88888", "c3reach001")
    assert naan_wide.post("/api/import", json={"ark": f"ark:88888/{n_c}"}).status_code == 403


def test_取り込みは権威を持たないNAANには入らない(db, world, root, principal_of, as_principal):
    """**取り次いでいるだけの NAAN の保管者を名乗らない。** 主体の到達範囲とは別の話。"""
    from arkhe.db.models import Naan

    # 権威を持たない（取り次ぐだけの）NAAN にする
    naan = db.get(Naan, "88888")
    naan.is_authoritative = False
    naan.redirect = "https://elsewhere.example"
    db.commit()
    _delegate(db, root, world["sh_c"])
    sysadmin = as_principal(
        principal_of(authority=Authority.SYSTEM, naan="", scopes={"ark:import"})
    )
    name = _valid_name("88888", "c3notours1")
    r = sysadmin.post("/api/import", json={"ark": f"ark:88888/{name}"})
    assert r.status_code == 403 and r.json()["code"] == "ARKHE-1308"


def test_一括の取り込みは一件でも落ちれば何も作らない(db, world, root, principal_of, as_principal):
    """**中途半端に入った名前は引っ込められない。** 部分適用は採番より重い事故になる。"""
    _delegate(db, root, world["sh_a"])
    c = as_principal(principal_of(manager=world["a"], scopes={"ark:import", "ark:read"}))
    ok1 = _valid_name("99999", "a1bulk0001")
    ok2 = _valid_name("99999", "a1bulk0002")

    bad = c.post("/api/import/bulk", json={"data": [
        {"ark": f"ark:99999/{ok1}"},
        {"ark": f"ark:99999/{ok2[:-1]}z"},   # 検査桁が壊れている
    ]})
    assert bad.status_code == 400
    assert c.post("/api/query", json={"data": [f"ark:99999/{ok1}"]}).json()["data"] == []

    good = c.post("/api/import/bulk", json={"data": [
        {"ark": f"ark:99999/{ok1}", "title": "1"},
        {"ark": f"ark:99999/{ok2}", "title": "2"},
    ]})
    assert good.status_code == 201 and good.json()["count"] == 2


def test_取り込んだARKは同じ名前のまま公開できる(db, world, root, principal_of, as_principal):
    """**これが口を足した理由。** 閉じた期間に配った名前が、そのまま公開に使える。"""
    _delegate(db, root, world["sh_a"])
    c = as_principal(principal_of(manager=world["a"], scopes={"ark:import", "ark:update"}))
    name = _valid_name("99999", "a1embargo1")

    # 記述だけ（行き先なし）で取り込む＝「存在は言えるが、対象には行けない」
    c.post("/api/import", json={"ark": f"ark:99999/{name}", "title": "禁輸中"})
    assert c.get(f"/ark:99999/{name}", follow_redirects=False).status_code == 200

    # 禁輸が明けたら url を入れるだけ。**識別子は変わらない。**
    c.patch("/api/update", json={
        "ark": f"ark:99999/{name}", "url": "https://repo.example/records/9",
    })
    moved = c.get(f"/ark:99999/{name}", follow_redirects=False)
    assert moved.status_code == 302
    assert moved.headers["location"] == "https://repo.example/records/9"


def test_PATCHは送った項目だけ書き換える(world, principal_of, as_principal):
    """**`PUT` は置き換え、`PATCH` は差分。** 実際に多いのは「行き先だけ動かす」で、
    そこで `PUT` を使うと記述が既定値で消える。
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={
        "url": "https://one.example/1", "title": "題", "who": "山田", "when": "2026",
    }).json()["ark"]

    moved = c.patch("/api/update", json={"ark": key, "url": "https://two.example/2"}).json()
    assert moved["url"] == "https://two.example/2"
    assert (moved["title"], moved["who"], moved["when"]) == ("題", "山田", "2026")

    # **空文字は「消す」。** 送らないことと区別できないと、値を消す手段が無くなる。
    cleared = c.patch("/api/update", json={"ark": key, "title": ""}).json()
    assert cleared["title"] == "" and cleared["who"] == "山田"

    # `PUT` は今までどおり置き換える（挙動を変えていない）。
    replaced = c.put("/api/update", json={"ark": key, "url": "https://three.example/3"}).json()
    assert replaced["who"] == "" and replaced["url"] == "https://three.example/3"

    # 権限も範囲も `PUT` と同じ経路を通る。
    thin = as_principal(principal_of(manager=world["a"], scopes={"ark:read"}))
    assert thin.patch("/api/update", json={"ark": key, "url": "https://x/9"}).status_code == 403


def test_infoは媒体で出し分ける(world, principal_of, as_principal):
    """§5.2「応答の形は**返す content type が示す**」。中身はどれも同じ
    「記述＋永続性宣言」で、違うのは媒体だけ。

    `?json` は残す——**その JSON を名指しする別名**であって、別の内容ではない。
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={
        "url": "https://x/1", "title": "題", "who": "山田", "when": "2026",
    }).json()["ark"].removeprefix("ark:")

    html = c.get(f"/ark:{key}?info")
    assert html.headers["content-type"].startswith("text/html")

    js = c.get(f"/ark:{key}?info", headers={"Accept": "application/json"})
    assert js.headers["content-type"].startswith("application/json")
    assert js.json()["where"] == f"ark:{key}"
    # **`?json` と同じもの**が返る。
    assert js.json() == c.get(f"/ark:{key}?json").json()

    anvl = c.get(f"/ark:{key}?info", headers={"Accept": "text/plain"})
    assert anvl.headers["content-type"].startswith("text/plain")
    assert anvl.text == c.get(f"/ark:{key}??").text   # `??` と同じ「記述＋宣言」

    # どれにも THUMP のヘッダが付き、`Vary` で表現が分かれることを言う。
    for r in (html, js):
        assert r.headers["thump-status"] == "0.6 200 OK"
        assert "Accept" in r.headers["vary"]


def test_infoは画面の言語で答える(world, principal_of, as_principal):
    """**`?info` は公開の口。** ARK は世界中から引かれるので、日本語しか話さないと
    「識別子は届いたのに説明が読めない」で落ちる。

    `?lang=` は使えない——クエリ文字列そのものが inflection だから。`?info&lang=en`。
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"].removeprefix("ark:")

    ja = c.get(f"/ark:{key}?info")
    en = c.get(f"/ark:{key}?info&lang=en")
    assert "永続性について" in ja.text and 'lang="ja"' in ja.text
    assert "On persistence" in en.text and 'lang="en"' in en.text

    # Accept-Language でも切り替わる。
    hdr = c.get(f"/ark:{key}?info", headers={"Accept-Language": "en-GB,en;q=0.9"})
    assert "On persistence" in hdr.text

    # 永続性の水準の表示名も catalogue から来る（`?json` にも出る）。
    js = c.get(f"/ark:{key}?info&lang=en", headers={"Accept": "application/json"}).json()
    assert js["commitment_label"] == "permanent; the content may be revised"


def test_A5_生成は新形式_受理は旧形式も永久に(world, principal_of, as_principal):
    """§2.2: 「新形式 `ark:` と旧形式 `ark:/` は**どちらも永久に**認識しなければ
    ならない。実装は**新しい ARK を新形式で生成すべき**」。

    **受理と生成で非対称**にする。受けるほうを狭めると既存の参照が死ぬが、
    出すほうを旧形式のままにすると、我々が配った文字列がそのまま次の実装の
    入力になって**旧形式が減らない**。
    """
    c = as_principal(principal_of(manager=world["a"]))
    ark = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"]
    assert ark.startswith("ark:") and not ark.startswith("ark:/")
    key = ark.removeprefix("ark:")

    # **出す口はすべて新形式。** 1 か所でも旧形式が残ると、そこから漏れ続ける。
    assert c.get(f"/ark:{key}?json").json()["ark"] == f"ark:{key}"
    assert f"ark:{key}" in c.get(f"/ark:{key}??").text
    missing = c.get(f"/ark:{key}zz-not-registered")
    assert missing.status_code == 404 and "ark:/" not in missing.text

    # **受けるほうは減らさない。** 旧形式でも大文字ラベルでも同じ ARK に当たる。
    for path in (f"/ark:{key}", f"/ark:/{key}", f"/ARK:/{key}", f"/Ark:{key}"):
        assert c.get(path, follow_redirects=False).headers["location"] == "https://x/1", path


def test_誤りは符号と英語の文面で返る(world, principal_of, as_principal):
    """**文面ではなく符号で判定させる。** 文面は直る（訳も語調も変わる）。

    `detail` は文面を埋めた値を**構造化したまま**返す——数字を文から切り出す
    クライアントを作らせない。
    """
    # **他組織の ARK を先に用意する。** `as_principal` は同じ app の差し替えを
    # 上書きするので、あとから作った主体が有効になる（最後に A を作る）。
    theirs = as_principal(principal_of(manager=world["b"], client_id="b")).post(
        "/api/mint", json={}
    ).json()["ark"]

    c = as_principal(principal_of(manager=world["a"]))

    over = c.post("/api/mint/bulk", json={"data": [{} for _ in range(1001)]})
    assert over.status_code == 400
    assert over.json() == {
        "code": "ARKHE-1011",
        "message": "A request holds at most 1000 rows.",
        "detail": {"limit": 1000},
    }

    # 他組織の ARK には触れない。**符号が「範囲の話だ」と言っている。**
    denied = c.put("/api/update", json={"ark": theirs, "url": "https://x/1"})
    assert denied.status_code in (403, 404)
    assert denied.json()["code"].startswith("ARKHE-1")

    # 読めない ARK は 400。
    bad = c.put("/api/update", json={"ark": "not-an-ark", "url": "https://x/1"})
    assert bad.status_code == 400 and bad.json()["code"] == "ARKHE-1001"

    # scope が足りなければ、**足りない scope を名指しする**（最後に差し替える）。
    thin = as_principal(principal_of(manager=world["a"], scopes={"ark:read"}))
    short = thin.post("/api/mint", json={})
    assert short.status_code == 403
    assert short.json()["code"] == "ARKHE-1301"
    assert short.json()["detail"]["scope"] == "ark:mint"


def test_解決の符号は本文の行頭に出る(world, principal_of, as_principal):
    """解決は `text/plain` を返す（人も読む）ので、**符号を行頭に置く**。"""
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"].removeprefix("ark:")
    naan = key.split("/")[0]

    # 検査桁の合わない名前は「転記ミス」だと言う。
    mistyped = c.get(f"/ark:{naan}/x9zzzzzzzz")
    assert mistyped.status_code == 404
    assert mistyped.text.startswith("ARKHE-1403 ")

    # ARK として読めないもの。
    unreadable = c.get("/ark:/")
    assert unreadable.status_code == 400 and unreadable.text.startswith("ARKHE-1001 ")


def test_A1_ラベルの大小は経路でも無視する(world, principal_of, as_principal):
    """§3.2 手順3「**大小非依存で** 'ark:/' または 'ark:' に最初に一致した箇所を
    'ark:' に直す」。

    `parse_ark` は最初から大小非依存だったが、**経路照合は大小を見る**ので
    `/ARK:/…` はルータに届かず 404 になっていた。**直すのはラベルの 5 文字だけ**
    ——名前の大小は識別子の一部なので触らない（手順5）。
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"].removeprefix("ark:")
    for label in ("ark:", "ark:/", "ARK:", "ARK:/", "Ark:", "aRk:/"):
        r = c.get(f"/{label}{key}", follow_redirects=False)
        assert r.headers.get("location") == "https://x/1", label

    # **名前の大小は直さない。** 直すと別の識別子に当ててしまう。
    assert c.get(f"/ARK:{key.upper()}", follow_redirects=False).status_code == 404


def test_C7_THUMPのヘッダを付ける(world, principal_of, as_principal):
    """§5.2。`Link` の役目は仕様が説明している——**inflection を知らない受信者に、
    この応答が「修飾の付いていない ARK」を記述したものだと示す**。

    `rel` の綴りは仕様の応答例（`<…> rel="describes";`）ではなく RFC 8288 に従う。
    例のほうが誤りで、そのまま出すと標準の Link パーサが読めない。
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://x/1"}).json()["ark"].removeprefix("ark:")

    # 裸の `?` は入れない——クエリ文字列だけでは区別できず、この経路では
    # inflection 無し（＝転送）になる（`ARKHE_RAW_URI_HEADER` の項を見よ）。
    for q in ("??", "?info", "?json"):
        h = c.get(f"/ark:{key}{q}").headers
        assert h["thump-status"] == "0.6 200 OK", q
        assert h["link"] == f'</ark:{key}>; rel="describes"', q

    # 見つからないときも THUMP の応答である（符号は写す）。
    missing = c.get(f"/ark:{key}zz-not-registered?info")
    assert missing.status_code == 404
    assert missing.headers["thump-status"] == "0.6 404 Not Found"

    # **転送には付けない。** それは THUMP の答えではなく、対象への誘導。
    assert "thump-status" not in c.get(f"/ark:{key}", follow_redirects=False).headers


def test_C6_whereは転送先ではなくARK(world, principal_of, as_principal):
    """§5.1.2「**"where" は長期的な識別子であって、一時的な転送先ではない**」。

    以前は逆で、`where` に転送先の URL を入れ、ARK は URL が空のときの代替だった。
    記述は「この識別子は何を指すか」を答えるものなので、**行き先が変わっても
    変わらない値**が入っていなければ、記述として引用できない。
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={
        "url": "https://one.example/1", "title": "題", "who": "山田", "when": "2026",
    }).json()["ark"].removeprefix("ark:")

    body = c.get(f"/ark:{key}??").text
    assert f"where: ark:{key}" in body
    # **転送先は捨てない。** kernel の外に、あるときだけ出す。
    assert "redirect: https://one.example/1" in body

    j = c.get(f"/ark:{key}?json").json()
    assert j["where"] == f"ark:{key}" and j["redirect"] == "https://one.example/1"

    # 行き先を変えても `where` は動かない。**それがこの要素の意味である。**
    c.put("/api/update", json={"ark": f"ark:{key}", "url": "https://two.example/2"})
    j2 = c.get(f"/ark:{key}?json").json()
    assert j2["where"] == j["where"] and j2["redirect"] == "https://two.example/2"

    # 行き先が無い ARK でも `where` は答えられる（FAIR A2）。
    c.put("/api/tombstone", json={"ark": f"ark:{key}", "commitment": "失われた"})
    assert f"where: ark:{key}" in c.get(f"/ark:{key}??").text


def test_A4_エンコードされたスラッシュは区切りにならない(world, principal_of, as_principal):
    """draft-kunze-ark-42 §3.2「%-エンコードされた文字を復号形で現してはならない」。

    `%2F` は**「ここに `/` はあるが成分の区切りではない」と書く唯一の方法**
    （§3.2「予約文字を %-エンコードしてよいのは、その予約された意味を隠すときだけ」）。
    復号すると `base/a%2Fb`（1 つの名前）が `base/a/b`（`base/a` に含まれる `b`）に
    化け、**祖先 passthrough が base の行き先を継いでしまう**——別の識別子に
    別の答えを返すことになる。

    ASGI は経路を先に復号するので、`scope["raw_path"]` から取り直している。
    """
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post("/api/mint", json={"url": "https://base.example.org/1"}).json()["ark"]
    base = key.removeprefix("ark:")

    # 隠した `/` を含む修飾子を、別の行き先で登録する。
    r = c.post("/api/register", json={"ark": key, "qualifier": "/a%2fb",
                                      "url": "https://other.example.org/2"})
    assert r.status_code == 201
    # 手順5: 保存されるのは大文字に揃えた形。
    assert r.json()["ark"] == f"ark:{base}/a%2Fb"

    # **その行に当たる。** base の行き先＋`/a/b` ではない。
    hit = c.get(f"/ark:/{base}/a%2Fb", follow_redirects=False)
    assert hit.status_code == 302
    assert hit.headers["location"] == "https://other.example.org/2"

    # 小文字で来ても同じ行に当たる（手順5 は受け取り側でも効く）。
    assert c.get(f"/ark:/{base}/a%2fb", follow_redirects=False).headers["location"] == (
        "https://other.example.org/2"
    )

    # 素の `/` は別の識別子。**こちらは登録が無いので base から継ぐ。**
    passthrough = c.get(f"/ark:/{base}/a/b", follow_redirects=False)
    assert passthrough.status_code == 302
    assert passthrough.headers["location"] == "https://base.example.org/1/a/b"


def test_A4_raw_pathが無い環境では復号済みの経路に落ちる():
    """**生の経路を渡さないサーバでも動く。** 落ちる先は今までと同じ挙動。"""
    from types import SimpleNamespace

    from arkhe.api.resolve import _raw_ark_path

    url = SimpleNamespace(path="/ark:/99999/x54/c2")
    assert _raw_ark_path(SimpleNamespace(scope={}, url=url)) == "/ark:/99999/x54/c2"
    # query が混ざって渡るサーバがあるので、素の `?` で切る。
    req = SimpleNamespace(scope={"raw_path": b"/ark:/99999/x54%2Fc2?info"}, url=url)
    assert _raw_ark_path(req) == "/ark:/99999/x54%2Fc2"
    # UTF-8 でない生バイトは**捏造せず**復号済みへ落とす。
    bad = SimpleNamespace(scope={"raw_path": b"/ark:/99999/x\xff"}, url=url)
    assert _raw_ark_path(bad) == "/ark:/99999/x54/c2"


def test_well_known_arkは既定で仕様どおりのtext_plainを返す(world, principal_of, as_principal):
    """draft-kunze-ark-42 §5.6。**`Accept` を送らない相手には仕様の表現を返す。**

    `*/*` で独自の JSON を返すと、仕様どおりに読む発見クライアントからは
    「このホストは ARK リゾルバではない」に見える。
    """
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    r = c.get("/.well-known/ark")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    # 本文はリゾルバのルートパス 1 行。**末尾は `/`**——ここに Compact ARK を
    # 継ぎ足すと解決の経路になる、というのが仕様の定め。
    assert r.text.strip() == "/"
    assert c.get(f"{r.text.strip()}ark:/99999/x9abc").status_code in (200, 302, 404)
    # 同じ URL が 2 つの表現を持つので、間に挟まる cache のために要る。
    assert r.headers["vary"] == "Accept"


def test_well_known_arkはjsonを求められたときだけ在庫を返す(world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    r = c.get("/.well-known/ark", headers={"Accept": "application/json"})
    assert r.status_code == 200
    assert {n["naan"] for n in r.json()["naans"]} == {"99999", "88888"}
    # **仕様が定める値も JSON 側に入れる。** 片方だけ見て済ませられるように。
    assert r.json()["resolver_path"] == "/"
    assert r.headers["vary"] == "Accept"


@pytest.mark.parametrize(
    ("accept", "want"),
    [
        ("", "text/plain"),                                   # ヘッダ無し
        ("*/*", "text/plain"),                                # curl の既定
        ("application/json", "application/json"),
        ("application/json, text/plain;q=0.9", "application/json"),
        ("text/plain, application/json", "text/plain"),       # 同点は仕様の側へ
        ("text/html,application/xhtml+xml,*/*;q=0.8", "text/plain"),  # ブラウザ
        ("application/*", "application/json"),
        ("application/xml", "text/plain"),                    # どちらも出せない
    ],
)
def test_well_known_arkの媒体の選び方(accept, want, world, principal_of, as_principal):
    c = as_principal(principal_of(authority=Authority.SYSTEM, naan=""))
    r = c.get("/.well-known/ark", headers={"Accept": accept} if accept else {})
    assert r.headers["content-type"].startswith(want)


@pytest.mark.parametrize(
    ("root_path", "want"),
    [("", "/"), ("/", "/"), ("/pid", "/pid/"), ("/pid/", "/pid/"), (None, "/")],
)
def test_well_known_arkはマウント位置を答える(root_path, want):
    """**前段でパスを切っているなら、その値を答える。**

    仕様は「そのパスに Compact ARK を継ぎ足すと解決の要求になる」と定めている
    ので、`/` 決め打ちにするとプレフィクス付きの構成で案内先が実際の口とずれる。
    """
    from types import SimpleNamespace

    from arkhe.api.resolve import _resolver_path

    assert _resolver_path(SimpleNamespace(scope={"root_path": root_path})) == want


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
    key = r.json()["ark"].removeprefix("ark:")
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
    ).json()["ark"].removeprefix("ark:")
    r = c.get(f"/ark:/{key}")
    assert r.status_code == 200                     # 302 ではない
    assert "urn:isbn:0451450523" in r.text          # 行き先は見せる
    assert '<a href="urn:' not in r.text            # ただしリンクにはしない


def test_開ける行き先は転送する(world, principal_of, as_principal):
    c = as_principal(principal_of(manager=world["a"]))
    key = c.post(
        "/api/mint", json={"url": "https://ok.example/1"}
    ).json()["ark"].removeprefix("ark:")
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


@pytest.mark.parametrize(
    "resolver,want", [(True, "replica"), (False, "primary")], ids=["resolver", "minter"]
)
def test_接続先はこのappの設定で決まる(resolver, want):
    """**`ARKHE_READ_DATABASE_URL` を効かせる。** 設定は読まれるだけで誰も使って
    おらず、resolver は書き込みエンジンから読んでいた——レプリカを立てても向かない。

    **見るのは `create_app` に渡した設定のほう。** 役割を `get_settings()`（環境変数の
    キャッシュ）から引くと、`create_app(settings=…)` で建てた app とは別の設定を
    見ることになり、**ルータの出し分けと接続先が食い違う**。ここで渡す URL は環境変数に
    無いので、環境から引いていれば下の照合は通らない。
    """
    from fastapi.testclient import TestClient

    from arkhe.app import create_app
    from arkhe.settings import Settings

    app = create_app(
        Settings(
            resolver=resolver, auth=["apikey"], admin_login="bearer",
            database_url="sqlite:///primary.sqlite3",
            read_database_url="sqlite:///replica.sqlite3",
        )
    )

    # **本物の依存をそのまま通す。** 差し替えると、確かめたい配線が消える。
    # `Db` を冒頭で import してあるのは、`from __future__ import annotations` の下では
    # 注釈が文字列になり、関数内 import だと FastAPI が解決できないため。
    @app.get("/_bind", include_in_schema=False)
    def _bind(session: Db):
        return {"url": str(session.get_bind().url)}

    assert TestClient(app).get("/_bind").json()["url"].endswith(f"{want}.sqlite3")



def _spec(**over):
    """その構成の OpenAPI を起こす。**本番と同じ `create_app` を通す**
    ——仕様書は口の出し分けの結果なので、app を組まずに確かめても意味がない。"""
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
    security = spec["paths"]["/api/mint"]["post"]["security"]
    assert {"oauth2": ["ark:mint"]} in security   # 何が要るかも書く
    assert {"bearer": []} in security


@pytest.mark.parametrize(
    "over", [{"auth": ["apikey"]}, {"resolver": True, "auth": ["apikey"]}],
    ids=["minter-apikey", "resolver"],
)
def test_口の無い構成では取り方を広告しない(over):
    """**無い口を指さない。** 広告だけ残ると、生成したクライアントが 404 を踏む。"""
    spec = _spec(**over)
    assert "oauth2" not in spec.get("components", {}).get("securitySchemes", {})
    assert "/oauth/token" not in spec["paths"]


def test_解決の3xxは委譲テンプレートが出せるものと一致する():
    """**宣言と実装を突き合わせる。** 仕様書に並べた 3xx は、`expand_redirect` が
    実際に出せる符号（`_STATUS_PREFIX`）と同じでなければ、契約として嘘になる。
    """
    from arkhe.api.resolve import _RESOLVE_RESPONSES
    from arkhe.domain.resolution import expand_redirect

    declared = {c for c in _RESOLVE_RESPONSES if 300 <= c < 400}
    produced = {expand_redirect(f"{c} https://x/$id", "99999", "abc")[0] for c in declared}
    assert produced == declared
    # 受けない符号は既定に落ちる。**宣言を増やす理由にはならない。**
    assert expand_redirect("308 https://x/$id", "99999", "abc")[0] == 302


def test_解決の200は宣言した3つの媒体で返る(world, principal_of, as_principal):
    """**同じ 200 でも媒体が違う。** `application/json` だけを宣言していたので、
    仕様書から起こしたクライアントは ANVL と HTML を「知らない応答」として扱う。
    """
    from arkhe.api.resolve import _RESOLVE_RESPONSES

    c = as_principal(principal_of(manager=world["a"]))
    key = c.post(
        "/api/mint", json={"url": "https://example.org/1", "title": "A"}
    ).json()["ark"].removeprefix("ark:")

    got = {
        c.get(f"/ark:/{key}?{q}").headers["content-type"].split(";")[0]
        for q in ("json", "?", "info")
    }
    assert got == set(_RESOLVE_RESPONSES[200]["content"])


def test_宣言したscopeと検査するscopeが一致する():
    """**宣言と検査が 2 か所に分かれている。** 仕様書に出るのは口の `needs(…)`、
    実際に弾くのは本体の `require_scope(…)`——ずれれば仕様書が嘘になる。

    束ねなかったのは、束ねると scope が `bearer` にも付くため。OpenAPI は
    **oauth2 以外のスキームに scope を書くことを許さない**（空配列でなければ
    ならない）ので、`Security` に包む対象は oauth2 だけに限っている。
    """
    import ast
    import pathlib

    src = pathlib.Path("src/arkhe/api/mint.py").read_text(encoding="utf-8")
    for fn in ast.walk(ast.parse(src)):
        if not isinstance(fn, ast.FunctionDef):
            continue
        declared = [
            k.value.args[0].value
            for d in fn.decorator_list if isinstance(d, ast.Call)
            for k in d.keywords
            if k.arg == "dependencies" and isinstance(k.value, ast.Call)
            and getattr(k.value.func, "id", "") == "needs"
        ]
        enforced = [
            x.args[1].value for x in ast.walk(fn)
            if isinstance(x, ast.Call)
            and ast.unparse(x.func) == "authz.require_scope"
        ]
        assert declared == enforced, f"{fn.name}: 宣言 {declared} / 検査 {enforced}"
        if fn.name != "_apply":
            assert not enforced or declared, f"{fn.name}: 検査はあるのに宣言が無い"


def test_scopeはoauth2にしか付かない():
    """OpenAPI 3.1 §4.8.30: **oauth2 と openIdConnect 以外は空配列でなければならない。**
    `bearer` は `type: http` なので、ここに scope を書くと仕様として不正になる。
    """
    spec = _spec(auth=["apikey", "oauth2"])
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            for requirement in op.get("security", []):
                for name, scopes in requirement.items():
                    if name != "oauth2":
                        assert scopes == [], f"{method.upper()} {path}: {name} に {scopes}"
