"""**管理画面に、合言葉で入る。**

画面は単体の試験でも叩いているが、そこでは主体を差し替えている。ここで通すのは
**入口そのもの**——`client passwd` で置いた合言葉、セッションの cookie、
そこから先の画面と、画面の form が本当に台帳を動かすところまで。
"""

from __future__ import annotations

import httpx
import pytest

from tests.e2e.conftest import World

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def signed_in(world: World) -> httpx.Client:
    """合言葉で入って、cookie を持ったままにする。"""
    client = httpx.Client(base_url=world.minter.url, follow_redirects=False, timeout=30)
    r = client.post("/admin/login",
                    data={"username": world.admin["username"],
                          "password": world.admin["password"]})
    assert r.status_code == 302, r.text
    assert client.cookies, "**cookie が発行されていない**"
    yield client
    client.close()


def test_名乗らなければ画面は見せない(world: World):
    r = httpx.get(f"{world.minter.url}/admin/", follow_redirects=False, timeout=30)
    assert r.status_code in (302, 303, 401), r.status_code
    if r.status_code in (302, 303):
        assert "/admin/login" in r.headers["location"]


def _login(world: World, username: str, password: str) -> httpx.Response:
    return httpx.post(f"{world.minter.url}/admin/login",
                      data={"username": username, "password": password},
                      follow_redirects=False, timeout=30)


def test_合言葉が違えば入れない(world: World):
    r = _login(world, world.admin["username"], "まちがい")
    assert r.status_code == 401
    assert not r.cookies, "**入れていないのに cookie が出ている**"


def test_居ない利用者でも同じ断り方をする(world: World):
    """**理由を分けない。** 「その ID は無い」と分かると、利用者の一覧を
    総当たりで作れてしまう。**返る画面まで同じ**であることを見る。"""
    wrong = _login(world, world.admin["username"], "まちがい")
    missing = _login(world, "居ない人", "まちがい")
    assert missing.status_code == wrong.status_code == 401
    assert missing.text == wrong.text, "**断り方が分かれている**——ID の総当たりに使える"


def test_入れば台帳の画面が出る(signed_in: httpx.Client):
    for path in ("/admin/", "/admin/arks", "/admin/stats", "/admin/audit", "/admin/clients"):
        r = signed_in.get(path)
        assert r.status_code == 200, f"{path}: {r.status_code}"
        assert "<html" in r.text.lower()


def test_画面から取り下げて_再公開できる(world: World, signed_in: httpx.Client, mint):
    """**form が本当に台帳を動かす**ところまで。押した結果を解決の側で確かめる。"""
    ark = mint(url="https://example.org/e2e/admin")["ark"]
    assert world.resolve(ark).status_code == 302

    down = signed_in.post(f"/admin/arks/{ark}/unpublish",
                          data={"reason": "画面から取り下げる", "confirm": ark})
    assert down.status_code in (200, 302, 303), down.text
    assert world.resolve(ark).status_code == 404, "**画面から取り下げたのに解決している**"

    up = signed_in.post(f"/admin/arks/{ark}/publish", data={"ark": ark})
    assert up.status_code in (200, 302, 303), up.text
    assert world.resolve(ark).status_code == 302


def test_一件の画面に採番した内容が出る(signed_in: httpx.Client, published):
    r = signed_in.get(f"/admin/arks/{published['ark']}")
    assert r.status_code == 200
    assert published["url"] in r.text


def test_出れば見えなくなる(world: World, signed_in: httpx.Client):
    out = signed_in.post("/admin/logout")
    assert out.status_code in (200, 302, 303)
    again = signed_in.get("/admin/")
    assert again.status_code in (302, 303, 401)
