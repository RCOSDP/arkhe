"""T6: 採番の応答時間がクライアント数に依存しないこと。

arklet は 800 本で 31〜32 秒＝gunicorn の既定 30 秒を超えて**失敗**していた。
DOT の `AccessToken.token_checksum`（unique 索引）で定数時間になるはず。

実行: `.venv/bin/python -m pytest tests/perf_t6.py -q -s`
"""

from __future__ import annotations

import json
import statistics
import time

import pytest
from django.conf import settings
from django.test import Client as HttpClient

from jc2ark.ark.models import Client, Manager, Naan, Shoulder
from jc2ark.arkspec.betanumeric import CONSONANTS

pytestmark = pytest.mark.django_db
SECRET = "perf-secret-value"


def _timed(fn, reps=9):
    xs = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t0) * 1000)
    xs.sort()
    return statistics.median(xs), xs[int(len(xs) * 0.95) - 1]


def test_t6_mint_latency_is_independent_of_client_count(capsys):
    http = HttpClient()
    naan = Naan.objects.create(naan="99999", name="JC2")
    real_hashers = list(settings.PASSWORD_HASHERS)

    def add(k, start):
        # 大量作成だけ高速ハッシャで行う（測る対象はトークン検証であって
        # client_secret のハッシュではない）。
        settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
        last = None
        for i in range(start, start + k):
            m = Manager.objects.create(naan=naan, name=f"機関{i:04d}")
            # 性能測定なので shoulder は決定的に振る（不透明性は本筋でない）。
            sh = f"/{CONSONANTS[i % 19]}{CONSONANTS[(i // 19) % 19]}{CONSONANTS[(i // 361) % 19]}{i % 10}"
            s = Shoulder.objects.create(shoulder=sh, naan=naan, manager=m)
            m.default_shoulder = s
            m.save()
            c = Client(
                name=f"c{i:04d}",
                label=f"c{i:04d}",
                manager=m,
                naan=naan,
                allowed_scopes="ark:mint",
                client_secret=SECRET,
                client_type=Client.CLIENT_CONFIDENTIAL,
                authorization_grant_type=Client.GRANT_CLIENT_CREDENTIALS,
            )
            c.save()
            last = c
        settings.PASSWORD_HASHERS = real_hashers
        return last

    with capsys.disabled():
        print(
            f"\n  {'クライアント数':>12} {'/o/token/':>12} {'/mint 中央値':>14} {'/mint p95':>11}"
        )
        print("  " + "-" * 54)
        total, results = 0, {}
        for target in (100, 400, 800):
            c = add(target - total, total)
            total = target

            def get_token(c=c):
                r = http.post(
                    "/o/token/",
                    {
                        "grant_type": "client_credentials",
                        "client_id": c.client_id,
                        "client_secret": SECRET,
                    },
                )
                return json.loads(r.content)["access_token"]

            tok = get_token()
            hdr = {"HTTP_AUTHORIZATION": f"Bearer {tok}"}
            t_tok, _ = _timed(get_token, 5)
            med, p95 = _timed(
                lambda: http.post("/mint", data="{}", content_type="application/json", **hdr)
            )
            results[total] = med
            print(f"  {total:>12} {t_tok:>10.1f}ms {med:>12.2f}ms {p95:>9.2f}ms")

    # 出口条件: p95 < 200 ms、かつクライアント数で有意に変わらない。
    assert p95 < 200, f"p95 {p95:.1f}ms"
    assert results[800] < results[100] * 3, f"クライアント数に依存している: {results}"
