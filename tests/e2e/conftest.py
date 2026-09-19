"""Fixtures for the end-to-end suite. Everything is started once, per session.

What is started:

  PostgreSQL   a throwaway container. The rest of the suite uses SQLite, so dialect
               differences only show up here
  minter       minting, the admin interface and /oauth/token, with real authentication
  resolver     resolution only. Its write URL points nowhere (see _BOGUS)

The ledger is built by scripts/seed_e2e.py, which goes through the CLI. The setup is not
repeated here: checking by hand should start from the same ledger, and code written in
two places drifts apart. See the top of that script for what the ledger contains.

Each principal has one purpose. If they shared one, the check that disables a principal
would break the checks that run after it.
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

#: How many ARKs to seed. What matters is the mix of states, not the number, so a small
#: number is enough. The seeder reserves every tenth one.
SEEDED_ARKS = 12

#: A NAAN that is not in the ledger. The seeder does not create it, so it lives here.
UNKNOWN_NAAN = "12345"
GLOBAL_RESOLVER = "https://n2t.example.net"

SESSION_SECRET = "e2e-session-secret-0123456789abcdef"
TOKEN_SECRET = "e2e-token-secret-0123456789abcdef"

#: The resolver's write URL points nowhere; its read URL points at the real database.
#: If the resolver touches the write side, this suite fails. /readyz did until 0.11.0.
_BOGUS = "postgresql+psycopg://arkhe:arkhe@127.0.0.1:1/arkhe"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_cli(args: list[str], env: dict[str, str]) -> str:
    """Run a command and show its output if it fails."""
    p = subprocess.run(
        args, cwd=ROOT, env={**os.environ, **env}, capture_output=True, text=True
    )
    if p.returncode != 0:
        raise AssertionError(f"{' '.join(args)} failed\n{p.stdout}\n{p.stderr}")
    return p.stdout


@dataclass
class Server:
    proc: subprocess.Popen
    url: str
    log: Path

    def tail(self) -> str:
        return self.log.read_text(errors="replace")[-4000:]


def serve(env: dict[str, str], log: Path, label: str, *, workers: int = 1) -> Server:
    """Start one server with uvicorn and wait until /healthz answers.

    More workers means more processes, as in production. With a single worker the Python
    side serialises, and a race between processes cannot be reproduced.
    """
    port = free_port()
    handle = log.open("w")
    proc = subprocess.Popen(
        # --factory matters: without it the process dies with
        # 'Attribute "app" not found'.
        ["uv", "run", "uvicorn", "arkhe.app:create_app", "--factory",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
         "--workers", str(workers)],
        cwd=ROOT, env={**os.environ, **env}, stdout=handle, stderr=subprocess.STDOUT,
    )
    server = Server(proc, f"http://127.0.0.1:{port}", log)
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"{label} exited instead of starting\n{server.tail()}")
        try:
            if httpx.get(f"{server.url}/healthz", timeout=1).status_code == 200:
                return server
        except httpx.HTTPError:
            time.sleep(0.3)
    proc.kill()
    raise AssertionError(f"{label} did not answer within 60 seconds\n{server.tail()}")


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
    #: What scripts/seed_e2e.py --json returned. That script decides the shape.
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
        """Call the minter. key=None sends no credentials."""
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
    """Build the ledger with scripts/seed_e2e.py.

    --arks also seeds ARKs in mixed states: published, reserved, held, tombstoned,
    qualified and withdrawn. A ledger where everything is published says nothing about
    how the screens or the statistics behave.
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
        pytest.skip("no docker, so the end-to-end suite did not run")
    if not shutil.which("uv"):
        pytest.skip("no uv, so the end-to-end suite did not run")

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
            raise AssertionError("PostgreSQL never came up")

        url = f"postgresql+psycopg://arkhe:arkhe@127.0.0.1:{port}/arkhe"
        env = {"ARKHE_DATABASE_URL": url, "ARKHE_AUTH": "apikey", "ARKHE_RESOLVER": "0"}
        seed = _bootstrap(env)

        minter = serve(
            {**env,
             # Open every door. Signing in with a key, taking a token and entering the
             # admin interface with a password can only be exercised once assembled.
             "ARKHE_AUTH": "apikey,oauth2",
             "ARKHE_TOKEN_SECRET": TOKEN_SECRET,
             "ARKHE_ADMIN_LOGIN": "password",
             "ARKHE_SESSION_SECRET": SESSION_SECRET,
             "ARKHE_SESSION_SECURE": "false",  # plain HTTP here; true in production
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
    """Mint one ARK. Minting cannot be undone, so only call it when needed."""

    def go(*, key: str = "ops", **fields) -> dict:
        r = world.api("post", "/api/mint", key=key, json=fields)
        assert r.status_code in (200, 201), r.text
        return r.json()

    return go


@pytest.fixture(scope="session")
def published(mint) -> dict:
    """One published ARK, shared by the read-only checks. Do not change its state."""
    return mint(url="https://example.org/e2e/object", title="E2E", request_id="e2e-shared")
