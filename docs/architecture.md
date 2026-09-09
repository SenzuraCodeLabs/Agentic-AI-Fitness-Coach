# Architecture

## Components

```mermaid
graph TB
    subgraph client["Client"]
        WEB["Next.js 15<br/>:3000"]
    end

    subgraph services["Services"]
        GW["Gateway :8000<br/>auth, rate limit, SSE"]
        GK["Agent 1 Gatekeeper :8001<br/>9-layer trust pipeline"]
        CO["Agent 3 Coach :8003<br/>overload maths"]
        RE["Agent 2 Researcher :8002<br/>RAG retrieval"]
    end

    subgraph data["Data"]
        MONGO[("MongoDB<br/>users, workouts,<br/>audit, nonces")]
        CHROMA[("ChromaDB<br/>evidence corpus")]
    end

    subgraph external["External"]
        DS["DeepSeek API"]
        SMTP["Gmail SMTP"]
    end

    WEB -->|"JWT over HTTPS"| GW
    GW -->|"signed envelope"| GK
    GK -->|"signed envelope"| CO
    CO -->|"signed envelope"| RE

    GW --- MONGO
    GK --- MONGO
    CO --- MONGO
    RE --- CHROMA

    GK -.->|"judge, redacted text only"| DS
    CO -.->|"phrasing only"| DS
    GW -.-> SMTP
```

Solid arrows carry signed envelopes. Dotted arrows are external calls, and both
carry only redacted text.

---

## The Gatekeeper pipeline

Order is a security property, not an implementation detail.

```mermaid
graph LR
    IN["user text"] --> L1["L1 canonicalise"]
    L1 --> L2["L2 deobfuscate"]
    L2 --> L3["L3 jargon"]
    L3 --> IC["intent"]
    IC --> L4["L4 extract"]
    L4 --> L6["L6 redact"]
    L6 --> L5["L5 threat"]
    L5 --> L7["L7 policy"]
    L7 -->|"ALLOW"| L8["L8 envelope"]
    L7 -->|"BLOCK / REFUSE / CLARIFY"| STOP["terminal:<br/>no downstream call"]
    L8 --> OUT["signed envelope"]
```

| Layer | Purpose | Why it sits here |
| --- | --- | --- |
| L0 | Rate limit, quota | In the gateway, before any pipeline work |
| L1 | Unicode canonicalisation | Must be first, or later layers match the attacker's encoding |
| L2 | Decode base64, hex, ROT13, leet | Before L5, or an encoded payload scores as noise |
| L3 | Jargon expansion | Before L4, so extraction sees standardised terms |
| Intent | Classification | Before L7, which conditions on it |
| L4 | Structured extraction | Before L7, which conditions on confidence |
| **L6** | **PII redaction** | **Before L5's judge: the only external call in the pipeline** |
| L5 | Hybrid threat scoring | Local signals see everything; the judge sees redacted text only |
| L7 | Policy decision | Consumes everything above |
| L8 | Envelope and audit | Only on a non-terminal decision |

**The L5/L6 ordering looks inverted and is not.** L5's rule and semantic
signals are local computation, so they can safely see unredacted variants. Only
the judge leaves the process, and it receives redacted text. This is asserted
by `test_redaction_precedes_any_external_call`, which intercepts the judge and
inspects exactly what it was given.

---

## Request sequence

```mermaid
sequenceDiagram
    participant U as User
    participant GW as Gateway
    participant GK as Gatekeeper
    participant CO as Coach
    participant RE as Researcher
    participant DB as MongoDB

    U->>GW: POST /api/chat (JWT)
    GW->>DB: rate limit + quota
    GW->>GK: run pipeline (in-process)
    GK-->>GW: decision + trace
    GW-->>U: SSE "decision" (transparency)
    GW->>DB: persist trace + audit record

    alt terminal decision
        GW-->>U: SSE "message" (refusal), no downstream call
    else allowed
        GW->>DB: persist workout
        GW->>GK: signed envelope
        GK->>CO: signed envelope
        CO->>DB: load history for subject
        CO->>RE: signed envelope
        RE-->>CO: evidence chunks
        CO-->>GK: reply + citations
        GK-->>GW: reply
        GW-->>U: SSE "message" + "done"
    end
```

---

## Data model

| Collection | Purpose | Key indexes |
| --- | --- | --- |
| `users` | Accounts | unique `email` |
| `refresh_tokens` | Rotating sessions | unique `token_hash`, TTL on `expires_at` |
| `email_tokens` | Verification and reset | unique `token_hash`, TTL on `expires_at` |
| `workouts` | Logged sessions | `(user_id, session_date)`, `(user_id, exercise, session_date)` |
| `audit_events` | Hash-chained security log | unique `seq`, by `correlation_id` |
| `envelope_nonces` | Replay protection | unique `message_id`, TTL on `expires_at` |
| `telemetry` | Token spend | `(user_id, created_at)` |
| `rate_limits` | Sliding windows | `key`, TTL on `expires_at` |
| `decision_traces` | Explainability | unique `message_id`, TTL 30 days |

TTL indexes let MongoDB expire nonces, tokens and traces itself, so there is no
cleanup job and the replay window cannot grow unbounded.

---

## Key design decisions

Each has an ADR in `docs/adr/`.

| ADR | Decision |
| --- | --- |
| 0001 | Signed envelopes for all inter-agent communication |
| 0002 | Discriminate the payload union on `kind`, not `intent` |
| 0003 | Aho-Corasick for jargon expansion |
| 0004 | Constrain fuzzy correction after it corrupted ordinary text |
| 0005 | Hybrid three-signal threat detection, with measured weaknesses |
| 0006 | Hash-chained audit log |
| 0007 | Add `subject` to the envelope header (breaking change) |
