"""What happens when requests arrive together. SQLite unit tests cannot show this.

The race these checks describe did happen: 200 resends that shared one request_id
returned 500 for 102 of them, because the inserts collided and the losing side raised
IntegrityError. Today the losing side returns what the winner wrote.
"""

from __future__ import annotations

import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import urlsplit

import pytest

from tests.e2e.conftest import TOKEN_SECRET, serve, stop

pytestmark = pytest.mark.e2e

RACERS = 32
#: Run several processes, as in production. With one worker the Python side serialises,
#: so the gap between reading the receipt and committing never overlaps another request.
WORKERS = 4


@pytest.fixture(scope="module")
def racing(world, tmp_path_factory):
    """A minter with several workers."""
    logs = tmp_path_factory.mktemp("e2e-race")
    minter = serve(
        {**world.env, "ARKHE_AUTH": "apikey,oauth2", "ARKHE_TOKEN_SECRET": TOKEN_SECRET},
        logs / "racing.log", "racing minter", workers=WORKERS,
    )
    yield replace(world, minter=minter)
    stop(minter)


def _fire_together(url: str, token: str, body: dict, count: int) -> list[tuple[int, dict]]:
    """Send the same request from many sockets at the same moment.

    Sending with httpx would open a connection and build a request per call, which
    spreads the sends over several milliseconds. The connections are therefore opened
    first, and after the barrier each thread only writes bytes that are ready.
    """
    host, port = urlsplit(url).hostname, urlsplit(url).port
    payload = json.dumps(body).encode()
    head = (
        f"POST /api/mint HTTP/1.1\r\nHost: {host}\r\n"
        f"Authorization: Bearer {token}\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n"
    ).encode()
    socks = [socket.create_connection((host, port), timeout=30) for _ in range(count)]
    gate = threading.Barrier(count)
    out: list[tuple[int, dict]] = []
    lock = threading.Lock()

    def fire(sock: socket.socket) -> None:
        gate.wait()
        sock.sendall(head + payload)
        chunks = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
        sock.close()
        raw = b"".join(chunks)
        status = int(raw.split(b" ", 2)[1])
        received = json.loads(raw.split(b"\r\n\r\n", 1)[1] or b"{}")
        with lock:
            out.append((status, received))

    threads = [threading.Thread(target=fire, args=(s,)) for s in socks]
    for th in threads:
        th.start()
    for th in threads:
        th.join(60)
    return out


def test_one_request_id_sent_together_mints_one_ark(racing):
    """F4 under contention: exactly one 201, and every other answer is the same ARK.

    Note what this check does not do. Even sending 32 resends from pre-opened sockets,
    with 1.3 ms between the first and last send and 170 ms per request, the race inside
    _commit_or_replay never opens: the first request commits before any other reaches
    the receipt lookup, with four workers as well. Reverting that fix does not make this
    check fail, so do not read it as the guard for it.

    What it does guard is the promise itself: resends get one ARK, in sequence or all at
    once.

    A token is used rather than an API key. Verifying an API key costs about 50 ms of
    Argon2, and the requests queue up behind it; verifying a JWT is one signature check.
    """
    token = racing.api("post", "/oauth/token", key=None, data={
        "grant_type": "client_credentials",
        "client_id": racing.seed["clients"]["secret"],
        "client_secret": racing.keys["secret"], "scope": "ark:mint",
    }).json()["access_token"]

    results = _fire_together(
        racing.minter.url, token,
        {"url": "https://example.org/e2e/race", "request_id": "e2e-race"},
        RACERS,
    )
    assert len(results) == RACERS
    codes = [c for c, _ in results]
    arks = {b.get("ark") for _, b in results}
    assert not [c for c in codes if c >= 400], f"some requests failed: {sorted(codes)}"
    assert codes.count(201) == 1, f"{codes.count(201)} requests minted, expected 1"
    assert len(arks) == 1, f"more than one ARK was minted: {arks}"


def test_names_do_not_collide_when_minted_together(racing):
    """E1: an existing ARK is never overwritten. Mint 32 at once and check they differ."""
    def send(i: int):
        r = racing.api("post", "/api/mint", json={"url": f"https://example.org/e2e/par/{i}"})
        assert r.status_code == 201, r.text
        return r.json()["ark"]

    with ThreadPoolExecutor(max_workers=16) as pool:
        arks = list(pool.map(send, range(32)))

    assert len(set(arks)) == 32, "the same name was minted twice"
    # Everything minted is visible to the resolver process
    assert racing.resolve(arks[0]).status_code == 302
    assert racing.resolve(arks[-1]).status_code == 302


def test_withdrawing_the_same_ark_together_does_not_break(racing, mint):
    """Touch one row from several requests at once: one succeeds, none return 500."""
    ark = mint(url="https://example.org/e2e/concurrent-unpublish")["ark"]

    def send(_: int):
        return racing.api("post", "/api/unpublish", json={
            "ark": ark, "reason": "withdrawn concurrently", "confirm": ark
        }).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(send, range(8)))

    assert 200 in codes, codes
    assert not [c for c in codes if c >= 500], f"a request returned 500: {codes}"
    assert racing.resolve(ark).status_code == 404
