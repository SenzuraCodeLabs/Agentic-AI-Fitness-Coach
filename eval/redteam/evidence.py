"""Render captured evidence into the markdown block the brief requires.

Field order follows the assignment brief exactly: Test ID, Objective, Input,
Expected Result, Actual Result, Evidence, Observations, Outcome.

The Observations field is left as a marked placeholder. That is the analysis,
and the analysis has to be yours: it is the part the marks are for, and
generated prose reads as generated.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"

OBSERVATION_PLACEHOLDER = (
    "> **TODO (your analysis).** Why did the system behave this way? Which "
    "layer was decisive, and what does the per-signal breakdown show? If the "
    "attack was caught, would a small variation evade it? If it succeeded, "
    "what is the root cause rather than the symptom?"
)


def latest_run(directory: Path = EVIDENCE_DIR) -> Path | None:
    runs = sorted(
        (p for p in directory.glob("*") if p.is_dir() and (p / "manifest.json").exists()),
        reverse=True,
    )
    return runs[0] if runs else None


def _format_payload(turns: list[dict[str, Any]]) -> str:
    lines = []
    for turn in turns:
        body = turn.get("request_body", {})
        message = body.get("message")
        if message is None:
            lines.append(f"(turn {turn.get('turn_index', 0)}) {json.dumps(body)[:400]}")
        elif len(turns) > 1:
            lines.append(f"[turn {turn.get('turn_index', 0) + 1}] {message}")
        else:
            lines.append(str(message))
    return "\n".join(lines)


def _format_trace(trace: dict[str, Any]) -> str:
    """Summarise the per-layer trace: the part that explains WHY."""
    if not trace:
        return "_No decision trace captured._"

    lines = [
        f"- Decision: `{trace.get('decision', '?')}` via rule `{trace.get('policy_rule_id', '?')}`",
        f"- Intent: `{trace.get('intent', '?')}`",
        f"- Risk score: `{trace.get('risk_score', '?')}`",
    ]

    contributions = trace.get("signal_contributions") or {}
    if contributions:
        parts = ", ".join(f"{k} {v}" for k, v in contributions.items())
        lines.append(f"- Signal contributions: {parts}")

    if trace.get("reason_codes"):
        lines.append(f"- Reason codes: {', '.join(trace['reason_codes'])}")

    if trace.get("extraction_confidence") is not None:
        lines.append(f"- Extraction confidence: `{trace['extraction_confidence']}`")

    layers = trace.get("layers") or []
    if layers:
        lines.append("")
        lines.append("| Layer | ms | Reason codes | Transformations |")
        lines.append("| --- | --- | --- | --- |")
        for layer in layers:
            codes = ", ".join(layer.get("reason_codes", [])) or "-"
            transforms = (
                ", ".join(t.get("kind", "") for t in layer.get("transformations", [])) or "-"
            )
            lines.append(
                f"| {layer.get('layer', '?')} | {layer.get('duration_ms', 0)} | "
                f"{codes} | {transforms[:70]} |"
            )

    return "\n".join(lines)


def render_case(evidence: dict[str, Any]) -> str:
    """One case as a markdown block in the brief's field order."""
    turns = evidence.get("turns", [])
    last = turns[-1] if turns else {}

    actual_parts = []
    decision = last.get("decision") or {}
    if decision:
        actual_parts.append(
            f"Decision `{decision.get('decision', '?')}`, "
            f"intent `{decision.get('intent', '?')}`, "
            f"risk `{decision.get('risk_score', '?')}`, "
            f"rule `{decision.get('policy_rule_id', '?')}`."
        )
    if last.get("reply_text"):
        actual_parts.append(f"\n\nSystem reply:\n\n> {last['reply_text']}")
    if last.get("error"):
        actual_parts.append(f"\n\nError: `{last['error']}`")
    if last.get("status_code") and last["status_code"] != 200:
        actual_parts.append(f"\n\nHTTP status: `{last['status_code']}`")
    actual = "".join(actual_parts) or "_No response captured._"

    citations = last.get("citations") or []
    citation_block = ""
    if citations:
        citation_block = "\n\n**Sources retrieved:**\n\n" + "\n".join(
            f"- {c.get('source', '?')}" for c in citations
        )

    verdict = evidence.get("verdict", "REVIEW")
    outcome = {
        "PASS": "**Defended.** The system behaved as expected.",
        "FAIL": "**Vulnerability.** The system did not behave as expected.",
        "REVIEW": "**Requires analysis.** Evidence captured; outcome is your judgement.",
    }[verdict]

    latency = evidence.get("total_latency_ms", 0)

    return f"""### {evidence["case_id"]}: {evidence["title"]}

| Field | Value |
| --- | --- |
| Test ID | `{evidence["case_id"]}` |
| Family | {evidence.get("family", "-")} |
| OWASP reference | {evidence.get("owasp_ref") or "-"} |
| Severity if failed | {evidence.get("severity_if_failed", "-")} |
| Executed | {evidence.get("executed_at", "-")} |
| Latency | {latency:.0f} ms |

**Objective**

{evidence.get("objective", "-")}

**Input**

```
{_format_payload(turns)}
```

**Expected result**

{evidence.get("expected_behaviour", "-")}

**Actual result**

{actual}{citation_block}

**Evidence: decision trace**

{_format_trace(last.get("trace", {}))}

**Observations**

{OBSERVATION_PLACEHOLDER}

**Outcome**

{outcome} Runner note: {evidence.get("verdict_reason", "-")}

---
"""


def render_run(run_dir: Path) -> str:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    blocks = [
        f"# Red-team evidence: run {manifest['run_id']}",
        "",
        f"- Commit: `{manifest.get('git_commit', 'unknown')}`",
        f"- Working tree clean: {'no' if manifest.get('git_dirty') else 'yes'}",
        f"- Target: {manifest.get('gateway', '-')}",
        f"- Cases: {manifest.get('case_count', 0)}",
        "",
        "---",
        "",
    ]

    for entry in manifest.get("cases", []):
        path = run_dir / f"{entry['id']}.json"
        if path.exists():
            blocks.append(render_case(json.loads(path.read_text(encoding="utf-8"))))

    return "\n".join(blocks)


async def screenshot_turn(url: str, output: Path) -> bool:
    """Capture the web UI for a turn, if Playwright is available.

    Optional: the JSON evidence is the primary record, and a screenshot is a
    supporting exhibit for the report.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return False

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport={"width": 1100, "height": 900})
            await page.goto(url, wait_until="networkidle")
            output.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(output), full_page=True)
            await browser.close()
        return True
    except Exception:  # noqa: BLE001 - a screenshot failure must not stop reporting
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, help="evidence run directory")
    parser.add_argument("--out", type=Path, help="write markdown here")
    args = parser.parse_args()

    run_dir = args.run or latest_run()
    if run_dir is None:
        raise SystemExit("No evidence runs found. Run eval/redteam/runner.py first.")

    markdown = render_run(run_dir)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown, encoding="utf-8")
        print(f"written: {args.out}")
    else:
        print(markdown)


if __name__ == "__main__":
    main()
