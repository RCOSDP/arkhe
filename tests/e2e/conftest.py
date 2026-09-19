"""通しの検査の土台。**建てるのは 1 度きり**（session 単位）。

ここで建てるもの:

  PostgreSQL   docker の使い捨て。**ほかの試験は SQLite** なので、方言の差はここでしか出ない
  minter       採番・管理画面・`/oauth/token`。**認証は本物**（apikey と client_credentials）
  resolver     解決だけ。**書き込み側はどこにも繋がらない先に向けてある**（`_BOGUS`）

台帳は **CLI で組む**。API や ORM で組むと、運用で実際に使う道の検査にならない
——**この形で ARKHE-1303（組織に結び付けない主体は採番できない）を踏んだ。**

**主体は用途ごとに分ける。** 1 つを使い回すと、止める検査が後続を巻き添えにする。
"""

from __future__ import annotations

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

NAAN = "99999"
#: 採番を外に委ねた NAAN。**解決はここへ送る**（D2）。
DELEGATED_NAAN = "88888"
DELEGATE = "https://delegate.example.org"
#: 誰も知らない NAAN。**全体リゾルバへ送る**（D2）。
UNKNOWN_NAAN = "12345"
GLOBAL_RESOLVER = "https://n2t.example.net"

SHOULDER = "/e1"
OTHER_SHOULDER = "/b2"
QUOTA_SHOULDER = "/q1"

ADMIN_USER = "e2e-person"
ADMIN_PASSWORD = "correct horse battery staple"
SESSION_SECRET = "e2e-session-secret-0123456789abcdef"
TOKEN_SECRET = "e2e-token-secret-0123456789abcdef"

ALL_SCOPES = (
    "ark:mint ark:update ark:read ark:tombstone ark:hold ark:import "
    "ark:delete ark:unpublish ark:purge"
)

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
    keys: dict[str, str] = field(default_factory=dict)
    managers: dict[str, str] = field(default_factory=dict)

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


def _bootstrap(env: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """台帳を **CLI で**組む。返すのは (鍵, 組織 id)。"""
    run_cli(["uv", "run", "alembic", "upgrade", "head"], env)
    cli = lambda *a: run_cli(["uv", "run", "arkhe", *a], env)  # noqa: E731

    cli("naan", "add", NAAN, "E2E RA", "--policy", "NP | NR, OP, CC | 2026")
    # **採番も解決も外に委ねた NAAN。** 台帳に行は無く、解決はここへ送る。
    cli("naan", "add", DELEGATED_NAAN, "E2E 委譲先", "--no-authoritative",
        "--redirect", DELEGATE)

    cli("onboard", NAAN, "E2E org", "-s", SHOULDER)
    cli("onboard", NAAN, "E2E 別組織", "-s", OTHER_SHOULDER)
    cli("onboard", NAAN, "E2E 上限組織", "-s", QUOTA_SHOULDER, "--quota", "1")

    # id は `manager list` の 1 列目——CLI が「ids are input to other commands」と
    # 言っているとおりに読む。
    listing = cli("manager", "list")
    managers = {}
    for line in listing.splitlines():
        for tag, name in (("a", "E2E org"), ("b", "E2E 別組織"), ("q", "E2E 上限組織")):
            if line.rstrip().endswith(name):
                managers[tag] = line.split()[0]
    assert set(managers) == {"a", "b", "q"}, listing

    keys = {}
    # **用途ごとに分ける。** `stop` は途中で止める、`quota` は 1 日 1 本しか採れない。
    for tag, client_id, manager, scopes in (
        ("ops", "e2e-ops", "a", ALL_SCOPES),
        ("mint_only", "e2e-mint-only", "a", "ark:mint"),
        ("other", "e2e-other", "b", "ark:mint ark:update ark:read"),
        ("quota", "e2e-quota", "q", "ark:mint"),
        ("stop", "e2e-stop", "a", "ark:mint ark:read"),
    ):
        cli("client", "add", client_id, NAAN, "--manager", managers[manager],
            "--scopes", scopes)
        # **鍵は刷った 1 度しか出ない。** 1 行目がその平文。
        keys[tag] = cli("client", "key", client_id).splitlines()[0]
        assert keys[tag].startswith("arkhe_"), keys[tag]

    # client_credentials 用。**平文は `arkhes_` で始まる別の種類。**
    cli("client", "add", "e2e-secret", NAAN, "--manager", managers["a"],
        "--scopes", "ark:mint ark:read")
    keys["secret"] = cli("client", "key", "e2e-secret", "--kind", "client_secret").splitlines()[0]

    # 管理画面に入る人。**人は資格情報を持たない**——合言葉だけ。
    cli("client", "add", ADMIN_USER, NAAN, "--person", "--authority", "naan",
        "--scopes", ALL_SCOPES)
    cli("client", "passwd", ADMIN_USER, "--password", ADMIN_PASSWORD)
    return keys, managers


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
        keys, managers = _bootstrap(env)

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
        yield World(minter, resolver, env, keys, managers)
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
