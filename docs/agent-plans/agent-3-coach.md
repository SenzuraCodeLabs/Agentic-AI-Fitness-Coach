# Agent 3: Coach, local answers and usage

Owns `services/agent3_coach/`. Turns structured workouts into deterministic recommendations, reads a user's training history and chooses the cheapest adequate answer route.

## Implemented in this improvement

Workout rationales return without a model call. Exact predefined questions have local answers. Sufficiently strong retrieved passages answer locally. Progress queries read recent stored sessions. Question answers are cached per user for 24 hours and invalidated by corpus/version changes. Workout history excludes the current correlation ID to prevent double counting. An evidence gap uses the fast configured DeepSeek model with thinking disabled, no SDK retry and a bounded output budget. Answer route and tokens travel to the UI using existing flexible payload fields.

## What to explain at the viva

RAG does not itself reduce generation cost unless retrieval can terminate the request with an adequate local answer. Caching occurs after safety checks. Cache keys retain numeric distinctions and user scope. Output limits do not limit input tokens. A cache hit uses zero new coaching tokens even if the original answer used DeepSeek. A fallback without sufficient evidence must not invent source citations.

## Next bounded work

1. Handle each exercise in multi-exercise logs and distinguish working sets from separate sessions when detecting a plateau.
2. Implement and test an explicitly defined weekly-volume product constraint. The proposal's 10% figure is a configurable product rule, not a universal scientific safety law; define the time window, baseline and missing-history behaviour.
3. Add equipment-aware increment limits for light weights, where a 2.5kg minimum is a large relative jump.
4. Add prompt/completion/cache-hit token breakdown and configurable price estimates, labelled separately from provider invoices.
5. Coalesce concurrent identical misses, avoid caching personalised time-sensitive answers and support richer date/exercise filters for progress queries.

## Follow-up prompt

> Read docs/improvement-plan.md and this file. Extend deterministic coaching to every exercise in a logged session. Do not let an LLM select or alter weights. Define session grouping, training-window boundaries, optional fields, equipment increments and volume-cap behaviour before implementing them. Add tests for light weights, multiple exercises, repeated sets within one session, backdated entries and missing history. Keep the local/cache/retrieval-first routing and strict paid-call budgets. Report assumptions and unresolved safety limitations clearly.

Acceptance now: local answers never construct an API client; cache keys isolate users; a miss uses one bounded fast-model call; a failed provider request falls back to clarification; existing overload maths remains deterministic.
