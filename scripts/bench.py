#!/usr/bin/env python
"""bench.py — 一本の口に負荷をかけて、rps と遅延の分布を出す。

**検査ではない。** `check.sh` からは呼ばない——時間がかかるうえ、結果が機械と
その日の負荷に左右されるので、緑/赤で語れるものではない。**自分の環境で自分の
数字を取る**ための道具である。

    python scripts/bench.py http://127.0.0.1:8000/ark:99999/x9abc -n 3000 -c 8
    python scripts/bench.py http://127.0.0.1:8000/api/mint -n 200 -c 4 \\
        --post --auth "$ARKHE_KEY"

読むときの約束が 2 つある。

**① クライアントが先に飽和していないか確かめる。** この道具はスレッドを並べて
同期 HTTP を投げるだけなので、サーバより先にこちら側が詰まる。`/healthz`（DB も
認証も通らない口）を同じ条件で測り、**その値に近づいていたら測っているのは
クライアント**である。

**② 同じ機械に置かない構成なら、必ず取り直す。** 往復にネットワークが入ると
分布の形が変わる。ここで出る数字は「この機械では」以上のことを言わない。
"""

from __future__ import annotations

import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import httpx


def _worker(url: str, count: int, method: str, body, headers) -> list[tuple[float, int]]:
    """1 スレッド分。**接続は使い回す**——毎回張り直すと TCP の分を測ってしまう。"""
    out: list[tuple[float, int]] = []
    with httpx.Client(follow_redirects=False, timeout=30, headers=headers or {}) as client:
        for _ in range(count):
            started = time.perf_counter()
            response = client.request(method, url, json=body)
            out.append((time.perf_counter() - started, response.status_code))
    return out


def run(url: str, n: int, concurrency: int, *, method="GET", body=None, headers=None) -> dict:
    # **温める。** 最初の 1 回はクエリの計画や接続の確立を含み、桁が違う
    # （実測で 20 ms 対 0.03 ms）。それを分布に混ぜると中央値まで濁る。
    _worker(url, 1, method, body, headers)

    per = max(1, n // concurrency)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        batches = pool.map(lambda c: _worker(url, c, method, body, headers), [per] * concurrency)
        samples = [s for batch in batches for s in batch]
    wall = time.perf_counter() - started

    latencies = sorted(d for d, _ in samples)
    codes: dict[int, int] = {}
    for _, code in samples:
        codes[code] = codes.get(code, 0) + 1
    return {
        "n": len(latencies),
        "conc": concurrency,
        "rps": len(latencies) / wall,
        "p50": statistics.median(latencies) * 1000,
        "p95": latencies[int(len(latencies) * 0.95)] * 1000,
        "p99": latencies[int(len(latencies) * 0.99)] * 1000,
        "codes": codes,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url")
    ap.add_argument("-n", type=int, default=2000, help="要求の総数")
    ap.add_argument("-c", type=int, default=8, help="同時数")
    ap.add_argument("--post", action="store_true", help="空の JSON を POST する")
    ap.add_argument("--auth", default="", help="Bearer トークン / API キー")
    ap.add_argument("--label", default="", help="行の見出し")
    args = ap.parse_args()

    headers = {"Authorization": f"Bearer {args.auth}"} if args.auth else None
    r = run(
        args.url, args.n, args.c,
        method="POST" if args.post else "GET",
        body={} if args.post else None,
        headers=headers,
    )
    label = args.label or args.url
    print(
        f"{label:34} c={r['conc']:>3}  {r['rps']:>8.1f} rps   "
        f"p50 {r['p50']:>7.2f}  p95 {r['p95']:>7.2f}  p99 {r['p99']:>7.2f} ms   {r['codes']}"
    )


if __name__ == "__main__":
    main()
