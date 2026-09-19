"""通しの検査の土台。**建てるのは 1 度きり**（session 単位）。

ここで建てるもの:

  PostgreSQL   docker の使い捨て。**ほかの試験は SQLite** なので、方言の差はここでしか出ない
  minter       採番・管理画面・`/oauth/token`。**認証は本物**（apikey と client_credentials）
  resolver     解決だけ。**書き込み側はどこにも繋がらない先に向けてある**（`_BOGUS`）

台帳は **`scripts/seed_e2e.py` が組む**（あちらは CLI を通す——運用で実際に使う道で
なければ検査にならない。**この形で ARKHE-1303 を踏んだ**）。**検査の側に同じ組み立てを
書かない**: 手で確かめるときも同じ台帳から始めたいし、2 か所に書けば片方が古くなる。

どんな台帳かは `scripts/seed_e2e.py` の冒頭にある。ここで押さえておくのは 1 点
——**主体は用途ごとに分けてある**。1 つを使い回すと、止める検査が後続を巻き添えにする。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
PG_NAME = "arkhe-e2e-pg"

#: 種として入れる ARK の本数。**状態が混ざっていることに意味がある**ので、
#: 数は少なくてよい（種蒔きの側が 10 本に 1 本を公開前にする）。
SEEDED_ARKS = 12

#: **誰も知らない NAAN。** 種を蒔く側は知らないので、こちらに置く。
UNKNOWN_NAAN = "12345"
GLOBAL_RESOLVER = "https://n2t.example.net"

SESSION_SECRET = "e2e-session-secret-0123456789abcdef"
TOKEN_SECRET = "e2e-token-secret-0123456789abcdef"

#: resolver の**書き込み側を、どこにも繋がらない先に向ける**。読みは本物に向ける。
#: resolver が解決や `/readyz` で書き込み側を触ったら、**検査が落ちる**——実際
#: `/readyz` は 0.11.0 まで触っていた。
_BOGUS = "postgresql+psycopg://arkhe:arkhe@127.0.0.1:1/arkhe"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_cli(args: list[str], env: dict[str, str]) -> str:
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


def serve(env: dict[str, str], log: Path, label: str, *, workers: int = 1) -> Server:
    """`uvicorn` で 1 つ建てて、`/healthz` が返るまで待つ。

    **`workers` を増やすと、本番と同じく別プロセスが並ぶ。** 1 つのままだと
    Python の側が直列になり、**プロセスをまたぐ競りが再現しない**。
    """
    port = free_port()
    handle = log.open("w")
    proc = subprocess.Popen(
        # **`--factory`。** ここを落とすと "Attribute \"app\" not found" で死ぬ。
        ["uv", "run", "uvicorn", "arkhe.app:create_app", "--factory",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
         "--workers", str(workers)],
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


def stop(server: Server) -> None:
    server.proc.terminate()
    try:
        server.proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.proc.kill()


@dataclass
class World:
    minter: Server
    resolver: Server
    env: dict[str, str]
    #: `scripts/seed_e2e.py --json` が返したもの。**台帳の形はあちらが決める。**
    seed: dict = field(default_factory=dict)

    @property
    def keys(self) -> dict[str, str]:
        return self.seed["keys"]

    @property
    def naan(self) -> str:
        return self.seed["naan"]

    @property
    def shoulder(self) -> str:
        return self.seed["shoulders"]["a"]

    @property
    def delegated_naan(self) -> str:
        return self.seed["delegated_naan"]

    @property
    def delegate(self) -> str:
        return self.seed["delegate"]

    @property
    def admin(self) -> dict[str, str]:
        return self.seed["admin"]

    def api(self, method: str, path: str, *, key: str | None = "ops", **kw) -> httpx.Response:
        """minter を叩く。`key=None` なら**資格情報を付けない**。"""
        headers = dict(kw.pop("headers", {}))
        if key is not None:
            headers["Authorization"] = f"Bearer {self.keys[key] if key in self.keys else key}"
        return httpx.request(
            method, f"{self.minter.url}{path}", headers=headers, timeout=30, **kw
        )

    def resolve(self, ark: str, suffix: str = "", **kw) -> httpx.Response:
        return httpx.get(
            f"{self.resolver.url}/{ark}{suffix}", follow_redirects=False, timeout=30, **kw
        )

    def cli(self, *args: str) -> str:
        return run_cli(["uv", "run", "arkhe", *args], self.env)


def _bootstrap(env: dict[str, str]) -> dict:
    """台帳を **`scripts/seed_e2e.py` で**組む。

    **検査の側に同じ組み立てを書かない。** 手で確かめるときも同じ台帳から始めたいし、
    2 か所に書けば片方が必ず古くなる。**呼んでいるから、あちらも腐らない。**

    `--arks` で状態の混ざった ARK も入れる——公開・公開前・保留・墓碑・修飾子つき・
    取り下げ済み。**全部が公開済みの台帳では、画面も統計も確かめられない。**
    """
    out = run_cli(
        ["uv", "run", "python", "scripts/seed_e2e.py", "--migrate", "--json",
         "--arks", str(SEEDED_ARKS)],
        env,
    )
    return json.loads(out.splitlines()[-1])


@pytest.fixture(scope="session")
def world(tmp_path_factory) -> World:
    if not shutil.which("docker"):
        pytest.skip("docker が無い。**通しの検査を通していない**")
    if not shutil.which("uv"):
        pytest.skip("uv が無い。**通しの検査を通していない**")

    logs = tmp_path_factory.mktemp("e2e")
    port = free_port()
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
        env = {"ARKHE_DATABASE_URL": url, "ARKHE_AUTH": "apikey", "ARKHE_RESOLVER": "0"}
        seed = _bootstrap(env)

        minter = serve(
            {**env,
             # **口を全部開けて建てる。** 鍵で入る道・トークンを取る道・合言葉で
             # 画面に入る道は、どれも組み上がってからでないと通せない。
             "ARKHE_AUTH": "apikey,oauth2",
             "ARKHE_TOKEN_SECRET": TOKEN_SECRET,
             "ARKHE_ADMIN_LOGIN": "password",
             "ARKHE_SESSION_SECRET": SESSION_SECRET,
             "ARKHE_SESSION_SECURE": "false",  # 検査は平文 HTTP。**本番は true**
             "ARKHE_GLOBAL_RESOLVER": GLOBAL_RESOLVER},
            logs / "minter.log", "minter",
        )
        servers.append(minter)
        resolver = serve(
            {**env, "ARKHE_RESOLVER": "1",
             "ARKHE_DATABASE_URL": _BOGUS, "ARKHE_READ_DATABASE_URL": url,
             "ARKHE_GLOBAL_RESOLVER": GLOBAL_RESOLVER},
            logs / "resolver.log", "resolver",
        )
        servers.append(resolver)
        yield World(minter, resolver, env, seed)
    finally:
        for s in servers:
            stop(s)
        subprocess.run(["docker", "rm", "-f", PG_NAME], capture_output=True)


@pytest.fixture(scope="session")
def mint(world: World):
    """1 本採る。**採番は取り消せない**ので、要るときだけ呼ぶ。"""

    def go(*, key: str = "ops", **fields) -> dict:
        r = world.api("post", "/api/mint", key=key, json=fields)
        assert r.status_code in (200, 201), r.text
        return r.json()

    return go


@pytest.fixture(scope="session")
def published(mint) -> dict:
    """公開済みの ARK 1 本。**読むだけの検査で使い回す**（状態を変えないこと）。"""
    return mint(url="https://example.org/e2e/object", title="E2E", request_id="e2e-shared")
