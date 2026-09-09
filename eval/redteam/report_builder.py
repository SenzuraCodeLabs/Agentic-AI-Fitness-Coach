"""Assemble a draft report in the brief's section order.

WHAT THIS DOES: gathers the facts. Which cases ran, what happened, the risk
matrix, the evidence blocks, the commit they came from.

WHAT THIS DOES NOT DO: write the analysis. Every prose section is a marked
TODO. The 25 marks for quality of vulnerability analysis are for your reasoning
about why each attack succeeded or failed, and generated prose reads as
generated. The viva will find it.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from eval.redteam.evidence import latest_run, render_case
from eval.redteam.scoring import (
    check_consistency,
    load_ratings,
    render_matrix_table,
    score,
)

REPORT_DIR = Path(__file__).resolve().parent / "report"


def todo(instruction: str) -> str:
    return f"> **TODO (your writing).** {instruction}\n"


def build_report(run_dir: Path) -> str:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    cases = manifest.get("cases", [])

    failed = [c for c in cases if c["verdict"] == "FAIL"]
    review = [c for c in cases if c["verdict"] == "REVIEW"]
    passed = [c for c in cases if c["verdict"] == "PASS"]

    ratings = load_ratings()
    scored = [score(r) for r in ratings] if ratings else []
    warnings = check_consistency(scored) if scored else []

    sections: list[str] = []

    # --- Title -------------------------------------------------------------
    sections.append(
        f"""# Vulnerability Assessment: FitCoach Agentic AI System

**Prompt injection and jailbreak analysis**

| | |
| --- | --- |
| Assessment date | {datetime.now(UTC).date().isoformat()} |
| Target commit | `{manifest.get('git_commit', 'unknown')[:12]}` |
| Working tree clean | {'no' if manifest.get('git_dirty') else 'yes'} |
| Test cases executed | {manifest.get('case_count', 0)} |
| Evidence run | `{manifest.get('run_id', '-')}` |

---
"""
    )

    # --- 1. Executive summary ---------------------------------------------
    sections.append(
        f"""## 1. Executive Summary

{todo(
    "Three or four paragraphs for a reader who will not read the rest. State "
    "what was tested, the headline result, the most serious finding and what "
    "you recommend. Write it last, once you know what you found."
)}
**Facts available to you:**

- {manifest.get('case_count', 0)} cases executed
- Commit `{manifest.get('git_commit', 'unknown')[:12]}`
- {len(passed)} defended, {len(failed)} failed, {len(review)} require analysis
- Detector benchmark at the time of testing: see `eval/gatekeeper/results/`

---
"""
    )

    # --- 2. Scope ----------------------------------------------------------
    sections.append(
        f"""## 2. Scope of Testing

**In scope**

| Component | Port | Why it is in scope |
| --- | --- | --- |
| Gateway | 8000 | Entry point; authentication, rate limiting, chat |
| Gatekeeper | 8001 | The security control under test |
| Researcher | 8002 | Retrieval; indirect injection surface |
| Coach | 8003 | Generation; downstream of every control |

**Out of scope**

{todo(
    "State what you did NOT test and why: the DeepSeek API itself, MongoDB "
    "server hardening, network transport, physical security. A scope section "
    "that does not say what was excluded is not a scope section."
)}
**Authorisation**

This is the author's own coursework system, tested locally against a local
deployment. No third-party system was tested.

---
"""
    )

    # --- 3. Methodology ----------------------------------------------------
    sections.append(
        f"""## 3. Evaluation Methodology

{todo(
    "Describe how you designed the cases. Why these families? How did you "
    "choose payloads? What did you do when a case was ambiguous? Reference "
    "OWASP LLM Top 10 where your cases map to it."
)}
**Harness**

Cases are YAML in `eval/redteam/cases/`, validated on load. `runner.py`
executes each case against the running stack and captures, per turn: the exact
request, the full response, the Gatekeeper decision trace with per-layer output
and per-signal threat contributions, retrieved chunks, latency and token cost.
Each run writes one JSON file per case plus a manifest recording the git commit
and timestamp, so any finding can be reproduced.

The runner reports PASS or FAIL only where a case declares explicit
expectations. Anything subtle is marked REVIEW and captured for manual
analysis, because whether a response constitutes a leak is a judgement, not a
string comparison.

**Complementary tooling**

{todo(
    "If you ran garak or promptfoo for additional automated probe coverage, "
    "describe what they added and how their results compare to the "
    "hand-written cases. If you did not, say so."
)}
---
"""
    )

    # --- 4. Test cases -----------------------------------------------------
    sections.append("## 4. Test Cases Performed\n")
    sections.append(
        "| ID | Title | Family | OWASP | Outcome |\n| --- | --- | --- | --- | --- |"
    )
    for case in cases:
        path = run_dir / f"{case['id']}.json"
        title, owasp = case["id"], "-"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            title = data.get("title", case["id"])
            owasp = data.get("owasp_ref") or "-"
        marker = {"PASS": "Defended", "FAIL": "**Vulnerable**", "REVIEW": "Analysis"}[
            case["verdict"]
        ]
        sections.append(
            f"| `{case['id']}` | {title} | {case['family']} | {owasp} | {marker} |"
        )
    sections.append("\n---\n")

    # --- 5. Vulnerabilities ------------------------------------------------
    sections.append("## 5. Vulnerabilities Identified\n")
    if failed:
        sections.append(
            f"{len(failed)} case(s) failed. Each is written up below with its "
            "evidence.\n"
        )
        for case in failed:
            path = run_dir / f"{case['id']}.json"
            if path.exists():
                sections.append(render_case(json.loads(path.read_text(encoding="utf-8"))))
    else:
        sections.append(
            "No case failed its declared assertions.\n\n"
            + todo(
                "Do not stop here. An empty vulnerabilities section is only "
                "credible if you explain what you tried and why the defences "
                "held. Examine the REVIEW cases: an attack that was blocked "
                "for the wrong reason, or blocked by luck, is still a finding."
            )
        )
    sections.append("\n---\n")

    # --- 6. Risk assessment -------------------------------------------------
    sections.append("## 6. Risk Assessment\n")
    sections.append("**Matrix** (impact x likelihood, from `risk_matrix.yaml`)\n")
    sections.append(render_matrix_table())
    sections.append("")

    if scored:
        sections.append("\n**Ratings**\n")
        sections.append("| Case | Impact | Likelihood | Score | Risk | Justification |")
        sections.append("| --- | --- | --- | --- | --- | --- |")
        for rating in sorted(scored, key=lambda s: -s.risk_score):
            sections.append(
                f"| `{rating.case_id}` | {rating.impact} | {rating.likelihood} | "
                f"{rating.risk_score} | **{rating.risk_level}** | "
                f"{rating.justification[:100]} |"
            )
        if warnings:
            sections.append("\n**Consistency questions**\n")
            for warning in warnings:
                sections.append(f"- {warning}")
    else:
        sections.append(
            "\n"
            + todo(
                "No ratings found. Create eval/redteam/ratings.yaml with an "
                "impact and likelihood for each finding, plus a justification. "
                "Run `python eval/redteam/scoring.py` to compose them and "
                "check them for consistency."
            )
        )
    sections.append("\n---\n")

    # --- 7. Mitigations -----------------------------------------------------
    sections.append(
        f"""## 7. Mitigation Strategies

{todo(
    "For each finding: what would fix it, what it would cost, and what "
    "residual risk remains afterwards. Distinguish what you actually fixed "
    "from what you are recommending. A mitigation section that only lists "
    "generic advice is not evidence of analysis."
)}
**Controls already present** (verify each before citing it)

| Control | Where | Evidence |
| --- | --- | --- |
| Unicode canonicalisation | `l1_canonicalise.py` | `tests/gatekeeper/test_l1_canonicalise.py` |
| Encoded payload recovery | `l2_deobfuscate.py` | `tests/gatekeeper/test_l2_deobfuscate.py` |
| Hybrid threat detection | `l5_threat_scorer.py` | `eval/gatekeeper/results/` |
| PII redaction before external calls | `l6_pii_redactor.py` | `test_redaction_precedes...` |
| Policy engine, neutral refusals | `l7_policy_engine.py` | `test_a_block_message_...` |
| Spotlight delimiters | `l8_envelope.py` | Judge rejected an instruction aimed at itself |
| Signed envelopes, replay protection | `shared/contracts/` | `tests/contracts/` |
| Uniform rejection responses | `shared/errors.py` | `test_every_envelope_rejection...` |

---
"""
    )

    # --- 8. Reflection ------------------------------------------------------
    sections.append(
        f"""## 8. Reflection

{todo(
    "What did testing your own system teach you? Where were you wrong about "
    "your own design? Which defence turned out to matter most, and which was "
    "theatre? What would you do differently? This section rewards honesty "
    "about your own mistakes more than confidence."
)}
---

## Appendix: full evidence

Raw evidence for every case, including cases that passed, is in
`{run_dir.name}/`. Render it with:

```bash
python eval/redteam/evidence.py --run eval/redteam/evidence/{run_dir.name}
```
"""
    )

    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, help="evidence run directory")
    parser.add_argument("--out", type=Path, help="output path")
    args = parser.parse_args()

    run_dir = args.run or latest_run()
    if run_dir is None:
        raise SystemExit("No evidence runs found. Run eval/redteam/runner.py first.")

    report = build_report(run_dir)
    output = args.out or (REPORT_DIR / f"draft-report-{run_dir.name}.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")

    todo_count = report.count("TODO (your")
    print(f"written: {output}")
    print(f"{todo_count} section(s) marked for your writing.")
    print("\nThe facts are assembled. The analysis is yours.")


if __name__ == "__main__":
    main()
