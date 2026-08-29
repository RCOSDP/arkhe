"""認証・認可の失敗。**HTTP から切り離しておく**（テストを HTTP 抜きで書けるように）。"""

from __future__ import annotations


class AuthError(Exception):
    """401。資格情報が無い・不正・期限切れ。"""

    status = 401

    def __init__(self, detail: str = "invalid credentials", *, challenge: str = "Bearer"):
        self.detail = detail
        self.challenge = challenge
        super().__init__(detail)


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
