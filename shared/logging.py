"""Structured JSON logging with a correlation ID bound across await points.

Why a ``ContextVar`` rather than passing a logger around: this is an async
service where one request's handler is interleaved with others on the same
thread. A module-level or thread-local would bleed one request's ID into
another's log lines. ``ContextVar`` is copied into each task's context, so the
ID follows the logical request through every ``await`` without threading a
parameter through every function signature.

The correlation ID is the thing that makes a four-service trace readable: the
same value appears on every line the request touches, in all four services.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

import structlog
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

CORRELATION_ID_HEADER = "X-Correlation-ID"

# Holds the current request's correlation ID. Default marks lines emitted
# outside any request (startup, background jobs) so they are still greppable.
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


def new_correlation_id() -> str:
    """Generate a fresh correlation ID."""
    return uuid.uuid4().hex


def set_correlation_id(value: str) -> None:
    _correlation_id.set(value)


def get_correlation_id() -> str:
    return _correlation_id.get()


def _add_correlation_id(_logger: Any, _name: str, event_dict: dict) -> dict:
    """structlog processor injecting the ambient correlation ID on every line."""
    event_dict.setdefault("correlation_id", _correlation_id.get())
    return event_dict


def configure_logging(service: str, level: str = "INFO") -> None:
    """Install JSON logging for this process.

    Also routes stdlib logging (uvicorn, pymongo, httpx) through structlog so
    the output stream is uniformly JSON, rather than JSON interleaved with
    uvicorn's plain-text default.
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _add_correlation_id,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(sort_keys=True),
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn installs its own handlers; clearing them prevents duplicate,
    # non-JSON copies of every access line.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(noisy)
        lg.handlers.clear()
        lg.propagate = True

    # These libraries are chatty at DEBUG and drown the trace.
    for quiet in ("pymongo", "httpx", "httpcore", "asyncio"):
        logging.getLogger(quiet).setLevel(logging.WARNING)

    structlog.contextvars.bind_contextvars(service=service)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)


class CorrelationIdMiddleware:
    """Bind an inbound or freshly generated correlation ID for the request.

    Written as raw ASGI rather than ``BaseHTTPMiddleware`` because the latter
    runs the handler in a separate task whose context does not propagate back,
    which breaks streaming responses (the SSE chat endpoint) and can detach the
    ContextVar. Pure ASGI middleware shares the caller's context.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        cid = headers.get(CORRELATION_ID_HEADER.lower()) or new_correlation_id()
        # Reject absurd inbound values: this string lands in every log line and
        # is echoed back, so it is untrusted input like any other header.
        if len(cid) > 64 or not cid.replace("-", "").isalnum():
            cid = new_correlation_id()

        token = _correlation_id.set(cid)

        async def send_with_header(message: dict) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"].append(
                    (CORRELATION_ID_HEADER.encode("latin-1"), cid.encode("latin-1"))
                )
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            _correlation_id.reset(token)


async def log_request_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Emit one structured line per request with method, path, status, latency."""
    import time

    log = get_logger("http")
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    log.info(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round(elapsed_ms, 2),
    )
    return response
