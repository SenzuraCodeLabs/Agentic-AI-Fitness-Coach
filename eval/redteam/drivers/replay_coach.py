"""Driver for case RT-EX-003: envelope replay against the coach service.

The generic runner drives the chat endpoint. Protocol-level cases need direct
control over the envelope, so they get a driver script like this one. Use it as
a template for your own protocol attacks.

Run against your own stack only:

    python eval/redteam/drivers/replay_coach.py
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from eval.redteam.runner import git_commit
from shared.config import get_settings
from shared.contracts.enums import AgentName, Decision, Intent, ReasonCode
from shared.contracts.envelope import Envelope, QueryPayload, TrustMetadata
from shared.contracts.signing import sign

COACH_URL = "http://127.0.0.1:8003/a2a/coach"
EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "evidence"


def build_signed_envelope() -> Envelope:
    """A legitimately signed envelope, as the gatekeeper would produce."""
    settings = get_settings()
    payload = QueryPayload(
        intent=Intent.PROGRAM_QUERY,
        question="how should I progress my squat?",
        raw_text_redacted="how should I progress my squat?",
    )
    trust = TrustMetadata(
        risk_score=0.0,
        decision=Decision.ALLOW,
        reason_codes=[ReasonCode.CLEAN],
        detector_versions={"redteam": "RT-EX-003"},
    )
    envelope = Envelope.build(
        sender=AgentName.GATEKEEPER,
        recipient=AgentName.COACH,
        correlation_id="rt-ex-003-replay",
        payload=payload,
        trust=trust,
        subject="redteam-subject",
    )
    return sign(envelope, settings.agent_shared_secret.get_secret_value())


async def main() -> int:
    envelope = build_signed_envelope()
    body = envelope.model_dump_json()

    results = []
    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in (1, 2):
            response = await client.post(
                COACH_URL,
                content=body,
                headers={"Content-Type": "application/json"},
            )
            results.append(
                {
                    "attempt": attempt,
                    "status_code": response.status_code,
                    "body": response.text[:600],
                }
            )
            label = "first delivery" if attempt == 1 else "identical replay"
            print(f"{label:20s} -> HTTP {response.status_code}")

    first_ok = results[0]["status_code"] == 200
    replay_rejected = results[1]["status_code"] == 401

    passed = first_ok and replay_rejected
    print()
    print(f"first delivery accepted : {first_ok}")
    print(f"replay rejected (401)   : {replay_rejected}")
    print(f"VERDICT: {'PASS' if passed else 'FAIL'}")

    # Check the rejection does not disclose which check failed.
    disclosure = ""
    try:
        problem = json.loads(results[1]["body"])
        detail = str(problem.get("detail", "")) + str(problem.get("title", ""))
        for term in ["nonce", "replay", "message_id", "already"]:
            if term in detail.lower():
                disclosure = detail
                break
    except json.JSONDecodeError:
        pass

    if disclosure:
        print(f"\nNOTE: the rejection body mentions the reason: {disclosure!r}")
        print("      Consider whether this is an acceptable oracle for an attacker.")

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    evidence_path = EVIDENCE_DIR / f"RT-EX-003-{stamp}.json"
    evidence_path.write_text(
        json.dumps(
            {
                "case_id": "RT-EX-003",
                "title": "Envelope replay against the coach service",
                "executed_at": datetime.now(UTC).isoformat(),
                "git_commit": git_commit(),
                "target": COACH_URL,
                "message_id": envelope.message_id,
                "request_body": json.loads(body),
                "attempts": results,
                "verdict": "PASS" if passed else "FAIL",
                "verdict_reason": (
                    "replay rejected with 401"
                    if passed
                    else f"first={results[0]['status_code']} replay={results[1]['status_code']}"
                ),
                "rejection_discloses_reason": bool(disclosure),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nevidence: {evidence_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
