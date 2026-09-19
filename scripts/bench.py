#!/usr/bin/env python
"""Load one endpoint and report requests per second and the latency spread.

This is not a check. check.sh does not call it: it takes a while, and the numbers depend
on the machine and on what else is running, so they cannot be read as pass or fail. It is
a tool for taking your own numbers on your own machine.

    python scripts/bench.py http://127.0.0.1:8000/ark:99999/x9abc -n 3000 -c 8
    python scripts/bench.py http://127.0.0.1:8000/api/mint -n 200 -c 4 \\
        --post --auth "$ARKHE_KEY"

Two things to keep in mind when reading the output.

First, check that the client is not the bottleneck. This tool runs threads that send
synchronous HTTP, so it saturates before the server does. Measure /healthz, which touches
neither the database nor authentication, under the same settings: if your figure is close
to that one, you are measuring the client.

Second, measure again for any layout that is not on a single machine. A network round
trip changes the shape of the distribution. These numbers say nothing beyond "on this
machine".
"""

from __future__ import annotations

import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import httpx


def _worker(url: str, count: int, method: str, body, headers) -> list[tuple[float, int]]:
    """One thread's share. The connection is reused; reopening it would measure TCP."""
    out: list[tuple[float, int]] = []
    with httpx.Client(follow_redirects=False, timeout=30, headers=headers or {}) as client:
        for _ in range(count):
            started = time.perf_counter()
            response = client.request(method, url, json=body)
            out.append((time.perf_counter() - started, response.status_code))
    return out


def run(url: str, n: int, concurrency: int, *, method="GET", body=None, headers=None) -> dict:
    # Warm up. The first request includes query planning and opening the connection,
    # and is an order of magnitude slower (20 ms against 0.03 ms here). Leaving it in
    # the sample would move even the median.
    _worker(url, 1, method, body, headers)

    # Spread the remainder. Truncating with n // concurrency would send 2992 requests
    # for -n 3000 -c 16, and anyone comparing the status counts against -n reads that as
    # eight lost requests. Send exactly as many as were asked for.
    per = [n // concurrency + (1 if i < n % concurrency else 0) for i in range(concurrency)]
    per = [max(1, c) for c in per]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        batches = pool.map(lambda c: _worker(url, c, method, body, headers), per)
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
    ap.add_argument("-n", type=int, default=2000, help="how many requests in total")
    ap.add_argument("-c", type=int, default=8, help="how many at a time")
    ap.add_argument("--post", action="store_true", help="POST an empty JSON body")
    ap.add_argument("--auth", default="", help="bearer token or API key")
    ap.add_argument("--label", default="", help="label for the output line")
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
