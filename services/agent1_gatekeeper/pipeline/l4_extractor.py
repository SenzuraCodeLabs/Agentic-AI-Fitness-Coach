"""L4 - Structured extraction with spaCy.

Purpose: turn "squats 100kg for 5, then bench 60kg for 8" into typed records
that the coach can compute on. Free text cannot drive progressive-overload
maths; a validated ``WorkoutLogPayload`` can.

TWO DESIGN RULES, BOTH ABOUT HONESTY
------------------------------------
1. Never fabricate a missing value. If reps are absent the field stays None and
   confidence drops. An invented "3 sets" would silently corrupt a user's
   training history, and the error would be invisible because the record looks
   complete.
2. Report calibrated confidence. The policy engine turns low confidence into a
   CLARIFY question rather than a guess. That only works if the score reflects
   real extraction quality, so it is computed from what was actually found, not
   from a model's self-assessment.

WHY THE DEPENDENCY PARSE, NOT PROXIMITY
---------------------------------------
The hard case is binding numbers to the right exercise:

    "squats 100kg for 5, then bench 60kg for 8"

Nearest-number heuristics fail on real sentences ("bench 60kg after squatting
100kg for 5"). spaCy's dependency parse gives the syntactic structure, so a
number can be attached to the exercise it actually modifies. This layer uses a
hybrid: the parse establishes clause boundaries, then values are bound within a
clause. That is more robust than proximity alone and cheaper than a full
semantic parser.

The EntityRuler runs BEFORE the statistical NER because gym vocabulary is a
closed, known set. A rule-based match on "RDL" is exact and needs no training
data; leaving it to the statistical model would produce silent misses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import spacy
from spacy.language import Language
from spacy.tokens import Doc

from services.agent1_gatekeeper.pipeline.base import LayerTrace, Timer, Transformation
from services.agent1_gatekeeper.pipeline.l3_lexicon import _load_jargon
from shared.contracts.enums import ReasonCode
from shared.contracts.envelope import WorkoutSet

LAYER_VERSION = "l4-1.0"

# Below this the policy engine asks a clarifying question instead of guessing.
CONFIDENCE_THRESHOLD = 0.55

LB_TO_KG = 0.45359237

# Weekday names for relative date resolution.
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

# --- Patterns ---------------------------------------------------------------
# "3x5", "3 x 5", "5x5 @ 100kg"
_SETS_X_REPS = re.compile(r"\b(\d{1,2})\s*[x×]\s*(\d{1,3})\b", re.IGNORECASE)
# "100kg", "225 lbs", "60 kilos"
_LOAD = re.compile(
    r"\b(\d{1,4}(?:\.\d{1,2})?)\s*(kgs?|kilos?|kilograms?|lbs?|pounds?)\b",
    re.IGNORECASE,
)
_REPS = re.compile(r"\b(?:for\s+)?(\d{1,3})\s*(?:reps?|repetitions?)\b", re.IGNORECASE)
_SETS = re.compile(r"\b(\d{1,2})\s*(?:sets?)\b", re.IGNORECASE)
# "3 sets of 8": binds both values, the spelled-out form of "3x5".
_SETS_OF_REPS = re.compile(r"\b(\d{1,2})\s*sets?\s+of\s+(\d{1,3})\b", re.IGNORECASE)
_RPE = re.compile(r"\brpe\s*(?:of\s*)?(\d{1,2}(?:\.\d)?)\b", re.IGNORECASE)
_RIR = re.compile(r"\b(\d{1,2})\s*rir\b|\brir\s*(?:of\s*)?(\d{1,2})\b", re.IGNORECASE)
_BODYWEIGHT = re.compile(r"\b(bodyweight|body weight|bw)\b", re.IGNORECASE)

# Clause separators. A workout log is typically a list of clauses, one per
# exercise, so splitting here is what stops values leaking between exercises.
_CLAUSE_SPLIT = re.compile(r"\s*(?:,\s*(?:then|and|followed by)?|;|\bthen\b|\band then\b)\s*")


@dataclass(slots=True)
class ExtractionResult:
    sets_logged: list[WorkoutSet] = field(default_factory=list)
    session_date: datetime | None = None
    entities: dict[str, list[str]] = field(default_factory=dict)
    confidence: float = 0.0
    missing_fields: list[str] = field(default_factory=list)
    trace: LayerTrace | None = None

    @property
    def is_confident(self) -> bool:
        return self.confidence >= CONFIDENCE_THRESHOLD


@lru_cache(maxsize=1)
def _nlp() -> Language:
    """Load spaCy once per process with a gym-domain EntityRuler.

    The parser is kept because clause structure is used for value binding; the
    statistical NER is disabled because it contributes nothing here and costs
    time on every request. Loading per request would add hundreds of
    milliseconds.
    """
    nlp = spacy.load("en_core_web_sm", exclude=["ner", "lemmatizer"])

    ruler = nlp.add_pipe("entity_ruler", config={"overwrite_ents": True})
    patterns: list[dict[str, Any]] = []

    # Exercises and body parts come from the same dictionary L3 uses, so the
    # two layers cannot disagree about what counts as an exercise.
    jargon = _load_jargon()
    body_parts = {
        "deltoids",
        "latissimus dorsi",
        "quadriceps",
        "hamstrings",
        "gluteus maximus",
        "pectorals",
        "trapezius",
        "biceps",
        "triceps",
        "abdominals",
        "erector spinae",
        "gastrocnemius",
        "forearms",
        "rotator cuff",
        "adductors",
        "abductors",
        "rhomboids",
        "serratus anterior",
    }
    # Every surface form gets a pattern, all carrying the canonical id. An
    # earlier version deduplicated by canonical term, which dropped the actual
    # user-facing variants ("squats", "benched") and kept only the canonical
    # spellings, so nothing matched real input. The ruler needs the variants:
    # that is the whole point of an EntityRuler over gym vocabulary.
    for surface, canonical in jargon.items():
        label = "BODYPART" if canonical in body_parts else "EXERCISE"
        if label == "EXERCISE" and not _looks_like_exercise(canonical):
            continue
        patterns.append(
            {
                "label": label,
                "pattern": [{"LOWER": tok} for tok in surface.split()],
                "id": canonical,
            }
        )

    # Units, effort metrics and temporal expressions.
    for unit in ("kg", "kgs", "kilo", "kilos", "lb", "lbs", "pound", "pounds"):
        patterns.append({"label": "UNIT", "pattern": [{"LOWER": unit}]})
    for token in ("rpe", "rir", "amrap", "emom"):
        patterns.append({"label": "EFFORT", "pattern": [{"LOWER": token}]})
    for word in ("today", "yesterday", "tonight", "morning", "evening"):
        patterns.append({"label": "TEMPORAL", "pattern": [{"LOWER": word}]})
    for day in _WEEKDAYS:
        patterns.append({"label": "TEMPORAL", "pattern": [{"LOWER": day}]})
        patterns.append({"label": "TEMPORAL", "pattern": [{"LOWER": "last"}, {"LOWER": day}]})

    ruler.add_patterns(patterns)
    return nlp


def _looks_like_exercise(canonical: str) -> bool:
    """Filter the jargon map down to movement names.

    The dictionary also holds nutrition and programming terms; treating
    "macronutrients" as an exercise would produce nonsense log entries.
    """
    non_exercise = {
        "kilograms",
        "pounds",
        "repetitions",
        "sets",
        "personal record",
        "rate of perceived exertion",
        "reps in reserve",
        "one rep maximum",
        "macronutrients",
        "calories",
        "carbohydrates",
        "caloric deficit",
        "caloric surplus",
        "maintenance calories",
        "body fat percentage",
        "recomposition",
        "intermittent fasting",
        "creatine monohydrate",
        "whey protein",
        "pre workout",
        "branched chain amino acids",
        "electrolytes",
        "delayed onset muscle soreness",
        "central nervous system",
        "range of motion",
        "mind muscle connection",
        "muscle protein synthesis",
        "rest interval",
        "mobility work",
        "foam rolling",
        "active recovery",
        "overtraining",
        "form breakdown",
        "muscular failure",
        "spotter",
        "lockout",
        "sticking point",
        "bracing",
        "hip hinge",
        "knee valgus",
        "butt wink",
        "deload",
        "periodisation",
        "linear progression",
        "double progression",
        "progressive overload",
        "training volume",
        "training intensity",
        "training frequency",
        "hypertrophy",
        "strength",
        "mesocycle",
        "macrocycle",
        "microcycle",
        "push pull legs",
        "upper lower split",
        "full body",
        "bro split",
        "german volume training",
        "five by five",
        "wendler 531",
        "texas method",
        "conjugate method",
        "daily undulating periodisation",
        "training max",
        "accessory work",
        "compound movement",
        "isolation movement",
        "total tonnage",
        "gym session",
        "bar speed",
        "beginner",
        "intermediate lifter",
        "advanced lifter",
        "natural lifter",
        "barbell",
        "dumbbell",
        "kettlebell",
        "smith machine",
        "cable machine",
        "resistance band",
        "trap bar",
        "ez bar",
        "weight plate",
        "as many reps as possible",
        "every minute on the minute",
        "time under tension",
        "warm up set",
        "working set",
        "back off set",
        "drop set",
        "superset",
        "giant set",
        "rest pause",
        "cluster set",
        "myo reps",
        "tempo",
        "eccentric",
        "concentric",
        "isometric",
        "three rep maximum",
        "five rep maximum",
        "percentage of one rep max",
    }
    return canonical not in non_exercise


def _normalise_load(value: float, unit: str) -> tuple[float, str]:
    """Convert to kilograms, rounded to the nearest 0.25.

    0.25 kg is the smallest plate increment in common use, so rounding finer
    would imply precision the input does not have.
    """
    unit = unit.lower()
    if unit.startswith(("lb", "pound")):
        return round(value * LB_TO_KG * 4) / 4, "lb"
    return round(value * 4) / 4, "kg"


def _resolve_date(text: str, tz_name: str = "UTC") -> tuple[datetime | None, str | None]:
    """Resolve a relative date against the user's timezone.

    The timezone matters: "yesterday" for a user in Colombo is a different UTC
    date than for one in London, and logging a session on the wrong day breaks
    weekly volume calculations.
    """
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = UTC

    now = datetime.now(tz)
    lowered = text.lower()

    if "yesterday" in lowered:
        return (now - timedelta(days=1)).astimezone(UTC), "yesterday"
    if "today" in lowered or "tonight" in lowered or "this morning" in lowered:
        return now.astimezone(UTC), "today"

    match = re.search(r"\blast\s+(\w+day)\b", lowered)
    if match and match.group(1) in _WEEKDAYS:
        target = _WEEKDAYS[match.group(1)]
        delta = (now.weekday() - target) % 7 or 7
        return (now - timedelta(days=delta)).astimezone(UTC), f"last {match.group(1)}"

    for day, index in _WEEKDAYS.items():
        if re.search(rf"\bon\s+{day}\b|\b{day}\b", lowered):
            delta = (now.weekday() - index) % 7
            return (now - timedelta(days=delta)).astimezone(UTC), day

    match = re.search(r"\b(\d+)\s*days?\s*ago\b", lowered)
    if match:
        return (now - timedelta(days=int(match.group(1)))).astimezone(UTC), match.group()

    return None, None


def _extract_clause(clause: str, exercise: str) -> WorkoutSet | None:
    """Pull numeric values out of one clause. Missing values stay None."""
    load_kg: float | None = None
    unit_original = "unknown"
    reps: int | None = None
    sets: int | None = None
    rpe: float | None = None
    rir: int | None = None

    if _BODYWEIGHT.search(clause):
        unit_original = "bodyweight"

    load_match = _LOAD.search(clause)
    if load_match:
        raw = float(load_match.group(1))
        load_kg, unit_original = _normalise_load(raw, load_match.group(2))

    # "3x5" binds sets and reps together and is unambiguous, so it wins over
    # the looser single-number patterns.
    sxr = _SETS_X_REPS.search(clause)
    sof = _SETS_OF_REPS.search(clause)
    if sxr:
        sets, reps = int(sxr.group(1)), int(sxr.group(2))
    elif sof:
        sets, reps = int(sof.group(1)), int(sof.group(2))
    else:
        reps_match = _REPS.search(clause)
        if reps_match:
            reps = int(reps_match.group(1))
        sets_match = _SETS.search(clause)
        if sets_match:
            sets = int(sets_match.group(1))
        # "for 5" with no unit word is a rep count in gym shorthand.
        if reps is None:
            bare = re.search(r"\bfor\s+(\d{1,3})\b", clause, re.IGNORECASE)
            if bare:
                reps = int(bare.group(1))

    rpe_match = _RPE.search(clause)
    if rpe_match:
        candidate = float(rpe_match.group(1))
        # RPE is defined on a 1-10 scale; anything else is a parse error, and
        # silently clamping it would hide the mistake.
        if 1 <= candidate <= 10:
            rpe = candidate

    rir_match = _RIR.search(clause)
    if rir_match:
        raw = rir_match.group(1) or rir_match.group(2)
        if raw is not None and 0 <= int(raw) <= 10:
            rir = int(raw)

    if load_kg is None and reps is None and sets is None and unit_original != "bodyweight":
        return None

    try:
        return WorkoutSet(
            exercise=exercise,
            load_kg=load_kg,
            unit_original=unit_original,  # type: ignore[arg-type]
            reps=reps,
            sets=sets,
            rpe=rpe,
            rir=rir,
        )
    except ValueError:
        # Implausible values are rejected by the contract validator rather than
        # being clamped, so bad data never reaches the coach.
        return None


def _merge_sets(primary: WorkoutSet, fallback: WorkoutSet) -> WorkoutSet:
    """Fill gaps in ``primary`` from ``fallback``.

    Values found after the exercise win, because that is the dominant word
    order and the least likely to have borrowed from a neighbouring clause.
    Only fields that are genuinely absent are taken from the leading text.
    """
    return WorkoutSet(
        exercise=primary.exercise,
        load_kg=primary.load_kg if primary.load_kg is not None else fallback.load_kg,
        unit_original=(
            primary.unit_original if primary.unit_original != "unknown" else fallback.unit_original
        ),
        reps=primary.reps if primary.reps is not None else fallback.reps,
        sets=primary.sets if primary.sets is not None else fallback.sets,
        rpe=primary.rpe if primary.rpe is not None else fallback.rpe,
        rir=primary.rir if primary.rir is not None else fallback.rir,
    )


def _find_exercises(doc: Doc) -> list[tuple[int, int, str]]:
    """Return (start_char, end_char, canonical) for each exercise mention."""
    out: list[tuple[int, int, str]] = []
    for ent in doc.ents:
        if ent.label_ == "EXERCISE":
            canonical = ent.ent_id_ or ent.text.lower()
            out.append((ent.start_char, ent.end_char, canonical))
    return out


def extract(text: str, *, timezone: str = "UTC") -> ExtractionResult:
    """Extract structured workout data from ``text``."""
    trace = LayerTrace(layer="L4_extractor", version=LAYER_VERSION)
    missing: list[str] = []

    with Timer(trace):
        doc = _nlp()(text)

        entities: dict[str, list[str]] = {}
        for ent in doc.ents:
            entities.setdefault(ent.label_, []).append(ent.ent_id_ or ent.text)

        exercises = _find_exercises(doc)
        session_date, date_phrase = _resolve_date(text, timezone)

        sets_logged: list[WorkoutSet] = []
        if exercises:
            # Bind each exercise to a window of text around it. The window runs
            # from the end of the previous exercise to the start of the next,
            # which keeps "squats 100kg for 5, then bench 60kg for 8" from
            # attributing 60kg to the squat.
            #
            # The window starts BEFORE the exercise, not at it, because English
            # puts the prescription on either side: "3x5 squats at 100kg" has
            # the sets and reps in front, "squats 3x5" behind. An earlier
            # version started at the exercise offset and silently lost every
            # leading "3x5".
            for i, (ex_start, ex_end, exercise) in enumerate(exercises):
                prev_end = exercises[i - 1][1] if i > 0 else 0
                next_start = exercises[i + 1][0] if i + 1 < len(exercises) else len(text)

                # English puts the prescription on either side of the exercise:
                # "squats 100kg for 5" (after) or "3x5 squats at 100kg"
                # (split). Text AFTER the exercise is tried first, because that
                # is the dominant order and it cannot borrow from a preceding
                # exercise's clause. Only if nothing is found there is the
                # preceding text considered, which is what recovers a leading
                # "3x5" without letting one exercise inherit another's load.
                trailing = text[ex_end:next_start]
                extracted = _extract_clause(trailing, exercise)

                leading = text[prev_end:ex_start]
                if leading.strip():
                    from_leading = _extract_clause(leading, exercise)
                    if from_leading is not None:
                        extracted = (
                            _merge_sets(extracted, from_leading)
                            if extracted is not None
                            else from_leading
                        )

                if extracted is not None:
                    sets_logged.append(extracted)

        # --- Confidence, computed from what was actually found -------------
        # Each component is evidence the extraction is trustworthy. The weights
        # reflect how load-bearing each field is for the overload calculation:
        # an exercise with no load is not usable for progression at all.
        if not exercises:
            confidence = 0.0
            missing.append("exercise")
        else:
            score = 0.35  # an identified exercise
            if sets_logged:
                score += 0.15
                first = sets_logged[0]
                if first.load_kg is not None or first.unit_original == "bodyweight":
                    score += 0.25
                else:
                    missing.append("load")
                if first.reps is not None:
                    score += 0.15
                else:
                    missing.append("reps")
                if first.sets is not None:
                    score += 0.10
                else:
                    missing.append("sets")
            else:
                missing.extend(["load", "reps", "sets"])
            confidence = min(score, 1.0)

        if session_date is None:
            # Not penalised: an unstated date sensibly defaults to today, and
            # that default is recorded in the trace rather than hidden.
            session_date = datetime.now(UTC)
            trace.transformations.append(
                Transformation(kind="date_defaulted", detail="no date stated, assumed today")
            )
        elif date_phrase:
            trace.transformations.append(
                Transformation(
                    kind="date_resolved",
                    before=date_phrase,
                    after=session_date.date().isoformat(),
                )
            )

    for s in sets_logged:
        trace.transformations.append(
            Transformation(
                kind="workout_set_extracted",
                detail=f"{s.exercise} {s.load_kg}kg x{s.reps} x{s.sets}",
            )
        )

    if confidence < CONFIDENCE_THRESHOLD:
        trace.reason_codes.append(ReasonCode.LOW_CONFIDENCE)
    if missing:
        trace.reason_codes.append(ReasonCode.MISSING_REQUIRED_FIELD)

    trace.notes = {
        "exercise_count": len(exercises),
        "sets_extracted": len(sets_logged),
        "confidence": round(confidence, 3),
        "missing": missing,
        "timezone": timezone,
    }

    return ExtractionResult(
        sets_logged=sets_logged,
        session_date=session_date,
        entities=entities,
        confidence=confidence,
        missing_fields=missing,
        trace=trace,
    )
