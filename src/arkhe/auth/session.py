"""管理画面のセッション。**署名付き Cookie 1 枚だけ。**

サーバ側にセッション表を持たない。持つと、resolver / minter / admin を別プロセスで
動かす設計と噛み合わなくなる（共有ストアが要る）。**Cookie に入れるのは主体の
識別子と期限だけ**で、到達範囲は毎回 Client 表から引き直す——組織の統廃合や鍵の
失効が、次のリクエストから効くようにするため。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

COOKIE = "arkhe_session"
ALGORITHM = "HS256"


def issue(subject: str, *, secret: str, ttl: int, extra: dict | None = None) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl)).timestamp()),
            **(extra or {}),
        },
        secret,
        algorithm=ALGORITHM,
    )


def read(token: str, *, secret: str) -> dict | None:
    """壊れていても期限切れでも **None を返す**（呼び出し側でログインへ送る）。"""
    try:
        return jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "iat", "sub"]}
        )
    except jwt.PyJWTError:
        return None


def set_cookie(response, token: str, *, ttl: int, secure: bool) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=ttl,
        httponly=True,       # JS から読めない
        samesite="lax",      # 外部サイトからの遷移では送らない（CSRF の面）
        secure=secure,       # HTTPS のときだけ送る
        path="/admin",       # **API には送らない。** 用途を混ぜない
    )


def clear_cookie(response) -> None:
    response.delete_cookie(COOKIE, path="/admin")
