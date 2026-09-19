"""解決の道。**resolver に建てた口を、素の HTTP で仕様どおりに叩く。**

ここで見るのは、単体の試験が `TestClient` で見ているのと同じ規則が、
**本物の経路（ASGI サーバ・ヘッダ・URL の正規化）を通っても同じか**である。
`%2F` や大文字小文字は、途中の層で握り潰されうる。
"""

from __future__ import annotations

import pytest

from tests.e2e.conftest import (
    DELEGATE,
    DELEGATED_NAAN,
    GLOBAL_RESOLVER,
    NAAN,
    UNKNOWN_NAAN,
    World,
)

pytestmark = pytest.mark.e2e


def test_修飾子は祖先から継いで転送される(world: World, published):
    """A1: 登録されていない修飾子は、**祖先の行き先に継いで**送る。"""
    r = world.resolve(published["ark"], "/page1")
    assert r.status_code == 302
    assert r.headers["location"].startswith(published["url"])
    assert r.headers["location"].endswith("/page1")


def test_ark_のラベルは大文字でも通る(world: World, published):
    """§2.5.1: `ark:` のラベルは大小を区別しない。**名前の側は区別する。**"""
    upper = published["ark"].replace("ark:", "ARK:", 1)
    assert world.resolve(upper).status_code == 302


def test_名前の中のハイフンは無視される(world: World, published):
    """§2.5.2: ハイフンは**書き写しのための飾り**で、名前の一部ではない。"""
    name = published["ark"].split("/", 1)[1]
    hyphenated = f"ark:{NAAN}/{name[:3]}-{name[3:]}"
    r = world.resolve(hyphenated)
    assert r.status_code == 302
    assert r.headers["location"] == published["url"]


def test_info_は認証なしで読める(world: World, published):
    r = world.resolve(published["ark"], "?info")
    assert r.status_code == 200
    assert published["ark"].split(":")[1] in r.text
    assert published["url"] in r.text


def test_疑問符二つも記述を返す(world: World, published):
    """C4: `??` は「この識別子について教えよ」。**転送しない。**"""
    r = world.resolve(published["ark"], "??")
    assert r.status_code == 200


def test_公開ページで_script_を実行させない(world: World, published):
    """`?info` は**認証を要さない公開ページ**で、載る文字列を決めるのは採番した側。

    だから **CSP で script を止める**。ここが緩むと、採番できる者が
    公開ページに任意の script を置けることになる。
    """
    r = world.resolve(published["ark"], "?info")
    csp = r.headers.get("content-security-policy", "")
    assert "script-src 'none'" in csp, csp
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_知らない名前は404(world: World):
    """D3: **自分が権威を持つ NAAN の未知の名前は 404。**「無い」と言える。"""
    assert world.resolve(f"ark:{NAAN}/e1zzzzzzzzz").status_code == 404


def test_委譲した_NAAN_は委譲先へ送る(world: World):
    """D2: 解決を委ねた NAAN は、**その先へ転送する**。台帳に行は無い。"""
    r = world.resolve(f"ark:{DELEGATED_NAAN}/anything")
    assert r.status_code == 302
    assert r.headers["location"].startswith(DELEGATE)


def test_知らない_NAAN_は全体リゾルバへ送る(world: World):
    """D2: 知らない NAAN は**自分の知識の外**。n2t へ渡す（404 にはしない）。"""
    r = world.resolve(f"ark:{UNKNOWN_NAAN}/whatever")
    assert r.status_code == 302
    assert r.headers["location"].startswith(GLOBAL_RESOLVER)


def test_壊れた_ark_は400(world: World):
    """NAAN の形をしていないものは、**解決以前に読めない**。"""
    assert world.resolve("ark:/").status_code in (400, 404)
