"""Agent 1 - Gatekeeper: trust, safety and NLU pipeline."""

from shared.service import create_service

app = create_service(
    service_name="agent1_gatekeeper",
    title="FitCoach Agent 1 - Gatekeeper",
    ensure_indexes=True,
)
