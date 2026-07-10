"""Structured logging shared across the backend.

Every request gets a short id (via the middleware in app.py) threaded
through a contextvar, so log lines from deep inside RAG retrieval, the LLM
call, or embeddings can be correlated back to the request that triggered
them without passing a request object through every function signature.

Verbosity is controlled by `PROTORAG_LOG_LEVEL` (default INFO; set to DEBUG
for full request/response bodies and provider call details).
"""

import logging
import os
import sys
from contextvars import ContextVar

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(rid: str) -> None:
    _request_id.set(rid)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    level_name = os.environ.get("PROTORAG_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))

    root = logging.getLogger("protorag")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(f"protorag.{name}")
