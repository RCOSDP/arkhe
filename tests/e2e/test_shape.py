"""**組み上がった形**を見る。部品ではなく、役割の分かれ方と建ち方。

この版までに、この形でしか見つからなかったものが実際に 3 つある:

  * `uvicorn arkhe.app:app` は起動しない（**この app はファクトリ**）
  * `/readyz` が、resolver の読まない DB を見ていた
  * resolver に採番の口が無いこと自体、app を建てないと分からない
"""

from __future__ import annotations

import json

import httpx
import pytest

from tests.e2e.conftest import World

pytestmark = pytest.mark.e2e


def test_採番できる(world: World, published):
    assert published["ark"].startswith(f"ark:{world.naan}/{world.shoulder.lstrip('/')}")
    assert published["published_at"]


def test_resolver_で解決できる(world: World, published):
    r = world.resolve(published["ark"])
    assert r.status_code == 302
    assert r.headers["location"] == published["url"]


def test_resolver_に採番の口は無い(world: World):
    r = httpx.post(
        f"{world.resolver.url}/api/mint",
        headers={"Authorization": f"Bearer {world.keys['ops']}"},
        json={"url": "https://example.org/x"}, timeout=30,
    )
    assert r.status_code == 404, "**resolver が採番を受けた。** 役割が分かれていない"


def test_resolver_に管理画面は無い(world: World):
    assert httpx.get(f"{world.resolver.url}/admin/", timeout=30).status_code == 404
    # minter には在る（認証は要る——何が返るかではなく、**口が在ること**を見る）
    assert httpx.get(
        f"{world.minter.url}/admin/", follow_redirects=False, timeout=30
    ).status_code != 404


def test_minter_に解決の口は無い(world: World, published):
    r = httpx.get(
        f"{world.minter.url}/{published['ark']}", follow_redirects=False, timeout=30
    )
    assert r.status_code == 404


def test_readyz_はその役割が読む_DB_を見る(world: World):
    """resolver の書き込み側は**どこにも繋がっていない**（`_BOGUS`）。

    ここが 200 を返すのは、**読む側を見ているから**である。0.11.0 まで主系を
    見ていて、レプリカが落ちても Ready と答え続けていた。
    """
    for server in (world.minter, world.resolver):
        assert httpx.get(f"{server.url}/healthz", timeout=30).status_code == 200
        assert httpx.get(f"{server.url}/readyz", timeout=30).status_code == 200


def test_well_known_は素で平文_JSON_は頼めば返る(world: World):
    plain = httpx.get(f"{world.resolver.url}/.well-known/ark", timeout=30)
    assert plain.status_code == 200
    assert plain.text.strip().endswith("/")

    data = httpx.get(
        f"{world.resolver.url}/.well-known/ark",
        headers={"Accept": "application/json"}, timeout=30,
    )
    assert data.status_code == 200
    json.loads(data.text)


def test_委譲した名前空間は_well_known_に出る(world: World):
    """**外形監視で見るべきものの一覧**でもある——消えればその名前空間が死ぬ。"""
    body = httpx.get(
        f"{world.resolver.url}/.well-known/ark",
        headers={"Accept": "application/json"}, timeout=30,
    ).json()
    assert world.delegated_naan in json.dumps(body, ensure_ascii=False)


def test_台帳を数えられる(world: World, published):
    r = world.api("get", "/api/stats")
    assert r.status_code == 200, r.text
    assert r.json()["arks"] >= 1


def test_CLI_と_API_は同じ数を返す(world: World, published):
    """**画面・CLI・API が同じ `domain.stats` を通る**ことを、外から確かめる。"""
    api = world.api("get", "/api/stats").json()["arks"]
    out = world.cli("stat")
    assert str(api) in out, out


def test_fingerprint_が取れる(world: World, published):
    """復元の検証はこれで機械化してある。**取れること自体を見る。**"""
    out = world.cli("fingerprint")
    assert out.strip()
