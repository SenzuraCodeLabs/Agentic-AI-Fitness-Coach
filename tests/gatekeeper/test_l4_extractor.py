"""L4 extraction: correctness, and the rule that it must never invent data."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.agent1_gatekeeper.pipeline.l4_extractor import (
    CONFIDENCE_THRESHOLD,
    extract,
)


def test_single_exercise_is_extracted():
    result = extract("Squatted 100kg for 5 reps today")
    assert len(result.sets_logged) == 1
    logged = result.sets_logged[0]
    assert logged.exercise == "barbell back squat"
    assert logged.load_kg == 100.0
    assert logged.reps == 5


def test_values_bind_to_the_correct_exercise():
    """The core extraction problem: two exercises, two loads.

    A nearest-number heuristic gets this wrong.
    """
    result = extract("squats 100kg for 5, then bench 60kg for 8")
    assert len(result.sets_logged) == 2

    by_exercise = {s.exercise: s for s in result.sets_logged}
    assert by_exercise["barbell back squat"].load_kg == 100.0
    assert by_exercise["barbell back squat"].reps == 5
    assert by_exercise["barbell bench press"].load_kg == 60.0
    assert by_exercise["barbell bench press"].reps == 8


def test_prescription_before_the_exercise_is_captured():
    """ "3x5 squats" puts sets and reps in front of the exercise."""
    result = extract("did 3x5 squats at 100kg")
    logged = result.sets_logged[0]
    assert logged.sets == 3
    assert logged.reps == 5
    assert logged.load_kg == 100.0


def test_sets_of_reps_phrasing():
    result = extract("OHP 3 sets of 8 at 45kg")
    logged = result.sets_logged[0]
    assert logged.sets == 3
    assert logged.reps == 8


def test_pounds_are_converted_to_kilograms():
    result = extract("benched 225 lbs for 5 reps")
    logged = result.sets_logged[0]
    # 225 lb = 102.058 kg, rounded to the nearest 0.25
    assert logged.load_kg == 102.0
    assert logged.unit_original == "lb"


def test_conversion_rounds_to_plate_increments():
    result = extract("squatted 100 lbs")
    assert result.sets_logged[0].load_kg % 0.25 == 0


def test_rpe_is_captured():
    result = extract("squats 100kg 3x5 RPE 8")
    assert result.sets_logged[0].rpe == 8.0


def test_rir_is_captured():
    result = extract("OHP 45kg 3 sets of 8, 2 RIR")
    assert result.sets_logged[0].rir == 2


def test_out_of_range_rpe_is_discarded_not_clamped():
    """RPE is defined on 1-10. Clamping would hide a parse error."""
    result = extract("squats 100kg 3x5 RPE 47")
    assert result.sets_logged[0].rpe is None


def test_bodyweight_exercises_are_recognised():
    result = extract("did some pullups bodyweight for 12")
    logged = result.sets_logged[0]
    assert logged.unit_original == "bodyweight"
    assert logged.reps == 12


# --- The honesty rules ------------------------------------------------------


def test_missing_values_stay_none():
    """Never fabricate. An invented value corrupts training history silently."""
    result = extract("squatted 100kg today")
    logged = result.sets_logged[0]
    assert logged.reps is None
    assert logged.sets is None
    assert "reps" in result.missing_fields


def test_no_exercise_gives_zero_confidence():
    result = extract("went to the gym and had a good time")
    assert result.confidence == 0.0
    assert result.sets_logged == []
    assert "exercise" in result.missing_fields


def test_sparse_input_falls_below_the_clarify_threshold():
    """The policy engine turns this into a question, not a guess."""
    result = extract("squatted today")
    assert result.confidence < CONFIDENCE_THRESHOLD
    assert not result.is_confident


def test_complete_input_scores_high_confidence():
    result = extract("deadlift 180kg 1x3 yesterday")
    assert result.confidence >= CONFIDENCE_THRESHOLD
    assert result.is_confident


def test_implausible_load_is_rejected():
    """The contract validator rejects it rather than clamping."""
    result = extract("squatted 5000kg for 5 reps")
    assert result.sets_logged == []


# --- Dates ------------------------------------------------------------------


def test_yesterday_resolves_to_the_previous_day():
    result = extract("squatted 100kg yesterday", timezone="UTC")
    today = datetime.now(UTC).date()
    assert result.session_date is not None
    assert (today - result.session_date.date()).days == 1


def test_missing_date_defaults_to_today_and_is_recorded():
    """A default must be visible in the trace, not silent."""
    result = extract("squatted 100kg for 5")
    assert result.session_date is not None
    kinds = {t.kind for t in result.trace.transformations}
    assert "date_defaulted" in kinds


def test_relative_weekday_is_resolved():
    result = extract("deadlift 180kg last monday", timezone="UTC")
    assert result.session_date is not None
    assert result.session_date <= datetime.now(UTC)


def test_days_ago_is_resolved():
    result = extract("benched 80kg 3 days ago", timezone="UTC")
    today = datetime.now(UTC).date()
    assert (today - result.session_date.date()).days == 3


@pytest.mark.parametrize("tz", ["UTC", "Asia/Colombo", "America/New_York"])
def test_timezone_is_honoured_without_error(tz):
    result = extract("squatted 100kg yesterday", timezone=tz)
    assert result.session_date is not None


def test_invalid_timezone_falls_back_safely():
    result = extract("squatted 100kg yesterday", timezone="Not/AZone")
    assert result.session_date is not None


# --- Trace ------------------------------------------------------------------


def test_trace_records_confidence_for_explainability():
    result = extract("squats 100kg 3x5")
    assert result.trace is not None
    assert "confidence" in result.trace.notes
    assert result.trace.duration_ms >= 0


def test_empty_input_is_safe():
    result = extract("")
    assert result.sets_logged == []
    assert result.confidence == 0.0
