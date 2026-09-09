# Pre-submission checklist

Maps each requirement to the artefact that satisfies it. Anything not yet done
is marked and listed at the end.

Verified against commit at 2026-09-09. Re-run `pytest -q` and
`python eval/gatekeeper/run_benchmark.py --judge` before submitting, and
confirm the numbers below still hold.

---

## Group assignment

### Agentic behaviour

| Requirement | Artefact | Status |
| --- | --- | --- |
| Multiple cooperating agents | Four services, `services/` | Done |
| Agents make decisions, not just calls | `l7_policy_engine.py` decision matrix; `overload.py` six ordered rules | Done |
| Agents delegate to one another | Gateway to Gatekeeper to Coach to Researcher | Done |
| Graceful degradation | Coach returns the deterministic rationale if the LLM fails; retrieval failure yields an uncited but correct answer | Done |
| Short-circuiting | Terminal decisions make no downstream call | Done, `test_injection_is_blocked_and_short_circuits` |

### LLM integration

| Requirement | Artefact | Status |
| --- | --- | --- |
| LLM used meaningfully | Judge in L5; phrasing in Agent 3 | Done |
| Model choice justified | Fast model for the judge, strong for coaching, in `shared/config.py` | Done |
| Prompt injection defences | Spotlight delimiters, `l8_envelope.py` and `l5_threat_scorer.py` | Done |
| Cost control | Band-gated judge (19 of 300 calls), daily token quota | Done |
| Numbers are not generated | `overload.py` pure functions | Done, 25 tests |

### NLP

| Requirement | Artefact | Status |
| --- | --- | --- |
| Named entity recognition | spaCy EntityRuler, `l4_extractor.py` | Done |
| Dependency parsing | Clause windowing for value binding | Done, `test_values_bind_to_the_correct_exercise` |
| Domain lexicon | 619 jargon variants, Aho-Corasick | Done, [ADR 0003](adr/0003-aho-corasick-jargon.md) |
| Fuzzy matching | rapidfuzz with three guards | Done, [ADR 0004](adr/0004-fuzzy-correction-guards.md) |
| Normalisation | Unicode canonicalisation, `l1_canonicalise.py` | Done |
| Temporal resolution | Relative dates against the user's timezone | Done |

### Information retrieval

| Requirement | Artefact | Status |
| --- | --- | --- |
| Vector store | ChromaDB, `agent2_researcher/retrieval.py` | Done |
| Embeddings | all-MiniLM-L6-v2, shared with L5 | Done |
| Retrieval quality controls | Measured relevance threshold | Done, `retrieval.py` comment records the measurement |
| Grounded citations | Every chunk carries a source, shown in the UI | Done |
| Evaluation | `eval/gatekeeper/`, precision, recall, F1, FPR | Done |

### Security

| Requirement | Artefact | Status |
| --- | --- | --- |
| Authentication | Argon2id, JWT, refresh rotation | Done, `tests/gateway/test_auth.py` |
| Authorisation | `subject` inside the signed region; `/api/explain` scoped to the user | Done |
| Input validation | Pydantic at every boundary, size caps | Done |
| Rate limiting | Sliding window per user and per IP | Done |
| Secrets management | pydantic-settings, `SecretStr`, no secret in history | Done, verified by scan |
| Injection defence | Nine-layer pipeline | Done, F1 0.971 |
| Audit trail | Hash-chained, tamper-evident | Done, [ADR 0006](adr/0006-audit-hash-chain.md) |
| Dependency audit | pip-audit and npm audit, every finding analysed | Done, [security review](security-review.md) |

### Agent communication protocol

| Requirement | Artefact | Status |
| --- | --- | --- |
| Protocol is defined, not ad hoc | [docs/protocol.md](protocol.md) | Done |
| Message schema | `shared/contracts/envelope.py` | Done |
| Authentication between agents | HMAC-SHA256 over canonical JSON | Done |
| Replay protection | Nonce store with TTL, atomic | Done, verified live |
| Error taxonomy | RFC 7807, uniform rejections | Done |
| Traceability | One correlation ID across four services | Done, verified in logs |
| Versioning | `envelope_version`, bumped to 1.1 with an ADR | Done |

### Responsible AI

| Requirement | Artefact | Status |
| --- | --- | --- |
| Principle to implementation table | [docs/responsible-ai.md](responsible-ai.md) | Done |
| Explainability surfaced to users | Transparency panel, verified in a browser | Done |
| Safety refusals | Medical outranks security in the policy order | Done |
| Privacy | Redaction before any external call | Done, ordering test |
| Honest evaluation | Every miss reported, weaknesses in ADRs | Done |
| Limitations stated | README, responsible-ai, security review | Done |

### Commercialisation plan

| Requirement | Artefact | Status |
| --- | --- | --- |
| Market analysis, pricing, go-to-market | Not started | **TODO: yours to write** |

Cost data available: `/api/telemetry` reports real token spend per user, and
the benchmark records the judge invocation rate, so unit economics can be
computed from measurements rather than estimated.

### Documentation

| Requirement | Artefact | Status |
| --- | --- | --- |
| README with setup | [README.md](../README.md) | Done |
| Architecture diagrams | [docs/architecture.md](architecture.md) | Done |
| API reference | README table | Done |
| Design rationale | Seven ADRs | Done |
| Contributors and ownership | README table | Done |

---

## Individual assignment: vulnerability assessment

| Requirement | Artefact | Status |
| --- | --- | --- |
| Harness | `eval/redteam/` | Done |
| Evidence capture | Request, response, per-layer trace, latency, tokens | Done |
| Reproducibility | Manifest with commit and dirty-tree warning | Done |
| 15+ documented test cases | 3 worked examples provided | **TODO: 12+ more are yours to author** |
| Risk matrix | `risk_matrix.yaml`, `scoring.py` | Done |
| Your risk ratings | `ratings.yaml` | **TODO: yours to write** |
| Report in the brief's section order | `report_builder.py` | Structure done, prose TODO |
| Executive summary | Marked TODO in the draft | **TODO: yours** |
| Scope of testing | Partially templated | **TODO: complete the out-of-scope list** |
| Methodology | Harness described; case design rationale TODO | **TODO: yours** |
| Vulnerabilities identified | Auto-populated from failures | Depends on your cases |
| Quality of analysis, 25 marks | Marked TODO throughout | **TODO: yours, and must be** |
| Mitigation strategies | Controls table provided; per-finding mitigations TODO | **TODO: yours** |
| Reflection | Marked TODO | **TODO: yours** |

One finding already exists and is fully documented: the envelope rejection
oracle found by RT-EX-003, diagnosed and fixed. See `eval/redteam/README.md`.
A finding you found and fixed yourself is stronger evidence than one you only
described.

---

## Outstanding before submission

| # | Item | Why it matters |
| --- | --- | --- |
| 1 | **Rotate the three credentials** shared in a chat transcript | The DeepSeek key, Gmail app password and JWT secret should be treated as exposed |
| 2 | Author 12+ red-team cases | The brief requires 15+; three examples are provided |
| 3 | Write `ratings.yaml` | The risk matrix needs your impact and likelihood judgements |
| 4 | Write the report analysis | The 25 analysis marks are for your reasoning |
| 5 | Write the commercialisation plan | Not started |
| 6 | Tell teammates about envelope 1.1 | [ADR 0007](adr/0007-envelope-subject-field.md) is a breaking change; they must pull |
| 7 | Re-run benchmarks on the final commit | Numbers in the README must match the submitted code |

---

## Verification commands

```bash
pytest -q                                       # expect 259 passed
ruff check . && ruff format --check .           # expect clean
python eval/gatekeeper/run_benchmark.py --judge # expect P 1.000, R 0.944
python scripts/verify_audit_chain.py            # expect chain OK
python eval/redteam/run_suite.py                # expect your cases to run
git log --all -p | grep -c '<your api key>'     # expect 0
```
