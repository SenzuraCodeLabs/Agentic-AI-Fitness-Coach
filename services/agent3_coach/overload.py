"""Progressive-overload mathematics.

DETERMINISTIC, NOT GENERATED. Every number a user acts on is computed here by
pure functions, never produced by a language model. Three reasons:

  1. An LLM asked for "5 percent more than 100kg" will usually say 105, but
     "usually" is not a property you want on the number someone loads onto a
     bar.
  2. These functions are testable. A recommendation can be asserted exactly.
  3. The reasoning is auditable at a viva: the rule that fired is visible in
     the output rather than hidden in a generation.

The LLM's role is to explain the computed recommendation in readable prose. It
never chooses the numbers.

EPLEY FOR ESTIMATED 1RM
-----------------------
    1RM = weight * (1 + reps/30)

Epley is used because it is the most widely cited formula in strength
literature and is accurate in the 1 to 10 rep range where most working sets
live. It drifts high at very high rep counts, which is why estimates are only
computed at 12 reps or fewer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Smallest usable increment on a standard barbell, two 1.25kg plates.
MIN_INCREMENT_KG = 2.5

# Upper-body lifts progress in smaller absolute jumps than lower-body ones,
# because the same percentage of a smaller load is a smaller absolute step and
# upper-body musculature adds strength more slowly.
UPPER_BODY = {
    "barbell bench press",
    "incline barbell bench press",
    "decline barbell bench press",
    "overhead press",
    "push press",
    "dumbbell bench press",
    "barbell row",
    "lat pulldown",
    "seated cable row",
    "bicep curl",
    "tricep extension",
    "lateral raise",
}

# Reps at or above this are treated as endurance work, where adding load is
# usually the wrong lever.
HIGH_REP_THRESHOLD = 15

# Sessions of no improvement before a deload is suggested.
STALL_SESSIONS = 3


@dataclass(slots=True)
class SessionRecord:
    """One logged set of an exercise, as stored."""

    exercise: str
    load_kg: float | None
    reps: int | None
    sets: int | None
    rpe: float | None
    session_date: datetime

    @property
    def tonnage(self) -> float:
        """Load x reps x sets. The standard single-number workload measure."""
        return (self.load_kg or 0) * (self.reps or 0) * (self.sets or 1)


@dataclass(slots=True)
class Recommendation:
    exercise: str
    action: str
    target_load_kg: float | None = None
    target_reps: int | None = None
    target_sets: int | None = None
    rationale: str = ""
    rule_id: str = ""
    current_load_kg: float | None = None
    estimated_1rm: float | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "exercise": self.exercise,
            "action": self.action,
            "target_load_kg": self.target_load_kg,
            "target_reps": self.target_reps,
            "target_sets": self.target_sets,
            "current_load_kg": self.current_load_kg,
            "estimated_1rm": self.estimated_1rm,
            "rationale": self.rationale,
            "rule_id": self.rule_id,
        }


def round_to_increment(value: float, increment: float = MIN_INCREMENT_KG) -> float:
    """Round to a loadable weight.

    A recommendation of 102.3kg is unusable: plates come in fixed sizes.
    """
    return round(value / increment) * increment


def estimate_1rm(load_kg: float, reps: int) -> float | None:
    """Epley estimate. Returns None where the formula is unreliable."""
    if load_kg <= 0 or reps < 1 or reps > 12:
        return None
    return round(load_kg * (1 + reps / 30), 1)


def increment_for(exercise: str, load_kg: float) -> float:
    """The load step for this exercise.

    Percentage-based with an absolute floor: 2.5 percent of a light bar is
    below the smallest plate pair, so the floor keeps the suggestion loadable.
    """
    percentage = 0.025 if exercise.lower() in UPPER_BODY else 0.05
    return max(MIN_INCREMENT_KG, round_to_increment(load_kg * percentage))


def compute_recommendation(
    history: list[SessionRecord],
    *,
    target_rep_range: tuple[int, int] = (5, 8),
) -> Recommendation:
    """Decide the next prescription from logged history.

    Rules are ordered and the first match wins, so the decision path is a
    single traceable branch rather than a blend of heuristics.
    """
    if not history:
        return Recommendation(
            exercise="unknown",
            action="need_more_data",
            rationale="No logged sessions yet for this exercise.",
            rule_id="NO-HISTORY",
        )

    ordered = sorted(history, key=lambda s: s.session_date)
    latest = ordered[-1]
    exercise = latest.exercise

    if latest.load_kg is None or latest.reps is None:
        return Recommendation(
            exercise=exercise,
            action="need_more_data",
            rationale="The most recent session is missing a load or rep count.",
            rule_id="INCOMPLETE-DATA",
        )

    current_load = latest.load_kg
    current_reps = latest.reps
    low, high = target_rep_range
    estimated = estimate_1rm(current_load, current_reps)

    # --- Rule 1: stalled -----------------------------------------------------
    # Checked first because adding load to a stalled lift is the single most
    # common programming error.
    same_exercise = [s for s in ordered if s.exercise == exercise and s.load_kg is not None]
    if len(same_exercise) >= STALL_SESSIONS:
        recent = same_exercise[-STALL_SESSIONS:]
        loads = [s.load_kg for s in recent]
        reps = [s.reps or 0 for s in recent]
        if max(loads) == min(loads) and max(reps) <= min(reps):
            deload_target = round_to_increment(current_load * 0.9)
            return Recommendation(
                exercise=exercise,
                action="deload",
                target_load_kg=deload_target,
                target_reps=current_reps,
                target_sets=latest.sets,
                current_load_kg=current_load,
                estimated_1rm=estimated,
                rule_id="STALL-DELOAD",
                rationale=(
                    f"No progress across the last {STALL_SESSIONS} sessions at "
                    f"{current_load:g}kg. Reducing to {deload_target:g}kg for a week "
                    "clears accumulated fatigue before building back."
                ),
            )

    # --- Rule 2: RPE too high ------------------------------------------------
    if latest.rpe is not None and latest.rpe >= 9.5:
        return Recommendation(
            exercise=exercise,
            action="hold",
            target_load_kg=current_load,
            target_reps=current_reps,
            target_sets=latest.sets,
            current_load_kg=current_load,
            estimated_1rm=estimated,
            rule_id="RPE-HOLD",
            rationale=(
                f"The last session was RPE {latest.rpe:g}, at or near failure. "
                f"Repeating {current_load:g}kg lets technique consolidate before "
                "the load goes up."
            ),
        )

    # --- Rule 3: top of the rep range, add load -----------------------------
    if current_reps >= high:
        step = increment_for(exercise, current_load)
        new_load = round_to_increment(current_load + step)
        return Recommendation(
            exercise=exercise,
            action="increase_load",
            target_load_kg=new_load,
            target_reps=low,
            target_sets=latest.sets,
            current_load_kg=current_load,
            estimated_1rm=estimated,
            rule_id="TOP-OF-RANGE",
            rationale=(
                f"You hit {current_reps} reps at {current_load:g}kg, the top of the "
                f"{low}-{high} range. Add {step:g}kg to {new_load:g}kg and work back "
                f"up from {low} reps."
            ),
        )

    # --- Rule 4: within the range, add reps ---------------------------------
    if low <= current_reps < high:
        return Recommendation(
            exercise=exercise,
            action="increase_reps",
            target_load_kg=current_load,
            target_reps=current_reps + 1,
            target_sets=latest.sets,
            current_load_kg=current_load,
            estimated_1rm=estimated,
            rule_id="DOUBLE-PROGRESSION",
            rationale=(
                f"You are inside the {low}-{high} rep range at {current_load:g}kg. "
                f"Aim for {current_reps + 1} reps at the same weight before adding load."
            ),
        )

    # --- Rule 5: below the range, load is too heavy -------------------------
    if current_reps < low:
        reduced = round_to_increment(current_load * 0.95)
        return Recommendation(
            exercise=exercise,
            action="reduce_load",
            target_load_kg=reduced,
            target_reps=low,
            target_sets=latest.sets,
            current_load_kg=current_load,
            estimated_1rm=estimated,
            rule_id="BELOW-RANGE",
            rationale=(
                f"{current_reps} reps is below the {low}-{high} target, so the load "
                f"is too heavy for this rep goal. Drop to {reduced:g}kg and build back."
            ),
        )

    # --- Rule 6: very high reps ---------------------------------------------
    step = increment_for(exercise, current_load)
    new_load = round_to_increment(current_load + step * 2)
    return Recommendation(
        exercise=exercise,
        action="increase_load",
        target_load_kg=new_load,
        target_reps=high,
        target_sets=latest.sets,
        current_load_kg=current_load,
        estimated_1rm=estimated,
        rule_id="HIGH-REP-JUMP",
        rationale=(
            f"{current_reps} reps is well above the {low}-{high} range, so the load "
            f"is light for this goal. Move to {new_load:g}kg."
        ),
    )


def compute_tonnage(records: list[SessionRecord]) -> float:
    return round(sum(r.tonnage for r in records), 1)


def find_personal_records(records: list[SessionRecord]) -> dict[str, dict[str, Any]]:
    """Best estimated 1RM per exercise, with the set that produced it."""
    best: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.load_kg is None or record.reps is None:
            continue
        estimate = estimate_1rm(record.load_kg, record.reps)
        if estimate is None:
            continue
        current = best.get(record.exercise)
        if current is None or estimate > current["estimated_1rm"]:
            best[record.exercise] = {
                "estimated_1rm": estimate,
                "load_kg": record.load_kg,
                "reps": record.reps,
                "achieved_on": record.session_date.astimezone(UTC).date().isoformat(),
            }
    return best
