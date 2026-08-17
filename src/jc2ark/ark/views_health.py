"""ヘルスチェック。**probe を API の表面から切り離す。**

ロールごとに出す口が違うので、probe を業務エンドポイントに向けると
**構成を変えたときに probe が壊れてロールアウトが止まる**（実際に起きた——
minter から admin を外したら `/admin/login/` を見ていた probe が 404 になり、
新しい Pod が Ready にならなかった）。
"""

from __future__ import annotations

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_safe


@require_safe
def healthz(request):
    """生存確認。**DB まで見る**（プロセスが立っていても DB が死んでいれば無意味）。"""
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
            c.fetchone()
        db = "ok"
        status = 200
    except Exception as exc:  # pragma: no cover - 障害時の経路
        db = f"error: {type(exc).__name__}"
        status = 503
    return JsonResponse({"role": settings.JC2ARK_ROLE, "db": db}, status=status)
