"""API gateway: authentication, rate limiting, and the chat endpoint.

Request order, which is also a cost and safety order:

  1. Authenticate            reject anonymous callers before any work
  2. Size limit              reject oversized bodies before parsing
  3. Rate limit (L0)         reject floods before touching the pipeline
  4. Daily quota             reject over-budget users before spending tokens
  5. Gatekeeper pipeline     classify, score, decide
  6. Downstream call         only if the pipeline allows it

Each step is cheaper than the next, so an abusive request is rejected at the
earliest possible point.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from services.gateway.auth import current_user
from services.gateway.auth import router as auth_router
from services.gateway.ratelimit import check_daily_quota, check_user_and_ip, record_usage
from shared.config import get_settings
from shared.contracts.client import AgentClient
from shared.contracts.enums import AgentName, Decision
from shared.contracts.envelope import CoachReplyPayload
from shared.db import DECISION_TRACES, WORKOUTS, get_db
from shared.errors import RateLimited, UpstreamUnavailable
from shared.logging import get_correlation_id, get_logger
from shared.service import create_service

log = get_logger("gateway")

app = create_service(
    service_name="gateway",
    title="FitCoach Gateway",
    ensure_indexes=True,
)

settings = get_settings()

# CORS is restricted to the configured origins. A wildcard would let any site
# a logged-in user visits call this API with their credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
    expose_headers=["X-Correlation-ID", "Retry-After"],
    max_age=600,
)

app.include_router(auth_router)


@app.middleware("http")
async def security_headers_and_size_limit(request: Request, call_next):
    """Reject oversized bodies and set defensive response headers."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.max_request_bytes:
        return JSONResponse(
            status_code=413,
            content={
                "type": "about:blank#payload-too-large",
                "title": "Request too large",
                "status": 413,
            },
            media_type="application/problem+json",
        )

    response = await call_next(request)

    # nosniff stops a browser from reinterpreting a JSON response as HTML.
    response.headers["X-Content-Type-Options"] = "nosniff"
    # This API returns no HTML, so framing it has no legitimate purpose.
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    # A restrictive CSP: the API serves data, never scripts.
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(RateLimited)
async def _rate_limited(_request: Request, exc: RateLimited) -> JSONResponse:
    """429 with Retry-After, so a well-behaved client knows when to return."""
    problem = exc.to_problem()
    return JSONResponse(
        status_code=429,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
        headers={"Retry-After": str(exc.retry_after)},
    )


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


def _client_ip(request: Request) -> str:
    """Best-effort client address.

    X-Forwarded-For is honoured only because this sits behind a reverse proxy
    in the compose deployment. Trusting it without a proxy would let any caller
    forge their address and evade the per-IP limit, so this is a deployment
    assumption worth stating rather than a general-purpose helper.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _sse(event: str, data: dict[str, Any]) -> str:
    """Format one server-sent event.

    The double newline is the record separator; without it the browser buffers
    indefinitely waiting for the end of the event.
    """
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@app.post("/api/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    user: Annotated[dict[str, Any], Depends(current_user)],
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> StreamingResponse:
    """Run the Gatekeeper pipeline and stream the result over SSE."""
    from services.agent1_gatekeeper.pipeline.orchestrator import run_pipeline

    correlation_id = get_correlation_id()
    user_id = user["_id"]

    # Steps 3 and 4: cheap rejections before any expensive work.
    await check_user_and_ip(db, user_id, _client_ip(request))
    quota = await check_daily_quota(db, user_id)

    async def stream() -> AsyncIterator[str]:
        yield _sse("status", {"stage": "analysing", "correlation_id": correlation_id})

        result = await run_pipeline(
            body.message,
            timezone=user.get("timezone", "UTC"),
            correlation_id=correlation_id,
        )

        # The transparency payload. This is the explainability deliverable:
        # the user can see the intent, the risk score and which rule fired.
        yield _sse(
            "decision",
            {
                "intent": str(result.intent),
                "decision": str(result.decision),
                "risk_score": result.risk_score,
                "policy_rule_id": result.policy_rule_id,
                "reason_codes": [str(c) for c in result.reason_codes],
                "signal_contributions": result.trust.signal_contributions,
                "extraction_confidence": result.trust.extraction_confidence,
                "pipeline_ms": round(result.total_ms, 1),
            },
        )

        message_id = result.envelope.message_id if result.envelope else correlation_id

        # Persist the trace so /api/explain can serve it later.
        await db[DECISION_TRACES].update_one(
            {"message_id": message_id},
            {
                "$set": {
                    "message_id": message_id,
                    "user_id": user_id,
                    "correlation_id": correlation_id,
                    "created_at": datetime.now(UTC),
                    "trace": result.trace_dict(),
                }
            },
            upsert=True,
        )

        # Write the audit record for every turn, including refusals: a blocked
        # request is exactly what a security review needs to see.
        from services.agent1_gatekeeper.pipeline.l8_envelope import write_audit_event

        await write_audit_event(
            correlation_id=correlation_id,
            message_id=message_id,
            user_id=user_id,
            intent=result.intent,
            decision=result.decision,
            risk_score=result.risk_score,
            reason_codes=result.reason_codes,
            policy_rule_id=result.policy_rule_id,
            layer_timings=result.layer_timings(),
            db=db,
        )

        # Terminal decisions end here: no downstream call, no token spend.
        if result.is_terminal or result.envelope is None:
            yield _sse("message", {"text": result.user_message, "terminal": True})
            yield _sse("done", {"message_id": message_id, "quota": quota})
            await record_usage(
                db,
                user_id=user_id,
                correlation_id=correlation_id,
                tokens_used=0,
                decision=str(result.decision),
            )
            return

        # A workout log is persisted before the coach is consulted, so the
        # session is recorded even if the downstream call fails.
        if result.decision in {Decision.ALLOW, Decision.SANITISE}:
            payload = result.envelope.payload
            if hasattr(payload, "sets_logged"):
                await db[WORKOUTS].insert_one(
                    {
                        "user_id": user_id,
                        "correlation_id": correlation_id,
                        "message_id": message_id,
                        "session_date": payload.session_date,
                        "sets": [s.model_dump(mode="json") for s in payload.sets_logged],
                        "created_at": datetime.now(UTC),
                    }
                )
                yield _sse("status", {"stage": "logged", "sets": len(payload.sets_logged)})

        yield _sse("status", {"stage": "coaching"})

        tokens_used = 0
        try:
            async with AgentClient(AgentName.GATEWAY) as client:
                reply = await client.send(
                    recipient=AgentName.GATEKEEPER,
                    path="/a2a/assess",
                    payload=result.envelope.payload,
                    trust=result.trust,
                    correlation_id=correlation_id,
                    # Identifies whose history the coach should load. Inside
                    # the signed region, so it cannot be forged to read another
                    # user's training data.
                    subject=user_id,
                )
            if isinstance(reply.payload, CoachReplyPayload):
                text = reply.payload.reply_text
                tokens_used = reply.payload.tokens_used
                # Restore any redacted values before showing the reply to the
                # user who supplied them.
                if result.pii_vault is not None:
                    text = result.pii_vault.rehydrate(text)
                yield _sse(
                    "message",
                    {"text": text, "citations": reply.payload.citations, "terminal": False},
                )
            else:
                yield _sse("message", {"text": "Logged.", "terminal": False})

        except UpstreamUnavailable:
            log.error("coach_unavailable", correlation_id=correlation_id)
            yield _sse(
                "error",
                {
                    "message": (
                        "The coaching service is temporarily unavailable. Your session was saved."
                    )
                },
            )

        await record_usage(
            db,
            user_id=user_id,
            correlation_id=correlation_id,
            tokens_used=tokens_used,
            model=settings.deepseek_model_strong,
            decision=str(result.decision),
        )
        yield _sse("done", {"message_id": message_id, "quota": quota})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Tells nginx not to buffer, which would defeat streaming.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/explain/{message_id}")
async def explain(
    message_id: str,
    user: Annotated[dict[str, Any], Depends(current_user)],
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Return the full decision trace for one turn.

    Scoped to the requesting user: a trace reveals what someone wrote and how
    it was judged, so one user must not be able to read another's.
    """
    record = await db[DECISION_TRACES].find_one({"message_id": message_id, "user_id": user["_id"]})
    if record is None:
        # 404 rather than 403 for a trace belonging to someone else: a 403
        # would confirm the message id exists.
        return JSONResponse(
            status_code=404,
            content={
                "type": "about:blank#not-found",
                "title": "No trace for that message",
                "status": 404,
            },
            media_type="application/problem+json",
        )

    return {
        "message_id": message_id,
        "correlation_id": record.get("correlation_id"),
        "created_at": record.get("created_at"),
        "trace": record.get("trace", {}),
    }


@app.get("/api/workouts")
async def list_workouts(
    user: Annotated[dict[str, Any], Depends(current_user)],
    db: AsyncIOMotorDatabase = Depends(get_db),
    limit: int = 50,
) -> dict[str, Any]:
    """Recent sessions with computed tonnage, for the history view."""
    cursor = (
        db[WORKOUTS]
        .find({"user_id": user["_id"]}, {"_id": 0})
        .sort("session_date", -1)
        .limit(min(max(limit, 1), 200))
    )
    sessions = await cursor.to_list(length=200)

    for session in sessions:
        session["tonnage_kg"] = round(
            sum(
                (s.get("load_kg") or 0) * (s.get("reps") or 0) * (s.get("sets") or 1)
                for s in session.get("sets", [])
            ),
            1,
        )
    return {"sessions": sessions, "count": len(sessions)}


@app.get("/api/telemetry")
async def telemetry(
    user: Annotated[dict[str, Any], Depends(current_user)],
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict[str, Any]:
    """Token spend for the current user, for the telemetry page."""
    quota = await check_daily_quota(db, user["_id"])
    return {"quota": quota}
