# Single image for all four Python services; the compose command selects which
# module uvicorn runs. One image means one dependency build, and identical
# library versions across services, which matters because they share
# shared/contracts and must agree on Pydantic's behaviour.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY shared ./shared
COPY services ./services

RUN pip install --upgrade pip \
    && pip install -e ".[gateway,gatekeeper,researcher,coach]" \
    && python -m spacy download en_core_web_sm

COPY eval ./eval

# Run as an unprivileged user: a container escape from a web process should not
# start as root.
RUN useradd --create-home --uid 10001 fitcoach && chown -R fitcoach /app
USER fitcoach

EXPOSE 8000 8001 8002 8003
CMD ["uvicorn", "services.gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
