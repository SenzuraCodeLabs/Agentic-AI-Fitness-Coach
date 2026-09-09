# Responsible AI

Every row names a control that exists in the code and an artefact that
demonstrates it. Nothing aspirational is listed: a principle without an
implementation is a claim, not a control.

---

## 1. Safety

| Principle | Implementation | File | Evidence |
| --- | --- | --- | --- |
| Never give training advice on an acute injury | Medical intent is classified before anything else and routed to a referral | `services/agent1_gatekeeper/pipeline/intent.py` | `test_medical_concern_is_refused_with_a_referral` |
| Medical safety outranks security | Rule order in the policy matrix places medical above threat blocking | `services/agent1_gatekeeper/resources/policy_rules.yaml` | `test_medical_outranks_security` |
| Recall over precision for injury detection | Medical patterns are deliberately broad; a false referral costs one message, a missed injury costs more | `intent.py`, `_ACUTE_MEDICAL` | 30 medical cases in `eval/gatekeeper/benchmark.jsonl` |
| No pharmacological advice | Rule DM-001 flags steroid and SARM dosing requests | `resources/threat_rules.yaml` | Benchmark cases in the adversarial class |
| Disordered eating is refused, not coached | Separate detection path with a referral message | `intent.py`, `_DISORDERED_EATING` | `SAFE-EATING` policy rule |
| Numbers a user acts on are never generated | All loads, reps and progressions come from pure functions; the LLM only phrases them | `services/agent3_coach/overload.py` | `tests/coach/test_overload.py`, 25 tests asserting exact values |

---

## 2. Transparency and explainability

| Principle | Implementation | File | Evidence |
| --- | --- | --- | --- |
| A user can see why a decision was made | Per-reply panel showing intent, risk score, per-signal breakdown, policy rule and sources | `web/components/TransparencyPanel.tsx` | Screenshot in the report; verified in a browser |
| Every decision is reconstructable | Each layer returns a trace record with timings, reason codes and transformations | `services/agent1_gatekeeper/pipeline/base.py` | `test_every_layer_appears_in_the_trace` |
| Traces are retrievable after the fact | `GET /api/explain/{message_id}` returns the full per-layer trace | `services/gateway/main.py` | Verified live: returns all 8 layers |
| Claims are grounded in sources | Every retrieved chunk carries an attribution, shown with the reply | `services/agent2_researcher/corpus.py` | `test_every_returned_chunk_carries_its_source` |
| Irrelevant citations are not offered | A measured relevance threshold drops weak matches | `services/agent2_researcher/retrieval.py` | `test_unrelated_query_returns_little_or_nothing` |
| Detector versions travel with decisions | `detector_versions` is inside the signed trust block | `shared/contracts/envelope.py` | Present in every envelope |

---

## 3. Privacy

| Principle | Implementation | File | Evidence |
| --- | --- | --- | --- |
| Personal data never reaches a third party | Redaction runs before the only external call in the pipeline | `pipeline/l6_pii_redactor.py`, `orchestrator.py` | `test_redaction_precedes_any_external_call` intercepts the judge and asserts on what it received |
| Redaction is reversible only for the owner | An in-memory vault scoped to the request, never persisted | `l6_pii_redactor.py` | `test_rehydration_restores_the_original` |
| Traces do not retain the redacted value | The transformation record stores the placeholder, not the original | `l6_pii_redactor.py` | `test_the_trace_does_not_record_the_original_value` |
| The audit log holds no message content | Reason codes and rule ids only | `pipeline/l8_envelope.py` | Documented in ADR 0006 |
| Logs hold no personal data | Email logging records the domain only | `services/gateway/email.py` | Log scan in `docs/security-review.md`: zero addresses found |
| One user cannot read another's data | `/api/explain` is scoped to the requesting user; `subject` is inside the signed region | `services/gateway/main.py`, `shared/contracts/envelope.py` | `test_subject_is_covered_by_the_signature` |
| Traces expire | 30-day TTL index on decision traces | `shared/db.py` | Index definition |

---

## 4. Honesty

| Principle | Implementation | File | Evidence |
| --- | --- | --- | --- |
| Never fabricate a missing value | Absent fields stay `None` and lower the confidence score | `pipeline/l4_extractor.py` | `test_missing_values_stay_none` |
| Ask rather than guess | Confidence below 0.55 produces a clarifying question | `l4_extractor.py`, `policy_rules.yaml` | `test_low_confidence_log_asks_for_clarification` |
| Implausible data is rejected, not clamped | Contract validation refuses a 5000 kg squat outright | `shared/contracts/envelope.py` | `test_implausible_load_is_rejected` |
| Out-of-range values are discarded | An RPE of 47 becomes `None` rather than being clipped to 10 | `l4_extractor.py` | `test_out_of_range_rpe_is_discarded_not_clamped` |
| Benchmark results are reported as measured | The runner prints whatever the detector produced, and lists every miss | `eval/gatekeeper/run_benchmark.py` | Missed-attack table in every results file |
| Weaknesses are documented, not hidden | Five undetected attacks analysed rather than removed from the benchmark | `docs/adr/0005-hybrid-threat-detection.md` | The ADR names each phrasing and why it evades |
| The system degrades honestly | If the LLM is unavailable the deterministic rationale is returned, so numbers stay correct | `services/agent3_coach/main.py` | Fallback path in `_phrase_recommendation` |

---

## 5. Security as a user-facing property

| Principle | Implementation | File | Evidence |
| --- | --- | --- | --- |
| A refusal reveals nothing to an attacker | Neutral messages that never name the detector | `pipeline/l7_policy_engine.py` | `test_a_block_message_does_not_name_the_detector` |
| Rejections give no oracle | Every envelope rejection returns an identical body | `shared/errors.py` | `test_every_envelope_rejection_looks_identical_on_the_wire` |
| Failures do not silently weaken defences | The LLM judge fails closed to the cheap signals | `pipeline/l5_threat_scorer.py` | `test_judge_failure_falls_back_to_cheap_signals` |
| A detector cannot be argued down | The judge may only raise a risk score | `l5_threat_scorer.py` | `test_judge_can_only_raise_the_score` |
| User text is data, never instructions | Spotlight delimiters with an explicit framing instruction | `shared/contracts/envelope.py`, `l8_envelope.py` | The judge classified an instruction aimed at itself as an attack |
| Account existence is not disclosed | Identical responses and comparable timing | `services/gateway/auth.py` | Verified live |

---

## 6. Fairness and access

| Principle | Implementation | File | Evidence |
| --- | --- | --- | --- |
| Domain vocabulary is not penalised | 619 jargon variants recognised, so abbreviation does not raise risk | `pipeline/l3_lexicon.py` | 60 jargon-heavy benchmark cases, zero false positives |
| Over-refusal is measured, not assumed | A false-positive rate on benign classes is a headline metric | `eval/gatekeeper/run_benchmark.py` | FPR 0.000 across 150 benign cases |
| Shared networks are not punished | Per-user and per-IP limits are separate, so NAT does not lock out a whole building | `services/gateway/ratelimit.py` | Documented in the module |
| Time zones are respected | "Yesterday" resolves against the user's zone, not the server's | `pipeline/l4_extractor.py` | `test_timezone_is_honoured_without_error` |
| Users can opt out of email | The digest query filters on the flag rather than checking it in code | `services/gateway/digest.py` | Filter is part of the database query |

---

## 7. Known limitations

Listed because a responsible-AI section that claims no weaknesses is not
credible.

| Limitation | Where documented |
| --- | --- |
| Five of 90 adversarial inputs evade detection | ADR 0005, with each phrasing analysed |
| The audit chain is tamper-evident, not tamper-proof | ADR 0006 |
| One symmetric key shared by all agents | ADR 0001, `docs/protocol.md` |
| Rate limiting fails open on a database outage | `docs/security-review.md` section 7.1 |
| Refresh token in `localStorage` | `docs/security-review.md` section 3.1 |
| Corpus is 20 curated chunks, not a comprehensive literature base | `services/agent2_researcher/corpus.py` |
| The intent classifier is rule-based, so it misses phrasings a model would catch | `pipeline/intent.py` module docstring |
