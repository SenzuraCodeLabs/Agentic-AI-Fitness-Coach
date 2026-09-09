"""Progressive-overload mathematics.

These are the numbers a user loads onto a bar, so they are asserted exactly.
Every function here is pure, which is what makes that possible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.agent3_coach.overload import (
    SessionRecord,
    compute_recommendation,
    compute_tonnage,
    estimate_1rm,
    find_personal_records,
    increment_for,
    round_to_increment,
)

BASE_DATE = datetime(2026, 9, 1, tzinfo=UTC)


def session(
    exercise: str = "barbell back squat",
    load: float | None = 100.0,
    reps: int | None = 5,
    sets: int | None = 3,
    rpe: float | None = None,
    day_offset: int = 0,
) -> SessionRecord:
    return SessionRecord(
        exercise=exercise,
        load_kg=load,
        reps=reps,
        sets=sets,
        rpe=rpe,
        session_date=BASE_DATE + timedelta(days=day_offset),
    )


# --- Loadability ------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [(102.3, 102.5), (100.0, 100.0), (101.2, 100.0), (103.8, 105.0)],
)
def test_rounding_produces_a_loadable_weight(value, expected):
    """A recommendation of 102.3kg is unusable: plates come in fixed sizes."""
    assert round_to_increment(value) == expected


def test_upper_body_increments_are_smaller_than_lower_body():
    """The same percentage of a smaller load is a smaller absolute step, and
    upper-body strength accrues more slowly."""
    upper = increment_for("barbell bench press", 100)
    lower = increment_for("barbell back squat", 100)
    assert upper < lower


def test_increment_never_falls_below_the_smallest_plate_pair():
    assert increment_for("bicep curl", 10) >= 2.5


# --- Epley ------------------------------------------------------------------


def test_epley_estimate():
    # 100kg x 5 -> 100 * (1 + 5/30) = 116.7
    assert estimate_1rm(100, 5) == pytest.approx(116.7, abs=0.1)


def test_one_rep_maximum_of_a_single_is_the_weight_itself():
    assert estimate_1rm(140, 1) == pytest.approx(144.7, abs=0.1)


def test_estimate_is_refused_outside_the_reliable_range():
    """Epley drifts high at high rep counts, so no estimate is offered."""
    assert estimate_1rm(60, 25) is None
    assert estimate_1rm(0, 5) is None


# --- Recommendation rules ---------------------------------------------------


def test_no_history_asks_for_more_data():
    result = compute_recommendation([])
    assert result.action == "need_more_data"
    assert result.rule_id == "NO-HISTORY"


def test_top_of_rep_range_adds_load():
    result = compute_recommendation([session(reps=8)], target_rep_range=(5, 8))
    assert result.action == "increase_load"
    assert result.rule_id == "TOP-OF-RANGE"
    assert result.target_load_kg == 105.0  # 100 + 5%
    assert result.target_reps == 5


def test_inside_rep_range_adds_a_rep():
    result = compute_recommendation([session(reps=6)], target_rep_range=(5, 8))
    assert result.action == "increase_reps"
    assert result.rule_id == "DOUBLE-PROGRESSION"
    assert result.target_load_kg == 100.0
    assert result.target_reps == 7


def test_below_rep_range_reduces_load():
    result = compute_recommendation([session(reps=3)], target_rep_range=(5, 8))
    assert result.action == "reduce_load"
    assert result.target_load_kg == 95.0


def test_a_stall_triggers_a_deload():
    """Adding load to a stalled lift is the most common programming error, so
    this rule is checked before every progression rule."""
    history = [
        session(load=100, reps=5, day_offset=0),
        session(load=100, reps=5, day_offset=3),
        session(load=100, reps=5, day_offset=6),
    ]
    result = compute_recommendation(history)
    assert result.action == "deload"
    assert result.rule_id == "STALL-DELOAD"
    assert result.target_load_kg == 90.0


def test_a_stall_outranks_the_top_of_range_rule():
    history = [
        session(load=100, reps=8, day_offset=0),
        session(load=100, reps=8, day_offset=3),
        session(load=100, reps=8, day_offset=6),
    ]
    assert compute_recommendation(history).action == "deload"


def test_high_rpe_holds_the_load():
    result = compute_recommendation([session(reps=5, rpe=10)], target_rep_range=(5, 8))
    assert result.action == "hold"
    assert result.rule_id == "RPE-HOLD"
    assert result.target_load_kg == 100.0


def test_progression_still_applies_at_moderate_rpe():
    result = compute_recommendation([session(reps=8, rpe=7)], target_rep_range=(5, 8))
    assert result.action == "increase_load"


def test_incomplete_data_is_reported_not_guessed():
    result = compute_recommendation([session(load=None, reps=None)])
    assert result.action == "need_more_data"
    assert result.rule_id == "INCOMPLETE-DATA"


def test_every_recommendation_carries_its_rule_id():
    """The rule that fired must be visible, so the decision is auditable."""
    for record in [session(reps=8), session(reps=6), session(reps=3)]:
        assert compute_recommendation([record]).rule_id


def test_rationale_states_the_actual_numbers():
    result = compute_recommendation([session(reps=8)], target_rep_range=(5, 8))
    assert "105" in result.rationale
    assert "100" in result.rationale


# --- Aggregates -------------------------------------------------------------


def test_tonnage_is_load_times_reps_times_sets():
    assert compute_tonnage([session(load=100, reps=5, sets=3)]) == 1500.0


def test_tonnage_treats_missing_sets_as_one():
    assert compute_tonnage([session(load=100, reps=5, sets=None)]) == 500.0


def test_personal_records_track_the_best_estimate_per_exercise():
    history = [
        session(exercise="barbell back squat", load=100, reps=5, day_offset=0),
        session(exercise="barbell back squat", load=110, reps=5, day_offset=7),
        session(exercise="barbell bench press", load=80, reps=5, day_offset=7),
    ]
    records = find_personal_records(history)
    assert records["barbell back squat"]["load_kg"] == 110
    assert "barbell bench press" in records
