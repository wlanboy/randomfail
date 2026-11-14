ARG PYTHON_TAG=3.14-slim

# Build stage
FROM python:${PYTHON_TAG} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies in a virtual environment
COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --only-binary=:all: -r requirements.txt

# Runtime stage
FROM python:${PYTHON_TAG}

ARG REVISION=unknown

LABEL org.opencontainers.image.title="randomfail" \
      org.opencontainers.image.description="Absichtlich instabiler FastAPI-Service zur Simulation von Ausfallszenarien in Kubernetes" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.vendor="wlanboy" \
      org.opencontainers.image.source="https://github.com/wlanboy/randomfail" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.base.name="python:3.14-slim"

# Verhindert, dass Python .pyc Dateien schreibt und sorgt für sofortige Log-Ausgabe
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"

# Create non-root user
RUN groupadd -r -g 1000 appuser && useradd -r -u 1000 -g appuser appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application files
COPY --chown=appuser:appuser main.py /app/
COPY --chown=appuser:appuser templates/ /app/templates/
COPY --chown=appuser:appuser static/ /app/static/

# Use non-root user
USER appuser

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
