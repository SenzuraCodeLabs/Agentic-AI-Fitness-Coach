# FitCoach - Agentic AI Fitness Coaching System

Coursework for IT3041 Information Retrieval and Web Analytics, SLIIT.

Users log strength-training sessions in natural language. The system sanitises
the input, retrieves grounded exercise-science evidence, and computes
progressive-overload recommendations deterministically.

## Architecture

Four services communicate over signed HMAC envelopes carrying a shared
correlation ID.

| Service | Port | Responsibility | Owner |
| --- | --- | --- | --- |
| `gateway` | 8000 | Auth, JWT, rate limiting, SSE streaming | Yathurshan |
| `agent1_gatekeeper` | 8001 | Nine-layer trust, safety and NLU pipeline | Yathurshan |
| `agent2_researcher` | 8002 | RAG retrieval over the evidence corpus | Teammate |
| `agent3_coach` | 8003 | Progressive-overload maths and telemetry | Teammate |

Full diagrams live in `docs/architecture.md`; the wire protocol is specified in
`docs/protocol.md`.

## Prerequisites

- Python 3.13
- MongoDB (local service on 27017, or the bundled compose service)
- Node.js 20 for the web client
- Docker Desktop, optional, for the full stack

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows; use source .venv/bin/activate on POSIX
pip install -e ".[gateway,gatekeeper,dev]"
python -m spacy download en_core_web_sm

cp .env.example .env            # then fill in every value
```

Generate the two secrets with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Running

```bash
docker compose up --build       # everything, including MongoDB

# or per service, against a local MongoDB
uvicorn services.gateway.main:app --reload --port 8000
uvicorn services.agent1_gatekeeper.main:app --reload --port 8001
```

Verify:

```bash
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
```

## Tests and benchmarks

```bash
pytest -q
pytest services/agent1_gatekeeper -q --cov
ruff check . && ruff format .
python eval/gatekeeper/run_benchmark.py
python eval/redteam/run_suite.py
```

## Contributors

| Member | Owned modules |
| --- | --- |
| Yathurshan | `gateway`, `agent1_gatekeeper`, `shared/`, `eval/redteam` |
| Teammate 2 | `agent2_researcher` |
| Teammate 3 | `agent3_coach` |

## Limitations

Recorded in `docs/security-review.md` and the limitations section added at P5.
