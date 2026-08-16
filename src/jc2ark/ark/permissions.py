"""DRF パーミッション。

S1-4 の実測: **DOT 標準ではクライアントを無効化しても発行済みトークンは TTL まで
有効。** permission クラス 1 つで即時失効にできる。mint は元々 DB を叩くので
追加コストは実質ゼロ（実測 0.80 ms にこの検査が含まれている）。

**これは ARK 固有の要請。** NAA ポリシーに `NR`（No Re-assignment）を宣言する
以上、**誤って採番された ARK の番号は取り消せない**。漏洩に気づいてから TTL 分
だけ採番され続ける状態を許容できない。
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework.permissions import BasePermission


class ClientStillValid(BasePermission):
    message = "client is inactive, expired, or its manager is inactive"

    def has_permission(self, request, view):
        app = getattr(getattr(request, "auth", None), "application", None)
        if app is None or not app.active:
            return False
        if app.expires_at and app.expires_at <= timezone.now():
            return False
        return not (app.manager and not app.manager.active)
