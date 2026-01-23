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

### 4. `/chaos/?`- choose failure
```bash
# Speicherverbrauch massiv erhöhen (Richtung OOMKill)
curl -k -X POST https://randomfail.gmk.lan/chaos/oom

# Den Container sofort hart beenden (Simuliert App-Crash)
curl -k -X POST https://randomfail.gmk.lan/chaos/crash

# Erzeugt für 30 Sekunden 100% Last auf einem CPU-Kern
curl -k -X POST https://randomfail.gmk.lan/chaos/cpu

# Erzeugt für 110 MBit bin file um pvc überlaufen zu lassen
curl -k -X POST https://randomfail.gmk.lan/chaos/disk

# Den Health-Status manuell auf "unhealthy" setzen (Liveness Probe Test)
curl -k -X POST https://randomfail.gmk.lan/chaos/unhealthy
```

---

## Running Locally

### Requirements
- Python 3.12+
- pip

### Install dependencies (old way)

```bash
pip install fastapi uvicorn
```

### Start the service
```bash
uv lock --upgrade
uv sync
uv pip compile pyproject.toml -o requirements.txt

uv run uvicorn main:app --host 0.0.0.0 --port 8080
```

### Access it at:
http://localhost:8080

## Docker Build und run
```bash
docker build -t unstable-fastapi .
docker run -p 8080:8080 unstable-fastapi
```
