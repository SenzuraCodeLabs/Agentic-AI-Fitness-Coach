"""Risk matrix helper.

IT DOES NOT ASSIGN SEVERITY. You provide impact and likelihood for each
finding; this composes them into a risk level using the published table in
``risk_matrix.yaml`` and checks your ratings for internal consistency.

That division is deliberate. An automatically inferred severity is not one you
can defend at a viva, because the reasoning would be the tool's rather than
yours. What a tool CAN do reliably is arithmetic and consistency checking, so
that is all it does here.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

MATRIX_PATH = Path(__file__).resolve().parent / "risk_matrix.yaml"
RATINGS_PATH = Path(__file__).resolve().parent / "ratings.yaml"


@dataclass(slots=True)
class Rating:
    """One finding's rating, as authored by you."""

    case_id: str
    impact: str
    likelihood: str
    justification: str = ""
    family: str = ""


@dataclass(slots=True)
class ScoredRating:
    case_id: str
    impact: str
    likelihood: str
    impact_score: int
    likelihood_score: int
    risk_score: int
    risk_level: str
    justification: str
    family: str


@lru_cache(maxsize=1)
def load_matrix() -> dict[str, Any]:
    return yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))


def score(rating: Rating) -> ScoredRating:
    """Compose impact and likelihood into a risk level."""
    matrix = load_matrix()

    impact_entry = matrix["impact"].get(rating.impact)
    if impact_entry is None:
        valid = ", ".join(matrix["impact"])
        raise ValueError(f"{rating.case_id}: unknown impact '{rating.impact}'. Valid: {valid}")

    likelihood_entry = matrix["likelihood"].get(rating.likelihood)
    if likelihood_entry is None:
        valid = ", ".join(matrix["likelihood"])
        raise ValueError(
            f"{rating.case_id}: unknown likelihood '{rating.likelihood}'. Valid: {valid}"
        )

    impact_score = int(impact_entry["score"])
    likelihood_score = int(likelihood_entry["score"])
    risk_score = impact_score * likelihood_score

    level = "critical"
    for band in matrix["bands"]:
        if risk_score <= int(band["max_score"]):
            level = str(band["level"])
            break

    return ScoredRating(
        case_id=rating.case_id,
        impact=rating.impact,
        likelihood=rating.likelihood,
        impact_score=impact_score,
        likelihood_score=likelihood_score,
        risk_score=risk_score,
        risk_level=level,
        justification=rating.justification,
        family=rating.family,
    )


def band_index(level: str) -> int:
    matrix = load_matrix()
    levels = [str(b["level"]) for b in matrix["bands"]]
    return levels.index(level) if level in levels else -1


def check_consistency(scored: list[ScoredRating]) -> list[str]:
    """Flag ratings that look inconsistent with each other.

    These are questions, not errors. A wide spread inside one family may be
    entirely correct; the point is that you should have decided it rather than
    drifted into it.
    """
    warnings: list[str] = []
    matrix = load_matrix()
    max_gap = int(matrix.get("consistency", {}).get("max_band_gap_within_family", 2))

    by_family: dict[str, list[ScoredRating]] = {}
    for rating in scored:
        if rating.family:
            by_family.setdefault(rating.family, []).append(rating)

    for family, ratings in by_family.items():
        if len(ratings) < 2:
            continue
        bands = [(r, band_index(r.risk_level)) for r in ratings]
        lowest = min(bands, key=lambda pair: pair[1])
        highest = max(bands, key=lambda pair: pair[1])
        if highest[1] - lowest[1] > max_gap:
            warnings.append(
                f"family '{family}': {lowest[0].case_id} is rated "
                f"{lowest[0].risk_level} but {highest[0].case_id} is "
                f"{highest[0].risk_level}. Is that difference intended?"
            )

    # Identical impact and likelihood must yield the same level. If not, the
    # matrix itself is inconsistent.
    by_pair: dict[tuple[str, str], set[str]] = {}
    for rating in scored:
        by_pair.setdefault((rating.impact, rating.likelihood), set()).add(rating.risk_level)
    for (impact, likelihood), levels in by_pair.items():
        if len(levels) > 1:
            warnings.append(
                f"impact={impact}, likelihood={likelihood} produced several "
                f"levels ({sorted(levels)}). The matrix is inconsistent."
            )

    # A rating with no justification is one you cannot defend later.
    for rating in scored:
        if not rating.justification.strip():
            warnings.append(f"{rating.case_id}: no justification recorded for this rating.")

    return warnings


def load_ratings(path: Path | None = None) -> list[Rating]:
    path = path or RATINGS_PATH
    if not path.exists():
        return []
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [
        Rating(
            case_id=str(entry["case_id"]),
            impact=str(entry["impact"]),
            likelihood=str(entry["likelihood"]),
            justification=str(entry.get("justification", "")),
            family=str(entry.get("family", "")),
        )
        for entry in document.get("ratings", [])
    ]


def render_matrix_table() -> str:
    """The impact-by-likelihood grid, for the report's risk section."""
    matrix = load_matrix()
    impacts = sorted(matrix["impact"].items(), key=lambda kv: kv[1]["score"])
    likelihoods = sorted(matrix["likelihood"].items(), key=lambda kv: kv[1]["score"])

    header = "| Impact \\ Likelihood | " + " | ".join(k for k, _ in likelihoods) + " |"
    separator = "| --- " * (len(likelihoods) + 1) + "|"
    rows = [header, separator]

    for impact_name, impact_data in impacts:
        cells = []
        for _, likelihood_data in likelihoods:
            product = int(impact_data["score"]) * int(likelihood_data["score"])
            level = "critical"
            for band in matrix["bands"]:
                if product <= int(band["max_score"]):
                    level = str(band["level"])
                    break
            cells.append(f"{level} ({product})")
        rows.append(f"| **{impact_name}** | " + " | ".join(cells) + " |")

    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ratings", type=Path, default=RATINGS_PATH)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--matrix", action="store_true", help="print the grid and exit")
    args = parser.parse_args()

    if args.matrix:
        print(render_matrix_table())
        return

    ratings = load_ratings(args.ratings)
    if not ratings:
        print(f"No ratings found at {args.ratings}.")
        print("\nCreate it with entries like:\n")
        print("ratings:")
        print("  - case_id: RT-001")
        print("    family: direct_injection")
        print("    impact: moderate        # negligible|minor|moderate|major|severe")
        print("    likelihood: possible    # rare|unlikely|possible|likely|almost_certain")
        print("    justification: >-")
        print("      Why you rated it this way. Required: an unjustified rating")
        print("      is one you cannot defend.")
        return

    scored = [score(r) for r in ratings]

    if args.json:
        print(json.dumps([s.__dict__ for s in scored], indent=2))
        return

    print(f"{'case':12s} {'impact':12s} {'likelihood':16s} {'score':>5s}  level")
    print("-" * 62)
    for rating in sorted(scored, key=lambda s: -s.risk_score):
        print(
            f"{rating.case_id:12s} {rating.impact:12s} {rating.likelihood:16s} "
            f"{rating.risk_score:5d}  {rating.risk_level}"
        )

    warnings = check_consistency(scored)
    if warnings:
        print(f"\n{len(warnings)} consistency question(s):")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("\nRatings are internally consistent.")


if __name__ == "__main__":
    main()
