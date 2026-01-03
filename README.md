# Unstable FastAPI Service

This project provides an intentionally unstable FastAPI service designed for
testing Kubernetes liveness/readiness probes, self‑healing behavior, and
failure‑handling mechanisms.

The service exposes:
- an HTML index page showing the current server time
- deterministic and random failures for http calls on the index site
- health and readiness endpoints that also fail unpredictably

As a result, Kubernetes will regularly restart the pod.

---

## Features

### 1. `/` – HTML Index Page  
- Renders a minimal dark‑themed HTML page  
- Displays the current server time  
- **Every second request intentionally returns HTTP 500**

### 2. `/healthz` – Liveness Probe  
- 80% success rate, 20% random failures  
- Kubernetes will restart the pod when this endpoint fails repeatedly

### 3. `/readyz` – Readiness Probe  
- 80% success rate, 20% random failures  
- Kubernetes will mark the pod as “NotReady”, preventing traffic routing

---

## Running Locally

### Requirements
- Python 3.12+
- pip

### Install dependencies

```bash
pip install fastapi uvicorn
```

### Start the service
```bash
uvicorn main:app --host 0.0.0.0 --port 8080

uv sync
uv run uvicorn main:app --host 0.0.0.0 --port 8080
```

### Access it at:
http://localhost:8080

## Docker Build und run
```bash
docker build -t unstable-fastapi .
docker run -p 8080:8080 unstable-fastapi
```
