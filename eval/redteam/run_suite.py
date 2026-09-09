"""Run the full red-team suite and build the draft report.

Convenience wrapper over runner.py, evidence.py and report_builder.py. Run
against your own stack only:

    python eval/redteam/run_suite.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from eval.redteam import runner
from eval.redteam.evidence import latest_run, render_run
from eval.redteam.report_builder import build_report

REPORT_DIR = Path(__file__).resolve().parent / "report"


async def main() -> int:
    print("=" * 62)
    print("FitCoach red-team suite")
    print("=" * 62)
    print()

    sys.argv = [sys.argv[0]]
    await runner.main()

    run_dir = latest_run()
    if run_dir is None:
        print("no evidence produced")
        return 1

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    evidence_path = REPORT_DIR / f"evidence-{run_dir.name}.md"
    evidence_path.write_text(render_run(run_dir), encoding="utf-8")
    print(f"\nevidence markdown: {evidence_path.name}")

    report_path = REPORT_DIR / f"draft-report-{run_dir.name}.md"
    report_path.write_text(build_report(run_dir), encoding="utf-8")
    print(f"draft report:      {report_path.name}")
    print("\nThe facts are assembled. The analysis is yours.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
