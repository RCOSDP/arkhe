"""**認証と到達範囲**を、本物の資格情報で。

単体の試験は認証を差し替えて認可だけを見ている——速く、網も細かい。**ここで見るのは
差し替えていない側**である: CLI が刷った鍵で本当に入れるか、止めた主体が本当に
止まるか、`client_credentials` で取ったトークンが本当に使えるか。
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import NAAN, World

pytestmark = pytest.mark.e2e


def test_鍵が無ければ採番できない(world: World):
    r = world.api("post", "/api/mint", key=None, json={"url": "https://example.org/x"})
    assert r.status_code == 401


def test_でたらめな鍵では入れない(world: World):
    r = world.api("post", "/api/mint", key="arkhe_" + "z" * 43,
                  json={"url": "https://example.org/x"})
    assert r.status_code == 401


def test_scope_の外は断る(world: World, published):
    """scope は**階層ではない**。`ark:mint` を持っていても読めるとは限らない。"""
    r = world.api("get", "/api/stats", key="mint_only")
    assert r.status_code == 403, r.text
    upd = world.api("put", "/api/update", key="mint_only",
                    json={"ark": published["ark"], "url": "https://example.org/nope"})
    assert upd.status_code == 403
    # 持っている scope は通る
    assert world.api("post", "/api/mint", key="mint_only",
                     json={"url": "https://example.org/e2e/mint-only"}).status_code == 201


def test_他組織の_ARK_には届かない(world: World, published):
    """M4: **読み取りも到達範囲に絞る**（arklet は認可を一切していなかった）。"""
    seen = world.api("post", "/api/query", key="other", json={"data": [published["ark"]]})
    assert seen.status_code == 200
    assert seen.json()["data"] == [], "**他組織の行が読めている**"

    wrote = world.api("put", "/api/update", key="other",
                      json={"ark": published["ark"], "url": "https://evil.example/x"})
    assert wrote.status_code in (403, 404), wrote.text
    # 行き先は動いていない
    assert world.resolve(published["ark"]).headers["location"] == published["url"]


def test_止めた主体は入れなくなる(world: World):
    """委譲した認証では**止めるのが唯一の手立て**——鍵を持っていないのだから。"""
    assert world.api("post", "/api/mint", key="stop",
                     json={"url": "https://example.org/e2e/before-stop"}).status_code == 201
    world.cli("client", "disable", "e2e-stop")
    after = world.api("post", "/api/mint", key="stop",
                      json={"url": "https://example.org/e2e/after-stop"})
    assert after.status_code in (401, 403), after.text


def test_一日の上限を超えたら採番できない(world: World):
    """R3: **一組織の暴走を止める。** 上限 1 本の組織で 2 本目を採る。"""
    first = world.api("post", "/api/mint", key="quota",
                      json={"url": "https://example.org/e2e/quota-1"})
    assert first.status_code == 201, first.text
    second = world.api("post", "/api/mint", key="quota",
                       json={"url": "https://example.org/e2e/quota-2"})
    assert second.status_code in (403, 429), second.text


def test_client_credentials_で取ったトークンで採番できる(world: World):
    """RFC 6749 §4.4。**本文でも Basic でも受ける**と仕様書に書いてある道。"""
    got = world.api("post", "/oauth/token", key=None, data={
        "grant_type": "client_credentials",
        "client_id": "e2e-secret",
        "client_secret": world.keys["secret"],
        "scope": "ark:mint",
    })
    assert got.status_code == 200, got.text
    token = got.json()["access_token"]

    r = world.api("post", "/api/mint", key=token,
                  json={"url": "https://example.org/e2e/by-token"})
    assert r.status_code == 201, r.text
    assert r.json()["ark"].startswith(f"ark:{NAAN}/")


def test_登録に無い_scope_を求めたら断る(world: World):
    """**要求で範囲は広がらない**（権限昇格そのもの）。RFC 6749 §5.2 の
    `invalid_scope` で断る——**黙って削らない**。削ると、クライアントは取れた
    つもりの権限で動き、後から 403 に出会う。"""
    got = world.api("post", "/oauth/token", key=None, data={
        "grant_type": "client_credentials",
        "client_id": "e2e-secret",
        "client_secret": world.keys["secret"],
        "scope": "ark:purge",
    })
    assert got.status_code == 400, got.text
    assert got.json()["error"] == "invalid_scope", got.text


def test_知らない_grant_type_は断る(world: World):
    got = world.api("post", "/oauth/token", key=None, data={
        "grant_type": "password", "client_id": "e2e-secret",
        "client_secret": world.keys["secret"],
    })
    assert got.status_code == 400
    assert got.json()["error"]
