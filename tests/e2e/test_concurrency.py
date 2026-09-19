"""**同時に来たとき**にどうなるか。SQLite の単体試験では出ない。

ここで見る競り合いは、実際に起きたもの——`request_id` を揃えた再送を 200 件
同時に投げて、**102 件が 500 を返した**。同じ鍵で INSERT が競り、後から来た側が
`IntegrityError` で落ちていた。直した今は、**負けた側が勝った側の結果を返す。**
"""

from __future__ import annotations

import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import urlsplit

import pytest

from tests.e2e.conftest import serve, stop

pytestmark = pytest.mark.e2e

#: **同時に投げないと、この競りは起きない。** 順に投げれば 2 本目は再送の判定で
#: 弾かれ、書き込みまで進まない——揃えて撃つために関所を置く。
RACERS = 32
#: **本番と同じく、プロセスを並べる。** 1 つだと Python の側が直列になり、
#: `_replay` を見てから commit するまでの隙が**別の要求と重ならない**
#: ——実際、1 worker では直しを外しても落ちなかった。
WORKERS = 4


@pytest.fixture(scope="module")
def racing(world, tmp_path_factory):
    """worker を並べた minter。**競りはここでしか出ない。**"""
    logs = tmp_path_factory.mktemp("e2e-race")
    minter = serve(
        {**world.env, "ARKHE_AUTH": "apikey,oauth2",
         "ARKHE_TOKEN_SECRET": "e2e-token-secret-0123456789abcdef"},
        logs / "racing.log", "racing minter", workers=WORKERS,
    )
    yield replace(world, minter=minter)
    stop(minter)


def _fire_together(url: str, token: str, body: dict, count: int) -> list[tuple[int, dict]]:
    """**同じ要求を、本当に同時に投げる。**

    `httpx` で投げると、接続も組み立ても要求ごとに起きる。それだけで数 ms 散らばり、
    **先頭が commit し終えてから次が `_replay` を見る**ので競りにならない
    ——実際、これを直す前は、直しを外しても落ちなかった。

    そこで**接続まで先に済ませ**、関所で揃えて、あとは組み立て済みの
    バイト列を流すだけにする。
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


def test_同じ_request_id_を同時に投げても番号は1つ(racing):
    """F4 を**競り合いの下で**。201 は 1 つだけ、残りは 200 で同じ ARK。

    実際に壊れていた形である: `request_id` を揃えた再送を同時に投げると、
    **どれも「まだ無い」と見てから、どれも書きにいく**。台帳は DB の一意制約で
    守られるが、**負けたほうには `500` が返っていた**（200 件中 102 件）。

    **ただし、この検査はその競りを再現していない。** 測って分かったことを残す:

      送信の散らばり  1.3 ms（32 本を、接続を済ませてから関所で揃えて撃った）
      1 件の所要      中央値 170 ms、全体 194 ms
      結果            201 が 1 件、残り 31 件は 200。**衝突は 1 度も起きない**

    要求は確かに同時に届いている。それでも競らないのは、**先頭が commit し
    終えるまでに、後続が `_replay` まで到達しないから**である（worker 4 つでも
    同じ）。実際、`_commit_or_replay` の直しを外しても**この検査は落ちない**
    ——**競りの守りの検査として読んではいけない。**

    ここが守っているのは、**同時に投げても番号は 1 つ**という約束のほうである。
    再送に同じ答えを返すという約束は、順次でも同時でも同じでなければならない。

    **鍵ではなくトークンで撃つ。** API 鍵の検証は Argon2 で 1 件 50 ms ほどかかり、
    そこが順番待ちになる。JWT の検証は署名 1 回である。
    """
    token = racing.api("post", "/oauth/token", key=None, data={
        "grant_type": "client_credentials", "client_id": "e2e-secret",
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
    assert not [c for c in codes if c >= 400], f"**落ちた要求がある**: {sorted(codes)}"
    assert codes.count(201) == 1, f"201 が {codes.count(201)} 件——番号が増えている"
    assert len(arks) == 1, f"**別の番号が採られた**: {arks}"


def test_同時に採っても名前は衝突しない(racing):
    """E1: **既存 ARK を黙って上書きしない。** 32 本を同時に採って、全部別物か。"""
    def send(i: int):
        r = racing.api("post", "/api/mint", json={"url": f"https://example.org/e2e/par/{i}"})
        assert r.status_code == 201, r.text
        return r.json()["ark"]

    with ThreadPoolExecutor(max_workers=16) as pool:
        arks = list(pool.map(send, range(32)))

    assert len(set(arks)) == 32, "**同じ名前が 2 度採られた**"
    # 採った全部が、別プロセスの resolver から引ける
    assert racing.resolve(arks[0]).status_code == 302
    assert racing.resolve(arks[-1]).status_code == 302


def test_同時に取り下げても壊れない(racing, mint):
    """**同じ行を同時に触る。** どれかは通り、どれも 500 にはならない。"""
    ark = mint(url="https://example.org/e2e/concurrent-unpublish")["ark"]

    def send(_: int):
        return racing.api("post", "/api/unpublish", json={
            "ark": ark, "reason": "同時に取り下げる", "confirm": ark
        }).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(send, range(8)))

    assert 200 in codes, codes
    assert not [c for c in codes if c >= 500], f"**500 を返した**: {codes}"
    assert racing.resolve(ark).status_code == 404
