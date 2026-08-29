"""運用のための記録。**構造化ログと、要求ごとの識別子。**

無かったので、障害時に追う材料が DB を直接見る以外に無かった。

## 何を出し、何を出さないか

出すのは**追跡に要る最小限**——要求 ID・経路・状態・所要時間・接続元・主体。
本文もヘッダも出さない。`Authorization` や `X-Forwarded-User` が混じると、
**ログが認証情報の置き場になる**。

失敗の理由は利用者に返さない（総当たりの手掛かりになる）が、**ここには残す**。
「鍵が期限切れ」なのか「組織が停止中」なのかを、運用者は知れなければならない。

## 要求 ID

前段が `X-Request-Id` を付けていればそれを使い、無ければ作る。応答にも返す
ので、利用者が「この ID で調べてほしい」と言える。**長さを切る**——前段が
何を入れてくるか分からないため。
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request

REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="")
HEADER = "X-Request-Id"
MAX_ID = 64

logger = logging.getLogger("arkhe")


class _JsonFormatter(logging.Formatter):
    """1 行 1 レコードの JSON。**集約基盤に渡す前提**で、人が読む整形はしない。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
        }
        rid = REQUEST_ID.get()
        if rid:
            payload["request_id"] = rid
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure(level: str = "INFO") -> None:
    """**アプリの出力先を 1 つに決める。** uvicorn の設定には触らない。"""
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False


def log(msg: str, **fields) -> None:
    """記録する。**秘密を渡さないのは呼び出し側の責任**（ここでは伏せない）。"""
    logger.info(msg, extra={"fields": fields})


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def _trace(request: Request, call_next):
        rid = (request.headers.get(HEADER) or uuid.uuid4().hex)[:MAX_ID]
        token = REQUEST_ID.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # **握り潰さない。** 記録して、そのまま上げる。
            logger.exception(
                "unhandled", extra={"fields": {
                    "method": request.method, "path": request.url.path}}
            )
            raise
        finally:
            REQUEST_ID.reset(token)
        took = int((time.perf_counter() - started) * 1000)
        # 解決は毎回来るので、成功した解決は情報量が少ない——それでも残すのは、
        # **「配った識別子が引かれているか」が運用の関心そのもの**だから。
        log(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=took,
        )
        response.headers[HEADER] = rid
        return response
