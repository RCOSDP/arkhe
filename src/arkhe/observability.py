"""Records for running the service: structured logs and a per-request identifier.

There were none, so during an incident there was nothing to follow except the database.

What is logged, and what is not

The minimum needed to follow a request: its id, the path, the status, how long it took,
the caller and the principal. No bodies and no headers. An Authorization or
X-Forwarded-User header in the log would turn the log into a place credentials are kept.

The reason a request failed is not returned to the caller, since it helps guessing, but
it is kept here. An operator has to be able to tell an expired credential from a stopped
organisation.

The request id

If a proxy set X-Request-Id it is used, otherwise one is made. It comes back in the
response, so someone can say "look up this id". Its length is capped, because there is
no telling what a proxy will send.
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
    """One JSON record per line, meant for a log collector rather than for reading."""

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
    """Decide where this application logs. uvicorn's own settings are left alone."""
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False


def log(msg: str, **fields) -> None:
    """Write a record. Keeping secrets out of it is the caller's responsibility;
    nothing is masked here."""
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
            # Nothing is swallowed: record it and re-raise.
            logger.exception(
                "unhandled", extra={"fields": {
                    "method": request.method, "path": request.url.path}}
            )
            raise
        finally:
            REQUEST_ID.reset(token)
        took = int((time.perf_counter() - started) * 1000)
        # Resolution happens constantly, so a successful one says little on its own.
        # It is still recorded, because whether the identifiers we handed out are being
        # followed is exactly what operators care about.
        log(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=took,
        )
        response.headers[HEADER] = rid
        return response
