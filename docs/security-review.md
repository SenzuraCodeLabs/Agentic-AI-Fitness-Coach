# Security review

Scope: the components owned by this author, being the gateway, agent 1
(Gatekeeper), `shared/`, and the red-team harness. Agents 2 and 3 are reviewed
only where they consume the shared contracts.

Date: 2026-09-09. Commit: see `git log`.

---

## Summary

| Area | Result |
| --- | --- |
| Secrets in git history | None found across all commits |
| Secrets in runtime logs | None found across all service logs |
| Dependency audit (pip-audit) | 5 advisories, all analysed, none applicable |
| Dependency audit (npm) | 2 advisories, accepted with justification |
| Authentication | Argon2id, pinned-algorithm JWT, refresh rotation with reuse detection |
| Error disclosure | One flaw found by the red-team harness and fixed |

---

## 1. Secret handling

### 1.1 No secrets in version control

```bash
git log --all -p | grep -icE '<known secret values>'   # 0
git log --all --diff-filter=A --name-only | grep -x '.env'   # no match
```

`.env` was never added in any commit. Every credential is loaded through
`shared/config.py` via pydantic-settings.

### 1.2 No secrets in logs

Every credential field is typed `SecretStr`, whose `repr` is masked, so a stray
`log.info("config", cfg=settings)` cannot leak a key. Verified by scanning
every captured service log for the real values: zero occurrences.

Email addresses are also absent. `services/gateway/email.py` logs only the
recipient domain, because logs are exactly where personal data should not
accumulate.

**Status: no finding.**

### 1.3 Credentials were shared in a chat transcript

The DeepSeek API key, Gmail app password and JWT secret used in development
were pasted into a conversation with an AI assistant.

**Severity: medium. Status: OPEN, action required by the author.**

Rotate all three before submission or before the repository is shared.
Coursework repositories are frequently uploaded with full history, and a
transcript is not a secure channel.

---

## 2. Dependency audit

### 2.1 Python (`pip-audit`)

Five advisories, none with a fix available. Each was analysed rather than
merely listed.

| Package | Advisory | Applicable here? |
| --- | --- | --- |
| chromadb 1.5.9 | PYSEC-2026-311 (pre-auth code injection) | **No.** Targets the `/api/v2/tenants/...` server endpoint and requires `trust_remote_code`. This deployment uses `chromadb.PersistentClient`, which runs embedded with no HTTP server. Verified: no `HttpClient` and no `trust_remote_code` anywhere in the tree. |
| chromadb 1.5.9 | CVE-2026-45830 (cross-tenant access) | **No.** Multi-tenant authorisation flaw. This deployment has one embedded collection and no tenants. |
| chromadb 1.5.9 | CVE-2026-45833 (authenticated code injection) | **No.** Same server endpoint and `trust_remote_code` precondition as PYSEC-2026-311. |
| chromadb 1.5.9 | CVE-2026-45831 (RBAC scope confusion) | **No.** Affects `SimpleRBACAuthorizationProvider`, which requires server mode. Not used. |
| ecdsa 0.19.2 | PYSEC-2026-1325 (Minerva timing attack on P-256) | **No.** Reaches the tree transitively through `python-jose`. JWTs are signed with HS256, which is HMAC-SHA256 and symmetric. Verified empirically: an HS256 encode-decode round trip loads no `ecdsa` module. |

**Status: accepted, with the reasoning recorded above.** Re-evaluate if
ChromaDB is ever run in server mode, or if the JWT algorithm changes to ES256.

### 2.2 JavaScript (`npm audit`)

Next.js was upgraded from the scaffolded 15.1.6, which npm flags for
CVE-2025-66478, to 15.5.25. Two advisories remain in a postcss copy bundled
inside Next.js, fixable only by a major bump to Next 16 that would contradict
the stack specified in CLAUDE.md.

Both are build-time CSS-processing flaws requiring attacker-controlled CSS. All
CSS here is written by the project and committed; no user input reaches
PostCSS.

**Status: accepted.** Full reasoning in `web/SECURITY-NOTES.md`.

---

## 3. Authentication and session management

| Control | Implementation | Verification |
| --- | --- | --- |
| Password hashing | Argon2id, 64 MiB memory cost, 3 iterations | `test_hash_is_argon2id` |
| Per-hash salt | Automatic in argon2-cffi | `test_same_password_hashes_differently` |
| Algorithm confusion | Algorithm pinned at decode, never read from the token header | `test_alg_none_token_is_rejected` |
| Forged signature | Rejected | `test_token_signed_with_another_key_is_rejected` |
| Claim tampering | Rejected | `test_tampered_claims_are_rejected` |
| Access token lifetime | 15 minutes | `test_access_token_expiry_matches_configuration` |
| Refresh rotation | Each refresh mints a new token and revokes the old | `rotate_refresh_token` |
| Refresh reuse detection | Presenting a revoked token revokes the whole family | `rotate_refresh_token`, verified live |
| Token storage | SHA-256 of the token, not the token | `test_token_hash_is_stable_and_hides_the_token` |
| Password reset | Single-use, time-limited, revokes all sessions | `reset_password` |
| Account enumeration | Identical response and comparable timing for unknown accounts | Verified live: both paths return "Email or password is incorrect." |

### 3.1 Token storage in the browser

**Finding: accepted risk.** The refresh token is held in `localStorage`, which
is readable by any script running on the page, so a cross-site scripting flaw
would expose it. An `httpOnly` cookie would be stronger.

**Why accepted:** an httpOnly cookie requires the API and client to share a
site, which this split deployment (API on 8000, client on 3000) does not
provide. Mitigating factors: the access token is held in memory only, refresh
tokens rotate on every use, reuse is detected and revokes the family, and the
API sets a strict Content-Security-Policy.

**Revisit if** the client and API are ever served from one origin.

---

## 4. Transport and headers

Verified live against the running gateway:

| Header | Value |
| --- | --- |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'` |
| `Referrer-Policy` | `no-referrer` |
| `Permissions-Policy` | geolocation, microphone, camera all disabled |
| `Strict-Transport-Security` | Set in production only, since HSTS over plain HTTP is meaningless |

**CORS** is restricted to configured origins. Verified: `http://localhost:3000`
receives an allow-origin header; `http://evil.example.com` is rejected with 400
and no allow-origin header.

**Request size** is capped at 32 KB before parsing, so an oversized body is
rejected before any allocation.

### 4.1 X-Forwarded-For is trusted

**Finding: accepted, with a deployment precondition.** `_client_ip` honours the
`X-Forwarded-For` header for per-IP rate limiting. Without a reverse proxy
stripping it, any caller can forge their address and evade the limit.

This is correct behind the compose deployment's proxy and incorrect if the
gateway is exposed directly. Documented at the function so it cannot be
mistaken for a general-purpose helper.

---

## 5. The agent-to-agent protocol

| Threat | Control | Verification |
| --- | --- | --- |
| Message forgery | HMAC-SHA256 over canonical bytes | `test_wrong_secret_fails` |
| Modification in transit | Signature covers header, trust block and payload | `test_lowering_risk_score_fails_verification` |
| Replay | `message_id` nonce with a TTL, atomic via a unique index | `test_second_use_of_the_same_id_is_a_replay`, live driver RT-EX-003 |
| Delayed replay | `expires_at` | `test_expired_envelope_is_rejected` |
| Forged timestamp | Clock-skew tolerance | `test_future_issued_at_beyond_skew_is_rejected` |
| Lateral movement | `ALLOWED_ROUTES` | `test_disallowed_route_is_rejected_despite_valid_signature` |
| Field smuggling | `extra="forbid"` | `test_unknown_field_is_rejected` |
| Timing attack on the signature | `hmac.compare_digest` | Reviewed in `signing.py` |
| User impersonation | `subject` is inside the signed region | `test_subject_is_covered_by_the_signature` |

### 5.1 FIXED: error responses disclosed which check failed

**Severity: low. Status: FIXED.**

Found by the project's own red-team harness (case RT-EX-003), not by review. A
replayed envelope returned `"Envelope replay detected"` while a malformed body
returned `"envelope could not be parsed"`, and the `type` field differed too. An
attacker probing the endpoint could determine exactly which control they had
tripped and iterate against it.

**Fix:** `EnvelopeRejected.to_problem()` now returns one uniform body for every
subclass. The specific reason is still passed to the logger, so operators keep
the detail. Guarded by
`test_every_envelope_rejection_looks_identical_on_the_wire`.

### 5.2 Symmetric shared key

**Finding: accepted, documented limitation.** All four services share one HMAC
secret, so full compromise of any one service allows minting envelopes for any
permitted route. Per-agent asymmetric keys (Ed25519) would contain this.

Rejected for now on key-distribution cost across three developers' machines.
Recorded in `docs/protocol.md` and ADR 0001 rather than left implicit.

---

## 6. Safety pipeline

| Control | Location | Evidence |
| --- | --- | --- |
| Unicode canonicalisation | `l1_canonicalise.py` | 22 tests covering zero-width, homoglyph, bidi and repetition evasion |
| Encoded payload recovery | `l2_deobfuscate.py` | base64 to depth 2, hex, ROT13, leetspeak |
| Threat detection | `l5_threat_scorer.py` | precision 1.000, recall 0.944, FPR 0.000 over 300 cases |
| PII redaction before external calls | `l6_pii_redactor.py` | `test_redaction_precedes_any_external_call` intercepts the only outbound call |
| Neutral refusals | `l7_policy_engine.py` | `test_a_block_message_does_not_name_the_detector` |
| Spotlighting | `l8_envelope.py` | The judge correctly classified an instruction aimed at itself as an attack |
| Tamper-evident audit log | `l8_envelope.py` | Modification detected as a hash mismatch, deletion as a sequence gap |

### 6.1 Five adversarial inputs are not detected

**Severity: medium. Status: OPEN, documented.**

Five of 90 adversarial benchmark cases score below threshold. All share one root
cause: they score under 0.15 on both cheap signals, so the LLM judge, which is
band-gated, never sees them.

Full analysis, including the specific phrasings and why each evades, is in
ADR 0005. Mitigating factor: L7 and L8 mean a missed detection at L5 is not
automatically a successful attack, since downstream prompts still frame user
text as data.

### 6.2 The audit chain is tamper-evident, not tamper-proof

**Status: accepted, documented.** An attacker able to rewrite the entire
collection could recompute the whole chain. Preventing that needs an external
anchor. See ADR 0006.

---

## 7. Rate limiting and cost

| Control | Behaviour |
| --- | --- |
| Per-user sliding window | 20 requests per minute |
| Per-IP sliding window | 60 requests per minute |
| Daily token quota | Checked against recorded telemetry, returns 429 with `Retry-After` |
| Short circuit | A blocked or refused turn never reaches the LLM, so an attack costs nothing to serve |

### 7.1 Rate limiting fails open

**Finding: deliberate asymmetry, documented.** If the database is unavailable,
rate limiting fails **open** while replay protection fails **closed**.

The reasoning: a database blip should not lock every user out of the product,
whereas an unverifiable message must never be treated as fresh. Both choices are
commented at the point of decision so the asymmetry is visible rather than
accidental.

---

## 8. Open items for the author

| Item | Severity | Action |
| --- | --- | --- |
| Rotate the three credentials shared in a chat transcript | Medium | Before submission |
| Five undetected adversarial inputs | Medium | Documented in ADR 0005; candidate for the report's findings |
| localStorage refresh token | Low | Accepted; revisit on same-origin deployment |
| Symmetric A2A key | Low | Accepted for coursework scale |
