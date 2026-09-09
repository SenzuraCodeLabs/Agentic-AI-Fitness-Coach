"""API gateway: auth, rate limiting, SSE streaming."""

from shared.service import create_service

app = create_service(
    service_name="gateway",
    title="FitCoach Gateway",
    ensure_indexes=True,
)
