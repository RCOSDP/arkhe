"""通しの検査。**本番と同じ形で建てて、素の HTTP で叩く。**

ほかの試験は `TestClient` で app を直に呼び、DB は SQLite、認証は差し替えてある
——速いし、認可の網はそちらのほうが細かい。**そこを通り抜けるものだけを、ここで
捕まえる。** ここが見るのは、部品ではなく**組み上がった形**である:

  * `uvicorn` で建つか（**この app はファクトリ**。`arkhe.app:app` では起動しない
    ——復元手順にそう書いてあって、動かなかった）
  * CLI で組み立てた台帳に、**その CLI が刷った鍵**で届くか
  * minter に解決の口が無く、**resolver に採番の口が無い**か
  * resolver が**書き込み DB に触れない**か（下の `_BOGUS` を見よ）
  * PostgreSQL の上で動くか（ほかの試験は SQLite）

**docker が無ければ SKIP する。** 黙って緑にはしない——「入っていないから通った」が
いちばん危ない。

    uv run pytest -m e2e          この検査だけ
    bash scripts/check.sh         手順の中から呼ばれる
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
PG_NAME = "arkhe-e2e-pg"
NAAN = "99999"
SHOULDER = "/e1"
TARGET = "https://example.org/e2e/object"

#: resolver の**書き込み側を、どこにも繋がらない先に向ける**。読みは本物のレプリカ
#: （ここでは同じ DB）に向ける。resolver が解決や `/readyz` で書き込み側を触ったら、
#: **この検査が落ちる**——実際 `/readyz` は 0.11.0 まで触っていた。
_BOGUS = "postgresql+psycopg://arkhe:arkhe@127.0.0.1:1/arkhe"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(args: list[str], env: dict[str, str]) -> str:
    """**落ちたら出力ごと見せる。** 通しの検査で「どこかで失敗した」は使えない。"""
    p = subprocess.run(
        args, cwd=ROOT, env={**os.environ, **env}, capture_output=True, text=True
    )
    if p.returncode != 0:
        raise AssertionError(f"{' '.join(args)} が落ちた\n{p.stdout}\n{p.stderr}")
    return p.stdout


@dataclass
class Server:
    proc: subprocess.Popen
    url: str
    log: Path

    def tail(self) -> str:
        return self.log.read_text(errors="replace")[-4000:]


def _serve(env: dict[str, str], log: Path, label: str) -> Server:
    """`uvicorn` で 1 つ建てて、`/healthz` が返るまで待つ。"""
    port = _free_port()
    handle = log.open("w")
    proc = subprocess.Popen(
        # **`--factory`。** ここを落とすと "Attribute \"app\" not found" で死ぬ。
        ["uv", "run", "uvicorn", "arkhe.app:create_app", "--factory",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env={**os.environ, **env}, stdout=handle, stderr=subprocess.STDOUT,
    )
    server = Server(proc, f"http://127.0.0.1:{port}", log)
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"{label} が起動せずに終了した\n{server.tail()}")
        try:
            if httpx.get(f"{server.url}/healthz", timeout=1).status_code == 200:
                return server
        except httpx.HTTPError:
            time.sleep(0.3)
    proc.kill()
    raise AssertionError(f"{label} が 60 秒で応えなかった\n{server.tail()}")


@dataclass
class World:
    minter: Server
    resolver: Server
    key: str


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    """PostgreSQL・minter・resolver を建て、CLI で台帳を組む。**module で 1 度だけ。**"""
    if not shutil.which("docker"):
        pytest.skip("docker が無い。**通しの検査を通していない**")
    if not shutil.which("uv"):
        pytest.skip("uv が無い。**通しの検査を通していない**")

    logs = tmp_path_factory.mktemp("e2e")
    port = _free_port()
    subprocess.run(["docker", "rm", "-f", PG_NAME], capture_output=True)
    subprocess.run(
        ["docker", "run", "-d", "--name", PG_NAME,
         "-e", "POSTGRES_USER=arkhe", "-e", "POSTGRES_PASSWORD=arkhe",
         "-e", "POSTGRES_DB=arkhe", "-p", f"{port}:5432", "postgres:17-alpine"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    servers: list[Server] = []
    try:
        for _ in range(60):
            probe = subprocess.run(
                ["docker", "exec", PG_NAME, "pg_isready", "-U", "arkhe"], capture_output=True
            )
            if probe.returncode == 0:
                break
            time.sleep(1)
        else:
            raise AssertionError("PostgreSQL が起動しない")

        url = f"postgresql+psycopg://arkhe:arkhe@127.0.0.1:{port}/arkhe"
        base = {"ARKHE_DATABASE_URL": url, "ARKHE_AUTH": "apikey", "ARKHE_RESOLVER": "0"}

        # **マイグレーションで作る。** `create_all` で作った DB は、運用の DB ではない。
        _run(["uv", "run", "alembic", "upgrade", "head"], base)
        _run(["uv", "run", "arkhe", "naan", "add", NAAN, "E2E RA",
              "--policy", "NP | NR, OP, CC | 2026"], base)
        _run(["uv", "run", "arkhe", "onboard", NAAN, "E2E org", "-s", SHOULDER], base)
        # **組織に結び付けずに作った主体は採番できない**（ARKHE-1303）。id は
        # `manager list` の 1 列目——CLI がそう言っているとおりに読む。
        listing = _run(["uv", "run", "arkhe", "manager", "list"], base)
        manager_id = next(ln.split()[0] for ln in listing.splitlines() if "E2E org" in ln)
        _run(["uv", "run", "arkhe", "client", "add", "e2e-client", NAAN,
              "--manager", manager_id, "--scopes", "ark:mint ark:update ark:read"], base)
        # **鍵は刷った 1 度しか出ない。** 1 行目がその平文。
        key = _run(["uv", "run", "arkhe", "client", "key", "e2e-client"], base).splitlines()[0]
        assert key.startswith("arkhe_"), key

        minter = _serve(base, logs / "minter.log", "minter")
        servers.append(minter)
        resolver = _serve(
            {**base, "ARKHE_RESOLVER": "1",
             "ARKHE_DATABASE_URL": _BOGUS, "ARKHE_READ_DATABASE_URL": url},
            logs / "resolver.log", "resolver",
        )
        servers.append(resolver)
        yield World(minter, resolver, key)
    finally:
        for s in servers:
            s.proc.terminate()
            try:
                s.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                s.proc.kill()
        subprocess.run(["docker", "rm", "-f", PG_NAME], capture_output=True)


@pytest.fixture(scope="module")
def minted(world: World) -> dict:
    """1 本採って、以降の検査で使い回す。**採番は取り消せない**ので増やさない。"""
    r = httpx.post(
        f"{world.minter.url}/api/mint",
        headers={"Authorization": f"Bearer {world.key}"},
        json={"url": TARGET, "title": "E2E", "request_id": "e2e-1"},
        timeout=30,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_採番できる(minted):
    assert minted["ark"].startswith(f"ark:{NAAN}/{SHOULDER.lstrip('/')}")
    assert minted["url"] == TARGET
    assert minted["published_at"]


def test_同じ_request_id_の再送では番号が増えない(world: World, minted):
    r = httpx.post(
        f"{world.minter.url}/api/mint",
        headers={"Authorization": f"Bearer {world.key}"},
        json={"url": TARGET, "request_id": "e2e-1"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    assert r.json()["ark"] == minted["ark"]


def test_鍵が無ければ採番できない(world: World):
    r = httpx.post(f"{world.minter.url}/api/mint", json={"url": TARGET}, timeout=30)
    assert r.status_code == 401


def test_resolver_で解決できる(world: World, minted):
    r = httpx.get(f"{world.resolver.url}/{minted['ark']}", follow_redirects=False, timeout=30)
    assert r.status_code == 302
    assert r.headers["location"] == TARGET


def test_修飾子は継承して転送される(world: World, minted):
    """A1: 登録されていない修飾子は、**祖先の行き先に継いで**送る。"""
    r = httpx.get(
        f"{world.resolver.url}/{minted['ark']}/page1", follow_redirects=False, timeout=30
    )
    assert r.status_code == 302
    assert r.headers["location"].startswith(TARGET)
    assert r.headers["location"].endswith("/page1")


def test_info_は認証なしで読める(world: World, minted):
    r = httpx.get(f"{world.resolver.url}/{minted['ark']}?info", timeout=30)
    assert r.status_code == 200
    assert minted["ark"].split(":")[1] in r.text
    assert TARGET in r.text


def test_知らない名前は404(world: World):
    r = httpx.get(
        f"{world.resolver.url}/ark:{NAAN}/e1zzzzzzzzz", follow_redirects=False, timeout=30
    )
    assert r.status_code == 404


def test_resolver_に採番の口は無い(world: World):
    r = httpx.post(
        f"{world.resolver.url}/api/mint",
        headers={"Authorization": f"Bearer {world.key}"},
        json={"url": TARGET}, timeout=30,
    )
    assert r.status_code == 404, "**resolver が採番を受けた。** 役割が分かれていない"


def test_resolver_に管理画面は無い(world: World):
    assert httpx.get(f"{world.resolver.url}/admin/", timeout=30).status_code == 404
    # minter には在る（認証は要る——何が返るかではなく、**口が在ること**を見る）
    assert httpx.get(
        f"{world.minter.url}/admin/", follow_redirects=False, timeout=30
    ).status_code != 404


def test_minter_に解決の口は無い(world: World, minted):
    r = httpx.get(f"{world.minter.url}/{minted['ark']}", follow_redirects=False, timeout=30)
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


def test_台帳を数えられる(world: World, minted):
    r = httpx.get(
        f"{world.minter.url}/api/stats",
        headers={"Authorization": f"Bearer {world.key}"}, timeout=30,
    )
    assert r.status_code == 200, r.text
    assert r.json()["arks"] >= 1
