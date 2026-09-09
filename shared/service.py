"""Factory building a FastAPI app with this project's standard wiring.

All four services need the same logging setup, correlation-ID middleware,
health endpoint and RFC 7807 error mapping. Centralising it means a fix to the
error taxonomy applies everywhere rather than being copy-pasted four times.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from shared import db as db_module
from shared.config import get_settings
from shared.errors import ProblemDetail, ProtocolError
from shared.logging import (
    CorrelationIdMiddleware,
    configure_logging,
    get_logger,
    log_request_middleware,
)

VERSION = "0.1.0"


def create_service(
    *,
    service_name: str,
    title: str,
    ensure_indexes: bool = False,
    on_startup: Callable[[], object] | None = None,
) -> FastAPI:
    """Build a configured FastAPI application.

    ``ensure_indexes`` is opt-in: only services that own collections should
    race to create indexes at boot.
    """
    settings = get_settings()
    configure_logging(service_name, settings.log_level)
    log = get_logger(service_name)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        log.info("service_starting", service=service_name, version=VERSION)
        if ensure_indexes:
            try:
                await db_module.ensure_indexes()
            except Exception as exc:  # noqa: BLE001 - never block boot on indexes
                log.warning("index_setup_skipped", error=str(exc))
        if on_startup is not None:
            result = on_startup()
            if hasattr(result, "__await__"):
                await result  # type: ignore[misc]
        log.info("service_started", service=service_name)
        yield
        await db_module.close_client()
        log.info("service_stopped", service=service_name)

    app = FastAPI(
        title=title,
        version=VERSION,
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
    )

    # Order matters and is counter-intuitive: Starlette applies middleware in
    # reverse registration order, so the LAST registered runs OUTERMOST.
    # CorrelationIdMiddleware must be outermost so the ContextVar is bound
    # before anything else runs, otherwise the request logger emits "-" for the
    # correlation ID. Registering it last is what puts it on the outside.
    app.middleware("http")(log_request_middleware)
    app.add_middleware(CorrelationIdMiddleware)

    # --- RFC 7807 problem+json for every error path ------------------------
    @app.exception_handler(ProtocolError)
    async def _protocol_error(_request: Request, exc: ProtocolError) -> JSONResponse:
        log.warning("protocol_error", type=exc.problem_type, detail=exc.detail)
        return _problem_response(exc.to_problem())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # Validation messages can echo submitted values, so they are summarised
        # to field locations rather than returned verbatim.
        fields = [".".join(str(p) for p in e["loc"]) for e in exc.errors()]
        return _problem_response(
            ProblemDetail(
                type="about:blank#validation-error",
                title="Request validation failed",
                status=422,
                detail="One or more fields are invalid.",
                extra={"fields": fields},
            )
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        # Log the real cause, return an opaque body: stack traces and internal
        # messages must not reach the client.
        log.error("unhandled_exception", error=str(exc), exc_info=True)
        return _problem_response(
            ProblemDetail(
                type="about:blank#internal-error",
                title="Internal server error",
                status=500,
                detail="The request could not be completed.",
            )
        )

    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        return {
            "service": service_name,
            "version": VERSION,
            "database": "up" if await db_module.ping() else "down",
        }

    return app


def _problem_response(problem: ProblemDetail) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
    )
