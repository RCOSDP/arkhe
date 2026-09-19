"""**設定で締める側**。宣言してあるだけで効いていない設定を、外から確かめる。

`ARKHE_ALLOWED_HOSTS` は**設定として宣言され、文書にも書いてあって、どこからも
読まれていなかった**——単体の試験は app を自前で組み立てるので、
`create_app` が入れるはずの中間層が抜けていても気づけない。**建てないと分からない。**
"""

from __future__ import annotations

import httpx
import pytest

from tests.e2e.conftest import serve, stop

pytestmark = pytest.mark.e2e

HOST = "ark.example.test"


@pytest.fixture(scope="module")
def guarded(world, tmp_path_factory):
    """`ARKHE_ALLOWED_HOSTS` を締めた resolver を 1 つだけ建てる。"""
    logs = tmp_path_factory.mktemp("e2e-hardening")
    env = {**world.env, "ARKHE_RESOLVER": "1",
           "ARKHE_READ_DATABASE_URL": world.env["ARKHE_DATABASE_URL"],
           "ARKHE_ALLOWED_HOSTS": f"{HOST},127.0.0.1"}
    server = serve(env, logs / "guarded.log", "guarded resolver")
    yield server
    stop(server)


def test_許した_Host_なら通る(guarded, published):
    r = httpx.get(f"{guarded.url}/{published['ark']}",
                  headers={"Host": HOST}, follow_redirects=False, timeout=30)
    assert r.status_code == 302


def test_許していない_Host_は断る(guarded, published):
    """**この設定は 0.9.2 まで死んでいた。** ここが 302 に戻ったら、また死んでいる。"""
    r = httpx.get(f"{guarded.url}/{published['ark']}",
                  headers={"Host": "evil.example"}, follow_redirects=False, timeout=30)
    assert r.status_code == 400, f"**Host を見ていない**: {r.status_code}"


@pytest.fixture(scope="module")
def closed(world, tmp_path_factory):
    """閉域のリゾルバ。**自分の領域なら公開前でも解決する**（`ARKHE_RESOLVE_UNPUBLISHED`）。"""
    logs = tmp_path_factory.mktemp("e2e-closed")
    env = {**world.env, "ARKHE_RESOLVER": "1",
           "ARKHE_READ_DATABASE_URL": world.env["ARKHE_DATABASE_URL"],
           "ARKHE_RESOLVE_UNPUBLISHED": "true"}
    server = serve(env, logs / "closed.log", "closed resolver")
    yield server
    stop(server)


def test_閉域のリゾルバは公開前も解決する(world, closed, mint):
    """**閉じた網の中で採った ARK を、その網のリゾルバが解決できないなら**
    閉じた対象に PID を配る意味が無い。公開のリゾルバでは、同じ行が 404。"""
    target = "https://closed.example.org/object"
    ark = mint(url=target, reserve=True)["ark"]

    inside = httpx.get(f"{closed.url}/{ark}", follow_redirects=False, timeout=30)
    assert inside.status_code == 302
    assert inside.headers["location"] == target

    assert world.resolve(ark).status_code == 404, "**公開のリゾルバが公開前を出した**"
