# Agent 1: Gatekeeper and API gateway

Owns `services/agent1_gatekeeper/`, `services/gateway/`, shared infrastructure and security evaluation. The job is to interpret user intent, protect data and stop unsuitable input before coaching, while preserving a trace of what ran.

## Implemented in this improvement

Plateau classification precedes log detection. Missing load/reps cause clarification; missing set count remains optional. The paid judge defaults off and is configurable, with independent local rule and embedding checks. Judge status and raw semantic similarity reach the browser. Gateway usage includes reported judge tokens. Signed inter-agent contracts are unchanged.

## What to explain at the viva

Canonicalisation removes superficial encoding differences; deobfuscation produces variants; Aho–Corasick expands jargon; spaCy and rules extract structured fields; maximum fusion prevents a strong detector from being diluted. Zero semantic contribution means the raw match fell below the floor, not that embedding did not happen. A disabled judge is not a successful judge assessment. Medical policy and prompt-injection risk answer different questions.

## Next bounded work

1. Add independently authored paraphrased attacks covering the 12 local-detector misses; measure precision/recall against a held-out set.
2. Separate local original-text scoring from redacted judge input explicitly, including decoded variants.
3. Replace the rate limiter's separate read/push operations with an atomic admission operation; add concurrent request tests.
4. Add atomic token reservations for hard spending ceilings and distinguish failed/unknown provider usage.
5. Validate rate limiting, ownership, trace persistence and signed routing against a real isolated Mongo database.

## Follow-up prompt

> Read docs/improvement-plan.md and this file. Improve the Gatekeeper's local threat detection against a separately held-out attack set. Preserve medical precedence, redaction before external calls and HMAC/replay protections. Keep API judge use configurable and report skipped/unavailable states honestly. Add meaningful regression tests and publish actual precision, recall, false positives and paid-call counts. Do not train rules to merely match the existing benchmark or overwrite historic evidence as if it describes this build. Document unresolved weaknesses.

Acceptance: complete logs are allowed; incomplete logs clarify; the screenshot's plateau message is a query; benign risk can be zero; blocked/local turns do not invoke coaching generation; no external request contains unredacted PII.
