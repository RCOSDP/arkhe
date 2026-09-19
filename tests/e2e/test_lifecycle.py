"""**一生**を通しで踏む。公開前 → 公開 → 取り下げ → 再公開 → 削除。

単体の試験は各段を個別に見ているが、ここで見るのは**段と段のあいだ**である
——採番した minter の書き込みが、**別プロセスの resolver から見えるか**。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.e2e

TARGET = "https://example.org/e2e/lifecycle"


def test_同じ_request_id_の再送では番号が増えない(world, published):
    """F4: **応答が失われただけのときに、死んだ番号を増やさない。**"""
    r = world.api("post", "/api/mint",
                  json={"url": published["url"], "request_id": "e2e-shared"})
    assert r.status_code == 200, r.text
    assert r.json()["ark"] == published["ark"]


def test_公開前は解決しないが公開すれば解決する(world, mint):
    """**公開前の ARK は、未登録の名前と同じに扱う**——`?info` にも出さない。"""
    ark = mint(url=TARGET, reserve=True)["ark"]
    assert ark
    assert world.resolve(ark).status_code == 404
    assert world.resolve(ark, "?info").status_code == 404

    r = world.api("post", "/api/publish", json={"ark": ark})
    assert r.status_code == 200, r.text
    assert world.resolve(ark).headers["location"] == TARGET


def test_取り下げると解決を止め_再公開すると戻る(world, mint):
    """公開は**行き来できる**。名前は振り直さないので、古い参照は 404 のまま。"""
    ark = mint(url=TARGET)["ark"]
    assert world.resolve(ark).status_code == 302

    r = world.api("post", "/api/unpublish",
                  json={"ark": ark, "reason": "e2e で取り下げる", "confirm": ark})
    assert r.status_code == 200, r.text
    assert world.resolve(ark).status_code == 404

    assert world.api("post", "/api/publish", json={"ark": ark}).status_code == 200
    assert world.resolve(ark).status_code == 302


def test_一度も公開していない_ARK_は理由なしで消せる(world, mint):
    """**公開前だけの特権。** 消した名前は `WithdrawnName` に残り、二度と当たらない。"""
    ark = mint(url=TARGET, reserve=True)["ark"]
    r = world.api("post", "/api/delete", json={"ark": ark})
    assert r.status_code in (200, 204), r.text
    assert world.resolve(ark).status_code == 404
    # 消えたことを、読みの口からも確かめる
    q = world.api("post", "/api/query", json={"data": [ark]})
    assert q.json()["data"] == []


def test_一度公開した_ARK_は理由と確認がないと消せない(world, mint):
    """**「一度出した」は一方通行。** 取り下げても、消すには理由と打ち直しが要る。"""
    ark = mint(url=TARGET)["ark"]
    world.api("post", "/api/unpublish",
              json={"ark": ark, "reason": "消す前に取り下げる", "confirm": ark})

    bare = world.api("post", "/api/delete", json={"ark": ark})
    assert bare.status_code in (400, 409, 422), bare.text

    ok = world.api("post", "/api/delete",
                   json={"ark": ark, "reason": "e2e で消す", "confirm": ark})
    assert ok.status_code in (200, 204), ok.text


def test_公開中のものは取り下げずに消せない(world, mint):
    ark = mint(url=TARGET)["ark"]
    r = world.api("post", "/api/delete",
                  json={"ark": ark, "reason": "消す", "confirm": ark})
    assert r.status_code == 409, r.text
    assert world.resolve(ark).status_code == 302  # **解決は続いている**


def test_行き先を書き換えると解決が追う(world, mint):
    """minter で書いたものが、**別プロセスの resolver から見える**か。"""
    ark = mint(url=TARGET)["ark"]
    moved = "https://example.org/e2e/moved"
    r = world.api("put", "/api/update", json={"ark": ark, "url": moved})
    assert r.status_code == 200, r.text
    assert world.resolve(ark).headers["location"] == moved


def test_まとめて採ると全部解決する(world):
    """一括は**認証 1 回を件数で割る**道。採った全部が本当に引けるかを見る。"""
    r = world.api("post", "/api/mint/bulk", json={"data": [
        {"url": f"https://example.org/e2e/bulk/{i}"} for i in range(5)
    ]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created"] == 5
    for i, row in enumerate(body["minted"]):
        got = world.resolve(row["ark"])
        assert got.status_code == 302
        assert got.headers["location"] == f"https://example.org/e2e/bulk/{i}"


def test_修飾子を明示して登録すると_継承より優先される(world, mint):
    """B4: 既定は祖先に継ぐが、**その 1 点だけ別の所在**にできる。"""
    base = mint(url=TARGET)["ark"]
    special = "https://example.org/e2e/elsewhere"
    r = world.api("post", "/api/register",
                  json={"ark": base, "qualifier": "/part1", "url": special})
    assert r.status_code == 201, r.text
    assert world.resolve(base, "/part1").headers["location"] == special
    # 登録していない兄弟は、今までどおり継ぐ
    assert world.resolve(base, "/part2").headers["location"].endswith("/part2")


def test_保留は転送だけを止め_記述は返り続ける(world, mint):
    """`404` は嘘（識別子は在る）、`503` は壊れて見える。**`200` と記述**を返す。"""
    ark = mint(url=TARGET)["ark"]
    until = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    r = world.api("put", "/api/hold",
                  json={"ark": ark, "until": until, "reason": "e2e で止める"})
    assert r.status_code == 200, r.text

    held = world.resolve(ark)
    assert held.status_code == 200
    assert "e2e で止める" in held.text  # **理由は公開の口に出る**

    assert world.api("put", "/api/hold/release", json={"ark": ark}).status_code == 200
    assert world.resolve(ark).status_code == 302


def test_墓碑は識別子を残して到達性だけを消す(world, mint):
    """`NR` を宣言している以上、**識別子は消せない**。消せるのは行き先だけ。"""
    ark = mint(url=TARGET)["ark"]
    r = world.api("put", "/api/tombstone", json={"ark": ark, "url": ""})
    assert r.status_code == 200, r.text

    gone = world.resolve(ark)
    assert gone.status_code == 200          # **404 にはしない**——名前は在る
    assert world.api("post", "/api/query", json={"data": [ark]}).json()["data"]
