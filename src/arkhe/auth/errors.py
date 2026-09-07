"""認証・認可の失敗。**HTTP から切り離しておく**（テストを HTTP 抜きで書けるように）。"""

from __future__ import annotations

from arkhe import errors
from arkhe.errors import ApiError


class AuthError(ApiError):
    """401。資格情報が無い・不正・期限切れ。"""

    status = 401

    def __init__(self, detail=None, *, challenge: str = "Bearer", **fmt):
        super().__init__(detail if detail is not None else errors.INVALID_CREDENTIALS,
                         challenge=challenge, **fmt)


class UnregisteredSubject(AuthError):
    """認可サーバのトークンは正しいが、その主体が台帳に無い。

    **AuthError と区別するのは、記録に残す価値がここだけ違うから。**
    署名検証を通った後なので `subject` は認可サーバが書いた値であり、
    運用者が登録するときにそのまま写せる——`client_id` の綴り違いは、
    この構成でいちばん多い詰まりどころである。
    """

    def __init__(self, subject: str, issuer: str = ""):
        self.subject = subject
        self.issuer = issuer
        super().__init__(f"subject {subject} is not registered with this resolver")


class Forbidden(ApiError):
    """403。認証はできたが、その操作・その名前空間には届かない。"""

    status = 403


class InsufficientScope(Forbidden):
    """403 insufficient_scope。**足りない scope を明示する**（クライアントが直せるように）。"""

    def __init__(self, required: str):
        self.required = required
        super().__init__(errors.INSUFFICIENT_SCOPE, scope=required)
