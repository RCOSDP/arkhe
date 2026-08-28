"""認証・認可の失敗。**HTTP から切り離しておく**（テストを HTTP 抜きで書けるように）。"""

from __future__ import annotations


class AuthError(Exception):
    """401。資格情報が無い・不正・期限切れ。"""

    status = 401

    def __init__(self, detail: str = "invalid credentials", *, challenge: str = "Bearer"):
        self.detail = detail
        self.challenge = challenge
        super().__init__(detail)


class Forbidden(Exception):
    """403。認証はできたが、その操作・その名前空間には届かない。"""

    status = 403

    def __init__(self, detail):
        self.detail = detail
        super().__init__(str(detail))


class InsufficientScope(Forbidden):
    """403 insufficient_scope。**足りない scope を明示する**（クライアントが直せるように）。"""

    def __init__(self, required: str):
        self.required = required
        super().__init__({"detail": "insufficient_scope", "required_scope": required})
