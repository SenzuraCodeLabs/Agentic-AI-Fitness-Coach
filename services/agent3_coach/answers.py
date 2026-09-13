"""Conservative local answers; exact FAQ matching cannot swallow unrelated questions."""

from __future__ import annotations

import re
from typing import Any

FAQS = {
    "what is progressive overload": (
        "Progressive overload means gradually increasing training demand. Add "
        "reps within your target range before increasing load, and keep technique "
        "consistent."
    ),
    "what does rpe mean": (
        "RPE describes how hard a set feels. On the repetitions-in-reserve scale, "
        "RPE 8 means about two reps left, and RPE 10 means no further rep is "
        "possible."
    ),
    "how do i log a workout": (
        "Include the exercise, load, sets and reps, for example: Squatted 60kg "
        "for 3 sets of 8 reps today. You can also include RPE and a session date."
    ),
}


def normalise_question(question: str) -> str:
    return re.sub(r"[?.!]+$", "", " ".join(question.casefold().split()))


def local_answer(question: str, evidence: list[dict[str, Any]]) -> tuple[str, str] | None:
    key = normalise_question(question)
    if key in FAQS:
        return FAQS[key], "predefined"
    # Retrieval ranks candidates; only strong matches can answer without generation.
    strong = [c for c in evidence if c.get("score", 0) >= 0.28]
    if not strong:
        return None
    answer = "\n\n".join(str(c["text"]) for c in strong[:2])
    if re.search(r"\b(stall\w*|plateau\w*|stuck)\b", key):
        answer += (
            "\n\nTo tailor this to you, include your recent sets, reps and RPE, "
            "and how many sessions have stalled."
        )
    return answer, "knowledge_base"
