"""Intent classification.

Deliberately rule-based rather than an LLM call. Three reasons:

  1. Latency. Intent is needed on every request; an API call would add ~1s to
     every message including the trivial ones.
  2. Determinism. The policy engine conditions on intent, so a classifier that
     returns different answers for the same input would make safety behaviour
     non-reproducible and untestable.
  3. Auditability. A viva question about why a message was classified as
     MEDICAL_CONCERN has a concrete answer: this pattern matched.

The trade-off is coverage: rules miss phrasings a model would catch. That is
acceptable because misclassification is not a safety failure here. Medical
detection is the one place where a miss matters, so those patterns are
deliberately broad and the class is checked FIRST, accepting false positives in
exchange for not missing an injury report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from services.agent1_gatekeeper.pipeline.base import LayerTrace, Timer
from shared.contracts.enums import Intent, ReasonCode

LAYER_VERSION = "intent-1.0"


# --- Medical: checked first, tuned for recall over precision ---------------
# A false positive costs one unnecessary referral message. A false negative
# means giving training advice to someone describing an acute injury.

_ACUTE_MEDICAL = re.compile(
    r"(?i)\b("
    r"sharp pain|severe pain|shooting pain|stabbing pain|"
    r"heard (?:a )?(?:pop|crack|snap|click)|felt (?:a )?(?:pop|tear|snap)|"
    r"can(?:no|')?t (?:walk|stand|move|lift|breathe)|"
    r"numb(?:ness)?|tingling|pins and needles|"
    r"dislocat|fracture|broken bone|torn|rupture|herniat|"
    r"chest pain|difficulty breathing|short(?:ness)? of breath|"
    r"dizzy|dizziness|fainted|passed out|blacked out|vomit|"
    r"swollen|swelling|bruis|blood in|bleeding|"
    r"concussion|head injury|"
    r"emergency|hospital|a&e|urgent care"
    r")\b"
)

_MEDICAL_CONTEXT = re.compile(
    r"(?i)\b("
    r"diagnos|prescri|medication|medicine|painkiller|anti-inflammator|"
    r"physio(?:therap)?|doctor|surgeon|specialist|clinic|"
    r"tendinitis|tendonitis|bursitis|arthritis|sciatica|impingement|"
    r"disc|hernia|acl|mcl|meniscus|rotator cuff tear|"
    r"diabetes|blood pressure|heart condition|asthma|epilep|"
    r"injury|injured|rehab|recovery from"
    r")\b"
)

_DISORDERED_EATING = re.compile(
    r"(?i)("
    r"\b(?:not|haven'?t|have not)\s+eat(?:en|ing)\b|"
    r"\bstop(?:ped)?\s+eating\b|"
    r"\blose\s+\d{2,}\s*(?:kg|kgs|kilos|lbs|pounds)\b[^.!?]{0,30}\b(?:in|within)\b[^.!?]{0,20}\b(?:day|week)|"
    r"\beating disorder|anorexi|bulimi|purge|purging\b|"
    r"\bstarv(?:e|ing|ation)\b"
    r")"
)

# --- Workout logging -------------------------------------------------------

_LOG_VERBS = re.compile(
    r"(?i)\b("
    r"squatted|benched|deadlifted|pressed|lifted|trained|"
    r"did|done|hit|completed|finished|logged|smashed|"
    r"performed|managed|worked"
    r")\b"
)

_LOG_STRUCTURE = re.compile(
    r"(?i)("
    r"\b\d{1,2}\s*[x×]\s*\d{1,3}\b|"  # 3x5
    r"\b\d{1,4}(?:\.\d+)?\s*(?:kg|kgs|lb|lbs|kilos?|pounds?)\b|"
    r"\b\d{1,2}\s*sets?\b|\b\d{1,3}\s*reps?\b|"
    r"\brpe\s*\d|\b\d\s*rir\b"
    r")"
)

# --- Questions -------------------------------------------------------------

# "did" is deliberately absent from the sentence-initial list. It is ambiguous:
# "did you know" is a question, but "did 3x5 squats at 100kg" is a workout log,
# and the log reading is overwhelmingly more common in this app. Including it
# made every "did ..." log classify as a query, which sent real training data
# to the wrong handler. A trailing question mark still marks those as questions.
_QUESTION_MARKERS = re.compile(
    r"(?i)^\s*(what|how|why|when|where|which|who|should|can|could|would|"
    r"is|are|does|will|explain|tell me|help me|give me|show me)\b|\?"
)

_FORM_QUERY = re.compile(
    r"(?i)\b(form|technique|how (?:do|to)|cue|setup|grip|stance|depth|"
    r"bar path|breathing|brac|posture|position|execut)\b"
)

_PROGRESS_QUERY = re.compile(
    r"(?i)\b(my progress|progress(?:ing|ed)?|history|last (?:week|month|session)|"
    r"how much have i|am i (?:getting|improving)|tonnage|volume over|"
    r"personal record|pr history|show me my|track)\b"
)

_PROGRAM_QUERY = re.compile(
    r"(?i)\b(program|programme|routine|split|plan|next week|periodis|periodiz|"
    r"deload|progress(?:ion)?|overload|what should i|how many sets|"
    r"rep range|frequency|volume|accessor|stall)\b"
)

# --- Out of scope ----------------------------------------------------------
# Positive detection of clearly non-fitness topics. A message with no fitness
# vocabulary AND a match here is out of domain.

_OFF_DOMAIN = re.compile(
    r"(?i)\b("
    r"capital of|president|prime minister|world cup|election|"
    r"weather|forecast|recipe|cook|bake|"
    r"python|javascript|code|script|programming language|blockchain|crypto|"
    r"stock|invest|shares|"
    r"translate|poem|joke|film|movie|song|"
    r"visa|passport application|"
    r"square root|equation|"
    r"history of|roman empire|photosynthesis|quantum"
    r")\b"
)

_FITNESS_VOCAB = re.compile(
    r"(?i)\b("
    r"squat|bench|deadlift|press|curl|row|pull ?up|push ?up|dip|lunge|"
    r"gym|train|workout|exercise|lift|rep|set|muscle|"
    r"kg|lbs|rpe|rir|1rm|pr|hypertroph|strength|cardio|"
    r"protein|macro|calorie|bulk|cut|deload|volume|tempo|"
    r"quad|hamstring|glute|delt|lat|bicep|tricep|pec|trap|chest|back|leg|arm|shoulder"
    r")\b"
)

_SMALL_TALK = re.compile(
    r"(?i)^\s*(hi|hey|heya|hiya|hello|yo|sup|good (?:morning|afternoon|evening)|"
    r"morning|thanks|thank you|ty|cheers|ok|okay|k|cool|nice|great|awesome|"
    r"bye|goodbye|see ya|later|how are you|whats up|what's up)"
    r"\b[\s!.,?]*(there|mate|coach|buddy)?[\s!.,?]*$"
)

# Past-tense training verbs. Their presence signals a LOG even with no numbers:
# "squatted today" is a report of a session, not a question about programming.
# It becomes a low-confidence log, which the policy engine turns into a
# clarifying question rather than a guess.
_PAST_TENSE_LOG = re.compile(
    r"(?i)\b("
    r"squatted|benched|deadlifted|pressed|lifted|trained|curled|rowed|"
    r"did|done|hit|completed|finished|logged|smashed|performed|"
    r"went to the gym|worked out"
    r")\b"
)


@dataclass(slots=True)
class IntentResult:
    intent: Intent
    confidence: float
    trace: LayerTrace | None = None


def classify_intent(expanded_text: str, original_text: str = "") -> IntentResult:
    """Classify what the user is trying to do.

    ``expanded_text`` has been through L3 so jargon is standardised;
    ``original_text`` is kept because expansion can obscure surface cues.
    """
    trace = LayerTrace(layer="intent_classifier", version=LAYER_VERSION)
    combined = f"{expanded_text} {original_text}".strip()

    with Timer(trace):
        if not combined:
            trace.notes = {"reason": "empty input"}
            return IntentResult(Intent.UNKNOWN, 0.0, trace)

        # 1. Medical first. Recall matters more than precision here.
        if _DISORDERED_EATING.search(combined):
            trace.reason_codes.append(ReasonCode.DISORDERED_EATING)
            trace.notes = {"matched": "disordered_eating"}
            return IntentResult(Intent.MEDICAL_CONCERN, 0.9, trace)

        if _ACUTE_MEDICAL.search(combined):
            trace.reason_codes.append(ReasonCode.MEDICAL_ACUTE)
            trace.notes = {"matched": "acute_medical"}
            return IntentResult(Intent.MEDICAL_CONCERN, 0.9, trace)

        if _MEDICAL_CONTEXT.search(combined):
            trace.reason_codes.append(ReasonCode.MEDICAL_CHRONIC)
            trace.notes = {"matched": "medical_context"}
            return IntentResult(Intent.MEDICAL_CONCERN, 0.75, trace)

        # 2. Small talk: cheap to detect, and short greetings would otherwise
        #    fall through to OUT_OF_SCOPE and get a needless refusal.
        #
        #    Tested against the two texts SEPARATELY, not against `combined`.
        #    The small-talk pattern is anchored to the whole string, and
        #    `combined` is the expanded text followed by the original, so a
        #    greeting arrives as "hey hey" and the anchor fails. This was a real
        #    bug: every greeting was answered with an out-of-scope refusal.
        if any(
            _SMALL_TALK.match(candidate)
            for candidate in (expanded_text.strip(), original_text.strip())
            if candidate
        ):
            trace.notes = {"matched": "small_talk"}
            return IntentResult(Intent.SMALL_TALK, 0.9, trace)

        has_fitness_vocab = bool(_FITNESS_VOCAB.search(combined))

        # 3. Out of scope: off-domain topic AND no fitness vocabulary. Both
        #    conditions are required, so "what is the best programming language
        #    for a gym app" is not misrouted.
        if _OFF_DOMAIN.search(combined) and not has_fitness_vocab:
            trace.reason_codes.append(ReasonCode.OUT_OF_DOMAIN)
            trace.notes = {"matched": "off_domain"}
            return IntentResult(Intent.OUT_OF_SCOPE, 0.85, trace)

        is_question = bool(_QUESTION_MARKERS.search(combined))

        # 4. A workout log: a logging verb or numeric structure, and not framed
        #    as a question. "squats 100kg for 5" logs; "how much should I
        #    squat?" asks.
        has_structure = bool(_LOG_STRUCTURE.search(combined))
        has_log_verb = bool(_LOG_VERBS.search(combined))
        has_past_tense = bool(_PAST_TENSE_LOG.search(combined))

        if has_fitness_vocab and has_structure and not is_question:
            confidence = 0.9 if has_log_verb else 0.75
            trace.notes = {"matched": "workout_log", "structure": True}
            return IntentResult(Intent.LOG_WORKOUT, confidence, trace)

        # A past-tense training verb with no numbers is still a log attempt.
        # Routing it to LOG_WORKOUT is what lets L7 see the low extraction
        # confidence and ask a clarifying question, instead of treating a
        # half-stated session as a programming query.
        if has_fitness_vocab and has_past_tense and not is_question:
            trace.notes = {"matched": "workout_log", "structure": False}
            return IntentResult(Intent.LOG_WORKOUT, 0.6, trace)

        # 5. Question subtypes, most specific first.
        if is_question or has_fitness_vocab:
            if _PROGRESS_QUERY.search(combined):
                trace.notes = {"matched": "progress_query"}
                return IntentResult(Intent.PROGRESS_QUERY, 0.8, trace)
            if _FORM_QUERY.search(combined):
                trace.notes = {"matched": "form_query"}
                return IntentResult(Intent.EXERCISE_FORM, 0.8, trace)
            if _PROGRAM_QUERY.search(combined):
                trace.notes = {"matched": "program_query"}
                return IntentResult(Intent.PROGRAM_QUERY, 0.8, trace)
            if has_fitness_vocab:
                trace.notes = {"matched": "generic_fitness"}
                return IntentResult(Intent.PROGRAM_QUERY, 0.6, trace)

        # 6. No fitness signal at all.
        if not has_fitness_vocab:
            trace.reason_codes.append(ReasonCode.OUT_OF_DOMAIN)
            trace.notes = {"matched": "no_fitness_signal"}
            return IntentResult(Intent.OUT_OF_SCOPE, 0.6, trace)

        trace.reason_codes.append(ReasonCode.LOW_CONFIDENCE)
        trace.notes = {"matched": "none"}
        return IntentResult(Intent.UNKNOWN, 0.3, trace)
