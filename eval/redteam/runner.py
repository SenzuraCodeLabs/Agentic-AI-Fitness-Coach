"""Execute red-team cases against the running stack and capture evidence.

Every run writes one JSON file per case plus a manifest recording the git
commit and timestamp. That is what makes a finding reproducible and
attributable: a screenshot without a commit hash cannot be re-tested.

WHAT IS CAPTURED, AND WHY
-------------------------
  request           the exact bytes sent, so the test can be repeated
  response          everything the system said back
  decision trace    per-layer output and per-signal contributions, which is
                    what lets the analysis explain WHY an attack was caught
                    or missed rather than just that it was
  retrieved chunks  for cases that reach the researcher
  latency, tokens   cost and denial-of-service evidence

The runner reports a verdict only for cases with explicit expectations. Where
there is none it records evidence and marks the case for your judgement, which
is the honest default: whether a subtle response constitutes a leak is an
analytical question, not a string comparison.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from eval.redteam.schema import Endpoint, TestCase, load_cases

EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"
GATEWAY = "http://127.0.0.1:8000"

# A dedicated account per run. Using a real user's account would pollute their
# training history with attack payloads.
RUN_PASSWORD = "RedTeamPass123!suite"  # noqa: S105 - throwaway test account


@dataclass
class TurnEvidence:
    turn_index: int
    request_body: dict[str, Any]
    status_code: int
    events: list[dict[str, Any]] = field(default_factory=list)
    reply_text: str = ""
    decision: dict[str, Any] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    error: str = ""


@dataclass
class CaseEvidence:
    case_id: str
    title: str
    family: str
    objective: str
    expected_behaviour: str
    severity_if_failed: str
    owasp_ref: str
    notes: str
    target_endpoint: str
    turns: list[TurnEvidence] = field(default_factory=list)
    verdict: str = "REVIEW"  # PASS, FAIL or REVIEW
    verdict_reason: str = ""
    total_latency_ms: float = 0.0
    tokens_used: int = 0
    run_id: str = ""
    executed_at: str = ""


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],  # noqa: S607 - fixed args
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def git_is_dirty() -> bool:
    """Uncommitted changes mean the evidence cannot be reproduced from the commit."""
    try:
        return bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],  # noqa: S607
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


class RedTeamSession:
    """One authenticated session, reused across a multi-turn case."""

    def __init__(self, base_url: str = GATEWAY) -> None:
        self.base_url = base_url
        self.email = f"redteam-{uuid.uuid4().hex[:10]}@example.com"
        self.access_token: str | None = None
        self.client = httpx.AsyncClient(timeout=180.0)

    async def __aenter__(self) -> RedTeamSession:
        await self.register_and_login()
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.client.aclose()

    async def register_and_login(self) -> None:
        await self.client.post(
            f"{self.base_url}/api/auth/register",
            json={"email": self.email, "password": RUN_PASSWORD},
        )
        response = await self.client.post(
            f"{self.base_url}/api/auth/login",
            json={"email": self.email, "password": RUN_PASSWORD},
        )
        response.raise_for_status()
        self.access_token = response.json()["access_token"]

    async def send_chat(self, message: str, turn_index: int) -> TurnEvidence:
        """Send one chat turn, capturing every SSE event."""
        body = {"message": message}
        evidence = TurnEvidence(turn_index=turn_index, request_body=body, status_code=0)
        started = time.perf_counter()

        try:
            async with self.client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=body,
                headers={"Authorization": f"Bearer {self.access_token}"},
            ) as response:
                evidence.status_code = response.status_code

                if response.status_code != 200:
                    raw = await response.aread()
                    evidence.error = raw.decode(errors="replace")[:500]
                    evidence.latency_ms = (time.perf_counter() - started) * 1000
                    return evidence

                event_name = ""
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        event_name = line[7:].strip()
                    elif line.startswith("data: "):
                        try:
                            payload = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue
                        evidence.events.append({"event": event_name, "data": payload})
                        if event_name == "decision":
                            evidence.decision = payload
                        elif event_name == "message":
                            evidence.reply_text = str(payload.get("text", ""))
                            evidence.citations = payload.get("citations", []) or []
                        elif event_name == "error":
                            evidence.error = str(payload.get("message", ""))

        except httpx.HTTPError as exc:
            evidence.error = f"transport error: {exc}"

        evidence.latency_ms = (time.perf_counter() - started) * 1000

        # Pull the full per-layer trace, which the SSE stream summarises.
        message_id = ""
        for event in evidence.events:
            if event["event"] == "done":
                message_id = str(event["data"].get("message_id", ""))
        if message_id:
            try:
                trace_response = await self.client.get(
                    f"{self.base_url}/api/explain/{message_id}",
                    headers={"Authorization": f"Bearer {self.access_token}"},
                )
                if trace_response.status_code == 200:
                    evidence.trace = trace_response.json().get("trace", {})
            except httpx.HTTPError:
                pass

        return evidence


def evaluate(case: TestCase, evidence: CaseEvidence) -> tuple[str, str]:
    """Apply the case's explicit expectations, if it has any.

    Returns REVIEW when the case declares none. That is deliberate: silently
    passing an unchecked case would inflate the results, and a suite that
    reports everything green teaches you nothing.
    """
    if not case.is_automatically_checkable:
        return "REVIEW", "no automatic assertions; requires manual analysis"

    last = evidence.turns[-1] if evidence.turns else None
    if last is None:
        return "FAIL", "no turns were executed"

    decision = str(last.decision.get("decision", ""))
    reply = last.reply_text.lower()

    if case.expect_decision is not None and decision != case.expect_decision:
        return "FAIL", f"expected decision {case.expect_decision}, got {decision or 'none'}"

    if case.expect_blocked is not None:
        blocked = decision in {"BLOCK", "REFUSE_MEDICAL"}
        if blocked != case.expect_blocked:
            return (
                "FAIL",
                f"expected blocked={case.expect_blocked}, decision was {decision or 'none'}",
            )

    for forbidden in case.expect_not_in_response:
        if forbidden.lower() in reply:
            return "FAIL", f"response contained forbidden text: {forbidden!r}"

    for required in case.expect_in_response:
        if required.lower() not in reply:
            return "FAIL", f"response did not contain expected text: {required!r}"

    return "PASS", "all declared expectations held"


async def run_case(session: RedTeamSession, case: TestCase) -> CaseEvidence:
    evidence = CaseEvidence(
        case_id=case.id,
        title=case.title,
        family=str(case.family),
        objective=case.objective,
        expected_behaviour=case.expected_behaviour,
        severity_if_failed=str(case.severity_if_failed),
        owasp_ref=case.owasp_ref,
        notes=case.notes,
        target_endpoint=str(case.target_endpoint),
        executed_at=datetime.now(UTC).isoformat(),
    )

    if case.target_endpoint is Endpoint.CHAT:
        for index, turn in enumerate(case.turns):
            evidence.turns.append(await session.send_chat(turn, index))
    else:
        # Non-chat endpoints (protocol attacks against :8003, and similar) are
        # driven by a bespoke script per case rather than this generic path.
        evidence.turns.append(
            TurnEvidence(
                turn_index=0,
                request_body={"note": f"endpoint {case.target_endpoint} needs a custom driver"},
                status_code=0,
                error="not executed by the generic runner",
            )
        )

    evidence.total_latency_ms = sum(t.latency_ms for t in evidence.turns)
    evidence.verdict, evidence.verdict_reason = evaluate(case, evidence)
    return evidence


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="run a single case by id")
    parser.add_argument("--family", help="run only cases in this family")
    parser.add_argument(
        "--out",
        type=Path,
        default=EVIDENCE_DIR,
        help="directory for evidence files",
    )
    args = parser.parse_args()

    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c.id == args.case]
    if args.family:
        cases = [c for c in cases if str(c.family) == args.family]

    if not cases:
        raise SystemExit("no cases matched")

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    commit = git_commit()
    dirty = git_is_dirty()
    if dirty:
        print("WARNING: working tree has uncommitted changes.")
        print("         This evidence cannot be reproduced from the commit alone.")

    print(f"run {run_id}: {len(cases)} case(s) against {GATEWAY}")

    results: list[CaseEvidence] = []
    async with RedTeamSession() as session:
        print(f"test account: {session.email}\n")
        for case in cases:
            evidence = await run_case(session, case)
            evidence.run_id = run_id
            results.append(evidence)

            (out_dir / f"{case.id}.json").write_text(
                json.dumps(asdict(evidence), indent=2, default=str),
                encoding="utf-8",
            )

            marker = {"PASS": "pass", "FAIL": "FAIL", "REVIEW": "review"}[evidence.verdict]
            print(f"  [{marker:6s}] {case.id:12s} {case.title[:52]}")
            if evidence.verdict == "FAIL":
                print(f"             {evidence.verdict_reason}")

    manifest = {
        "run_id": run_id,
        "executed_at": datetime.now(UTC).isoformat(),
        "git_commit": commit,
        "git_dirty": dirty,
        "gateway": GATEWAY,
        "case_count": len(results),
        "verdicts": {
            "pass": sum(1 for r in results if r.verdict == "PASS"),
            "fail": sum(1 for r in results if r.verdict == "FAIL"),
            "review": sum(1 for r in results if r.verdict == "REVIEW"),
        },
        "cases": [
            {
                "id": r.case_id,
                "family": r.family,
                "verdict": r.verdict,
                "reason": r.verdict_reason,
                "severity_if_failed": r.severity_if_failed,
            }
            for r in results
        ],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    counts = manifest["verdicts"]
    print(f"\npass {counts['pass']}  fail {counts['fail']}  review {counts['review']}")
    print(f"evidence: {out_dir}")
    if counts["review"]:
        print(
            f"\n{counts['review']} case(s) need your analysis: the runner captured "
            "evidence but cannot judge them automatically."
        )


if __name__ == "__main__":
    asyncio.run(main())
