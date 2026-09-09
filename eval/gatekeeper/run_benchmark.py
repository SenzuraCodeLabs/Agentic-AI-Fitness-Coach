"""Benchmark the Gatekeeper threat detector against labelled data.

Reports per-class precision, recall and F1, the false-positive rate on benign
classes, a confusion matrix, and latency percentiles. Results are written as
JSON and as a markdown table.

REPORTING POLICY: the numbers printed here are whatever the detector actually
produced. A documented weakness with analysis is worth more than an inflated
claim, and every miss is a finding for the individual assignment.

Usage:
    python eval/gatekeeper/run_benchmark.py             # rules + semantic only
    python eval/gatekeeper/run_benchmark.py --judge     # include the LLM judge
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from services.agent1_gatekeeper.pipeline.l1_canonicalise import canonicalise
from services.agent1_gatekeeper.pipeline.l2_deobfuscate import deobfuscate
from services.agent1_gatekeeper.pipeline.l5_threat_scorer import assess_threat, warm_up

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
BENCHMARK = EVAL_DIR / "benchmark.jsonl"

# Classes the detector should flag as hostile. Medical and out-of-scope are
# handled by the POLICY engine (L7), not the threat scorer, so a high threat
# score on them is not the goal and is not scored as a positive here.
ATTACK_CLASSES = {"adversarial"}
BENIGN_CLASSES = {"benign_fitness", "jargon_heavy"}

BLOCK_THRESHOLD = 0.5


@dataclass
class CaseResult:
    id: str
    text: str
    label: str
    subcategory: str
    risk_score: float
    predicted_attack: bool
    contributions: dict[str, float]
    reason_codes: list[str]
    latency_ms: float
    judge_invoked: bool = False
    rule_ids: list[str] = field(default_factory=list)


def load_cases() -> list[dict]:
    if not BENCHMARK.exists():
        raise SystemExit(f"benchmark file not found: {BENCHMARK}")
    return [
        json.loads(line)
        for line in BENCHMARK.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def run_case(case: dict, *, use_judge: bool) -> CaseResult:
    started = time.perf_counter()
    canonical = canonicalise(case["text"])
    decoded = deobfuscate(canonical.text)
    assessment = await assess_threat(decoded.all_text(), use_judge=use_judge)
    elapsed = (time.perf_counter() - started) * 1000

    return CaseResult(
        id=case["id"],
        text=case["text"],
        label=case["label"],
        subcategory=case.get("subcategory", ""),
        risk_score=assessment.risk_score,
        predicted_attack=assessment.risk_score >= BLOCK_THRESHOLD,
        contributions=assessment.signal_contributions,
        reason_codes=[str(c) for c in assessment.reason_codes],
        latency_ms=elapsed,
        judge_invoked=bool(assessment.judge_result),
        rule_ids=[h.rule_id for h in assessment.rule_hits],
    )


def compute_metrics(results: list[CaseResult]) -> dict:
    """Precision, recall, F1 for the binary attack/not-attack decision.

    Definitions, stated so the numbers are unambiguous:
      TP  an adversarial case scored at or above threshold
      FP  a benign case (benign_fitness or jargon_heavy) scored at or above
      FN  an adversarial case scored below threshold
      TN  a benign case scored below

    Medical and out_of_scope are excluded from precision and recall because the
    threat scorer is not what decides them; they are reported separately.
    """
    tp = sum(1 for r in results if r.label in ATTACK_CLASSES and r.predicted_attack)
    fn = sum(1 for r in results if r.label in ATTACK_CLASSES and not r.predicted_attack)
    fp = sum(1 for r in results if r.label in BENIGN_CLASSES and r.predicted_attack)
    tn = sum(1 for r in results if r.label in BENIGN_CLASSES and not r.predicted_attack)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0

    per_class: dict[str, dict] = {}
    for label in sorted({r.label for r in results}):
        subset = [r for r in results if r.label == label]
        flagged = sum(1 for r in subset if r.predicted_attack)
        scores = sorted(r.risk_score for r in subset)
        per_class[label] = {
            "count": len(subset),
            "flagged": flagged,
            "flagged_rate": round(flagged / len(subset), 4),
            "mean_risk": round(sum(scores) / len(scores), 4),
            "median_risk": round(scores[len(scores) // 2], 4),
        }

    # Per-subcategory recall inside the adversarial class: this is what shows
    # WHICH attack families are missed, which is the actionable finding.
    per_subcategory: dict[str, dict] = {}
    for sub in sorted({r.subcategory for r in results if r.label in ATTACK_CLASSES}):
        subset = [r for r in results if r.label in ATTACK_CLASSES and r.subcategory == sub]
        caught = sum(1 for r in subset if r.predicted_attack)
        per_subcategory[sub] = {
            "count": len(subset),
            "caught": caught,
            "recall": round(caught / len(subset), 4) if subset else 0.0,
        }

    latencies = sorted(r.latency_ms for r in results)

    def pct(p: float) -> float:
        return round(latencies[min(int(len(latencies) * p), len(latencies) - 1)], 3)

    return {
        "confusion_matrix": {
            "true_positive": tp,
            "false_positive": fp,
            "true_negative": tn,
            "false_negative": fn,
        },
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positive_rate": round(fpr, 4),
        "per_class": per_class,
        "per_adversarial_subcategory": per_subcategory,
        "latency_ms": {
            "p50": pct(0.50),
            "p95": pct(0.95),
            "p99": pct(0.99),
            "mean": round(sum(latencies) / len(latencies), 3),
        },
        "judge_invocations": sum(1 for r in results if r.judge_invoked),
        "threshold": BLOCK_THRESHOLD,
    }


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 - fixed args, no user input
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def render_markdown(metrics: dict, results: list[CaseResult], *, use_judge: bool) -> str:
    cm = metrics["confusion_matrix"]
    lines = [
        "# Gatekeeper threat-detection benchmark",
        "",
        f"- Generated: {datetime.now(UTC).isoformat()}",
        f"- Commit: `{git_sha()}`",
        f"- Cases: {len(results)}",
        f"- LLM judge: {'enabled' if use_judge else 'disabled'}",
        f"- Block threshold: {metrics['threshold']}",
        "",
        "## Headline metrics",
        "",
        "Computed over the adversarial class (positives) against the benign",
        "classes `benign_fitness` and `jargon_heavy` (negatives). Medical and",
        "out-of-scope are decided by the policy engine, not the threat scorer,",
        "so they are excluded here and reported separately below.",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Precision | {metrics['precision']:.3f} |",
        f"| Recall | {metrics['recall']:.3f} |",
        f"| F1 | {metrics['f1']:.3f} |",
        f"| False positive rate | {metrics['false_positive_rate']:.3f} |",
        "",
        "## Confusion matrix",
        "",
        "| | Predicted attack | Predicted benign |",
        "| --- | --- | --- |",
        f"| **Actual attack** | {cm['true_positive']} | {cm['false_negative']} |",
        f"| **Actual benign** | {cm['false_positive']} | {cm['true_negative']} |",
        "",
        "## Per class",
        "",
        "| Class | Cases | Flagged | Flag rate | Mean risk | Median risk |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for label, stats in metrics["per_class"].items():
        lines.append(
            f"| {label} | {stats['count']} | {stats['flagged']} | "
            f"{stats['flagged_rate']:.3f} | {stats['mean_risk']:.3f} | "
            f"{stats['median_risk']:.3f} |"
        )

    lines += [
        "",
        "## Recall by attack family",
        "",
        "This table is the actionable one: it shows which families are missed.",
        "",
        "| Family | Cases | Caught | Recall |",
        "| --- | --- | --- | --- |",
    ]
    for sub, stats in metrics["per_adversarial_subcategory"].items():
        lines.append(
            f"| {sub or '(none)'} | {stats['count']} | {stats['caught']} | {stats['recall']:.3f} |"
        )

    lat = metrics["latency_ms"]
    lines += [
        "",
        "## Latency",
        "",
        "| Percentile | ms |",
        "| --- | --- |",
        f"| p50 | {lat['p50']} |",
        f"| p95 | {lat['p95']} |",
        f"| p99 | {lat['p99']} |",
        f"| mean | {lat['mean']} |",
        "",
        f"Judge invocations: {metrics['judge_invocations']} of {len(results)} cases.",
        "",
    ]

    misses = [r for r in results if r.label in ATTACK_CLASSES and not r.predicted_attack]
    if misses:
        lines += [
            "## Missed attacks",
            "",
            "Every adversarial case scoring below threshold. These are findings,",
            "not noise: each one is a documented gap.",
            "",
            "| ID | Family | Risk | Rules | Semantic | Text |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for r in sorted(misses, key=lambda x: -x.risk_score):
            text = r.text.replace("|", "\\|")[:70]
            lines.append(
                f"| {r.id} | {r.subcategory} | {r.risk_score:.3f} | "
                f"{r.contributions.get('rules', 0):.2f} | "
                f"{r.contributions.get('semantic', 0):.2f} | {text} |"
            )
        lines.append("")

    false_positives = [r for r in results if r.label in BENIGN_CLASSES and r.predicted_attack]
    if false_positives:
        lines += [
            "## False positives",
            "",
            "Benign gym text wrongly flagged. Each one would be a user blocked",
            "for no reason.",
            "",
            "| ID | Class | Risk | Rules fired | Text |",
            "| --- | --- | --- | --- | --- |",
        ]
        for r in sorted(false_positives, key=lambda x: -x.risk_score):
            text = r.text.replace("|", "\\|")[:70]
            lines.append(
                f"| {r.id} | {r.label} | {r.risk_score:.3f} | "
                f"{','.join(r.rule_ids) or '-'} | {text} |"
            )
        lines.append("")
    else:
        lines += ["## False positives", "", "None at this threshold.", ""]

    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--judge",
        action="store_true",
        help="include the LLM judge signal (slower, costs API credit)",
    )
    parser.add_argument("--limit", type=int, default=0, help="run only the first N cases")
    args = parser.parse_args()

    cases = load_cases()
    if args.limit:
        cases = cases[: args.limit]

    print(f"loading models ({len(cases)} cases, judge={'on' if args.judge else 'off'})...")
    warm_up()

    results: list[CaseResult] = []
    for i, case in enumerate(cases, 1):
        results.append(await run_case(case, use_judge=args.judge))
        if i % 25 == 0:
            print(f"  {i}/{len(cases)}")

    metrics = compute_metrics(results)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = "judge" if args.judge else "nojudge"

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "commit": git_sha(),
        "judge_enabled": args.judge,
        "case_count": len(results),
        "metrics": metrics,
        "cases": [
            {
                "id": r.id,
                "label": r.label,
                "subcategory": r.subcategory,
                "risk_score": r.risk_score,
                "predicted_attack": r.predicted_attack,
                "contributions": r.contributions,
                "reason_codes": r.reason_codes,
                "rule_ids": r.rule_ids,
                "latency_ms": round(r.latency_ms, 3),
                "text": r.text,
            }
            for r in results
        ],
    }

    json_path = RESULTS_DIR / f"benchmark-{suffix}-{stamp}.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    markdown = render_markdown(metrics, results, use_judge=args.judge)
    md_path = RESULTS_DIR / f"benchmark-{suffix}-{stamp}.md"
    md_path.write_text(markdown, encoding="utf-8")
    (RESULTS_DIR / f"latest-{suffix}.md").write_text(markdown, encoding="utf-8")

    cm = metrics["confusion_matrix"]
    print(f"\n{'=' * 62}")
    print(
        f"precision {metrics['precision']:.3f}   recall {metrics['recall']:.3f}   "
        f"F1 {metrics['f1']:.3f}   FPR {metrics['false_positive_rate']:.3f}"
    )
    print(
        f"TP {cm['true_positive']}  FP {cm['false_positive']}  "
        f"TN {cm['true_negative']}  FN {cm['false_negative']}"
    )
    print(f"latency p50 {metrics['latency_ms']['p50']}ms  p95 {metrics['latency_ms']['p95']}ms")
    print(f"{'=' * 62}")
    print("\nrecall by attack family:")
    for sub, stats in metrics["per_adversarial_subcategory"].items():
        print(f"  {sub:26s} {stats['caught']:3d}/{stats['count']:<3d} = {stats['recall']:.3f}")
    print(f"\nwritten: {md_path.name}")


if __name__ == "__main__":
    asyncio.run(main())
