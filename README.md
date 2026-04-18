# Kubernetes Chaos Simulator – randomfail

Ein absichtlich instabiler FastAPI-Service zur Simulation realer Ausfallszenarien in Kubernetes-Clustern. Der Service löst automatisch und manuell verschiedene Fehlerzustände aus und ermöglicht so das gezielte Testen von Liveness/Readiness-Probes, Self-Healing-Mechanismen, HPA-Reaktionen, PVC-Limits und Graceful-Shutdown-Verhalten.

Der Chaos-Zyklus wechselt in konfigurierbaren Intervallen automatisch zwischen den Szenarien. Zusätzlich können alle Szenarien jederzeit manuell per HTTP-Endpoint ausgelöst werden.

---

## Simulierte Fehlerzustände

### OOM_KILL – Speichererschöpfung
Der Service füllt schrittweise den Arbeitsspeicher (1 MB pro Sekunde). Sobald das Memory-Limit des Containers erreicht ist, beendet der Linux-Kernel den Prozess mit einem OOMKill-Signal.

**Kubernetes-Reaktion:**
- Pod-Status wechselt zu `OOMKilled`
- Kubelet startet den Container automatisch neu
- Bei wiederholten OOMKills: Status `CrashLoopBackOff`
- Sichtbar in: `kubectl describe pod`, Prometheus-Metrik `container_oom_events_total`

---

### CPU_BURN – CPU-Erschöpfung
Mehrere Threads führen Endlosberechnungen durch und sättigen die zugewiesenen CPU-Kerne vollständig für eine konfigurierbare Dauer.

**Kubernetes-Reaktion:**
- Container wird auf das CPU-Limit gedrosselt (CPU Throttling)
- Sichtbar in Metrik `container_cpu_cfs_throttled_seconds_total`
- Horizontal Pod Autoscaler (HPA) kann weitere Replikas hochskalieren
- Probe-Timeouts möglich, wenn der Event-Loop durch Throttling verzögert wird

---

### SLOW_DEATH – Liveness Probe Failure
Der Service setzt seinen internen Health-Status auf `unhealthy`. Der `/healthz`-Endpoint antwortet ab diesem Moment mit HTTP 500.

**Kubernetes-Reaktion:**
- Liveness Probe schlägt nach `failureThreshold` Versuchen fehl
- Kubelet führt einen Container-Neustart durch (kein Pod-Neustart)
- Während der Neustart-Wartezeit bleibt der Pod im Status `Running`, nimmt aber keinen Traffic mehr an
- Sichtbar in: `kubectl describe pod` → Events: `Liveness probe failed`

---

### CRASH – Harter Prozessabsturz
Der Prozess beendet sich sofort mit `os._exit(1)` ohne jegliches Cleanup. Simuliert einen Segfault oder eine unkontrollierte Ausnahme.

**Kubernetes-Reaktion:**
- Pod-Status wechselt zu `Error` (Exit Code 1)
- Kubelet startet den Container sofort neu
- Bei wiederholten Abstürzen: exponentielles Backoff → `CrashLoopBackOff`
- Sichtbar in: `kubectl get pods`, `kubectl logs --previous`

---

### DISK_FILL – PVC-Erschöpfung
Der Service schreibt eine große Binärdatei auf das eingebundene PersistentVolume, bis der verfügbare Speicherplatz erschöpft ist.

**Kubernetes-Reaktion:**
- Schreiboperationen der Anwendung schlagen mit `No space left on device` fehl
- Je nach Konfiguration: Pod wird durch den Kubelet evakuiert (`Evicted`)
- Das PVC bleibt nach dem Pod-Neustart gefüllt – Cleanup nötig
- Sichtbar in: `kubectl describe pod` → Events: `Evicted`, `df -h` im Container

---

### SLOW_RESPONSE – Antwort-Verzögerung
Jeder HTTP-Request wird künstlich um eine konfigurierbare Anzahl von Sekunden verzögert. Dies betrifft auch die Probe-Endpunkte.

**Kubernetes-Reaktion:**
- Liveness- und Readiness-Probe überschreiten `timeoutSeconds` → Probe gilt als fehlgeschlagen
- Nach `failureThreshold` Timeouts: Container-Neustart (Liveness) bzw. Traffic-Ausschluss (Readiness)
- Simuliert langsame Datenbankabfragen, überlastete Downstream-Services oder GC-Pausen
- Sichtbar in: `kubectl describe pod` → Events: `Liveness probe failed: context deadline exceeded`

---

### FD_EXHAUSTION – File-Descriptor-Erschöpfung
Der Service öffnet kontinuierlich Datei-Handles ohne sie zu schließen, bis das Betriebssystem-Limit (`ulimit -n`) erreicht ist.

**Kubernetes-Reaktion:**
- Alle weiteren Systemoperationen schlagen mit `too many open files` fehl
- HTTP-Verbindungen können nicht mehr angenommen werden → Pod antwortet nicht mehr
- Liveness Probe schlägt fehl → Container-Neustart
- Simuliert typische FD-Leaks in Produktionsdiensten (nicht geschlossene DB-Connections, Socket-Leaks)
- Sichtbar in: `kubectl exec` → `ls /proc/<pid>/fd | wc -l`

---

### SIGTERM_DELAY – Verzögerter Graceful Shutdown
Beim Empfang des SIGTERM-Signals (ausgelöst durch `kubectl delete pod`, Rolling Update oder Scale-Down) wartet der Service für eine konfigurierbare Zeit, bevor er sich beendet.

**Kubernetes-Reaktion:**
- Kubernetes wartet maximal `terminationGracePeriodSeconds` auf den Prozess
- Nach Ablauf der Frist: SIGKILL (harter Abbruch)
- Testet, ob `terminationGracePeriodSeconds` ausreichend dimensioniert ist
- Während der Wartezeit werden Health-Probes auf `unhealthy` gesetzt, um Traffic-Routing zu stoppen
- Sichtbar in: `kubectl describe pod` → `Terminating` Status

---

### STABLE – Kein Chaos
Der Service läuft ohne Fehler. Dient als Ruhephase zwischen den Chaos-Zyklen.

---

## HTTP-Endpunkte

### Kubernetes Probes

| Endpunkt | Probe-Typ | Beschreibung |
|---|---|---|
| `GET /healthz` | Liveness + Startup | Gibt HTTP 200 zurück wenn der Service gesund ist, sonst HTTP 500 |
| `GET /readyz` | Readiness | Gibt HTTP 200 zurück wenn der Service bereit ist, sonst HTTP 503 |

### Anwendung

| Endpunkt | Beschreibung |
|---|---|
| `GET /` | HTML-Seite mit aktueller Uhrzeit und aktivem Szenario. Jede dritte Anfrage gibt HTTP 500 zurück. |
| `GET /status` | JSON-Statusübersicht: aktives Szenario, Speicherverbrauch, FD-Anzahl, Konfiguration |

### Chaos-Kontrolle

| Endpunkt | Szenario | Beschreibung |
|---|---|---|
| `POST /chaos/reset` | – | Setzt alle Chaos-Zustände zurück |
| `POST /chaos/oom` | OOM_KILL | Fügt sofort 100 MB Speicherdruck hinzu |
| `POST /chaos/cpu` | CPU_BURN | Startet CPU-Burn-Threads für konfigurierte Dauer |
| `POST /chaos/crash` | CRASH | Beendet den Prozess sofort mit Exit Code 1 |
| `POST /chaos/unhealthy` | SLOW_DEATH | Schaltet den Health-Status um (Toggle) |
| `POST /chaos/disk` | DISK_FILL | Startet das Befüllen des PVC |
| `POST /chaos/slow` | SLOW_RESPONSE | Aktiviert künstliche Request-Verzögerung |
| `POST /chaos/fd` | FD_EXHAUSTION | Startet das Erschöpfen der File-Descriptors |

---

## Konfiguration

Alle Parameter werden über Umgebungsvariablen gesetzt (Helm-Values in `randomfail-chart/values.yaml`):

| Variable | Default | Beschreibung |
|---|---|---|
| `CHAOS_INTERVAL` | `300` | Sekunden zwischen automatischen Chaos-Zyklen |
| `CHAOS_STARTUP_DELAY` | `10` | Sekunden Wartezeit nach dem Start vor dem ersten Zyklus |
| `MEMORY_CHUNK_SIZE` | `1000000` | Bytes pro Speicher-Chunk im OOM-Szenario (1 MB) |
| `DISK_FILL_SIZE_MB` | `110` | Größe der Junk-Datei für das DISK_FILL-Szenario in MB |
| `CPU_BURN_THREADS` | `2` | Anzahl paralleler Threads im CPU_BURN-Szenario |
| `CPU_BURN_DURATION` | `120` | Sekunden Dauer des CPU-Burns (empfohlen: max. CHAOS_INTERVAL / 2) |
| `SLOW_RESPONSE_DELAY` | `5` | Sekunden künstliche Verzögerung pro Request im SLOW_RESPONSE-Szenario |
| `SIGTERM_DELAY` | `30` | Sekunden Wartezeit nach SIGTERM vor dem Prozess-Exit |

---

## Lokaler Betrieb

### Voraussetzungen
- Python 3.12+
- [uv](https://github.com/astral-sh/uv)

### Setup und Start

```bash
uv lock --upgrade
uv sync
uv run ruff check .
uv run pyright .
uv pip compile pyproject.toml -o requirements.txt

uv run uvicorn main:app --host 0.0.0.0 --port 8080
```

Erreichbar unter: http://localhost:8080

### Docker

```bash
docker build -t randomfail .
docker run -p 8080:8080 \
  -e CHAOS_INTERVAL=60 \
  -e SLOW_RESPONSE_DELAY=3 \
  randomfail
```

---

## Deployment in Kubernetes (Helm)

```bash
helm install randomfail ./randomfail-chart
```

Das Chart enthält:
- `Deployment` mit konfigurierten Liveness-, Readiness- und Startup-Probes
- `PersistentVolumeClaim` für das DISK_FILL-Szenario
- `Service` (ClusterIP)
- Optionales Istio-Gateway mit VirtualService und TLS via cert-manager

### Chaos-Szenarien manuell auslösen

```bash
# Status abfragen
curl -k https://randomfail.gmk.lan/status

# OOM-Druck erzeugen
curl -k -X POST https://randomfail.gmk.lan/chaos/oom

# Harten Absturz auslösen
curl -k -X POST https://randomfail.gmk.lan/chaos/crash

# CPU-Last starten
curl -k -X POST https://randomfail.gmk.lan/chaos/cpu

# PVC füllen
curl -k -X POST https://randomfail.gmk.lan/chaos/disk

# Health-Status auf unhealthy setzen (Liveness Probe Test)
curl -k -X POST https://randomfail.gmk.lan/chaos/unhealthy

# Langsame Antworten aktivieren (Probe Timeout Test)
curl -k -X POST https://randomfail.gmk.lan/chaos/slow

# File-Descriptor-Erschöpfung starten
curl -k -X POST https://randomfail.gmk.lan/chaos/fd

# Alle Chaos-Zustände zurücksetzen
curl -k -X POST https://randomfail.gmk.lan/chaos/reset
```
