from fastapi import FastAPI, Response, Request
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
import random
import asyncio
import os
import threading
import time
import datetime

# Konfiguration via Environment-Variablen
CHAOS_INTERVAL = int(os.getenv("CHAOS_INTERVAL", "300"))  # Sekunden zwischen Chaos-Zyklen
CHAOS_STARTUP_DELAY = int(os.getenv("CHAOS_STARTUP_DELAY", "10"))  # Initialer Puffer
MEMORY_CHUNK_SIZE = int(os.getenv("MEMORY_CHUNK_SIZE", str(10**6)))  # 1MB default
DISK_FILL_SIZE_MB = int(os.getenv("DISK_FILL_SIZE_MB", "110"))
CPU_BURN_THREADS = int(os.getenv("CPU_BURN_THREADS", "2"))  # Anzahl CPU-Burn Threads
CPU_BURN_DURATION = int(os.getenv("CPU_BURN_DURATION", "240"))  # Sekunden

DISK_JUNK_PATH = "/tmp/chaos_junk.bin"

# Thread-safe Lock für request_count
request_lock = threading.Lock()

state = {
    "request_count": 0,
    "is_unhealthy": False,
    "memory_hoard": [],
    "current_scenario": "NONE"
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan Context Manager für Startup/Shutdown."""
    # Startup
    asyncio.create_task(chaos_loop())
    yield
    # Shutdown (optional: cleanup)

app = FastAPI(lifespan=lifespan)

templates = Jinja2Templates(directory="templates")

# --- KUBERNETES PROBES ---

@app.get("/healthz")
def healthz():
    if state["is_unhealthy"]:
        return Response("Unhealthy", status_code=500)
    return {"status": "ok", "scenario": state["current_scenario"]}

@app.get("/readyz")
def readyz():
    if state["is_unhealthy"]:
        return Response("Not Ready", status_code=503)
    return {"status": "ready"}

@app.get("/")
async def index(request: Request):
    with request_lock:
        state["request_count"] += 1
        count = state["request_count"]

    if count % 3 == 0:
        return Response("Chaos Error", status_code=500)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "TIME": datetime.datetime.now().strftime("%H:%M:%S"),
            "SCENARIO": state["current_scenario"]
        }
    )

# --- CHAOS LOGIK ---

def fill_disk():
    try:
        with open(DISK_JUNK_PATH, "wb") as f:
            f.write(os.urandom(DISK_FILL_SIZE_MB * 1024 * 1024))
    except IOError as e:
        print(f"Disk full error as expected: {e}")


def cleanup_disk():
    """Entfernt die Chaos-Disk-Datei falls vorhanden."""
    try:
        if os.path.exists(DISK_JUNK_PATH):
            os.remove(DISK_JUNK_PATH)
    except OSError as e:
        print(f"Could not cleanup disk junk: {e}")

def reset_state():
    """Bereinigt den Status für das nächste Intervall."""
    state["is_unhealthy"] = False
    state["memory_hoard"] = []
    cleanup_disk()
    # Hinweis: CPU Threads lassen sich schwer stoppen,
    # daher nutzen wir dort im 'burn' eine Zeitbegrenzung.

async def chaos_loop():
    """Die Endlosschleife, die periodisch Chaos verursacht."""
    await asyncio.sleep(CHAOS_STARTUP_DELAY)

    while True:
        reset_state()
        scenarios = ["OOM_KILL", "CPU_BURN", "SLOW_DEATH", "STABLE", "CRASH", "DISK_FILL"]
        state["current_scenario"] = random.choice(scenarios)

        print(f"[{time.ctime()}] --- NEW CHAOS CYCLE: {state['current_scenario']} ---")

        if state["current_scenario"] == "OOM_KILL":
            # Füllt den Speicher langsam, bis das Limit knallt
            for _ in range(100):
                state["memory_hoard"].append(" " * MEMORY_CHUNK_SIZE)
                await asyncio.sleep(1)

        elif state["current_scenario"] == "CPU_BURN":
            # Erzeugt Last mit mehreren Threads für Multi-Core-Systeme
            def burn():
                end = time.time() + CPU_BURN_DURATION
                while time.time() < end:
                    pass
            for _ in range(CPU_BURN_THREADS):
                threading.Thread(target=burn, daemon=True).start()

        elif state["current_scenario"] == "SLOW_DEATH":
            state["is_unhealthy"] = True

        elif state["current_scenario"] == "CRASH":
            await asyncio.sleep(30)
            os._exit(1)

        elif state["current_scenario"] == "DISK_FILL":
            fill_disk()

        await asyncio.sleep(CHAOS_INTERVAL)

@app.get("/status")
def get_status():
    """Gibt den kompletten aktuellen Status zurück."""
    return {
        "current_scenario": state["current_scenario"],
        "is_unhealthy": state["is_unhealthy"],
        "request_count": state["request_count"],
        "memory_hoard_size_mb": len(state["memory_hoard"]) * MEMORY_CHUNK_SIZE / (1024 * 1024),
        "config": {
            "chaos_interval": CHAOS_INTERVAL,
            "cpu_burn_threads": CPU_BURN_THREADS,
            "cpu_burn_duration": CPU_BURN_DURATION,
            "memory_chunk_size": MEMORY_CHUNK_SIZE,
            "disk_fill_size_mb": DISK_FILL_SIZE_MB
        }
    }


@app.post("/chaos/reset")
def manual_reset():
    """Setzt den Chaos-Status manuell zurück."""
    reset_state()
    state["current_scenario"] = "MANUAL_RESET"
    return {"message": "Chaos state reset", "state": state["current_scenario"]}


@app.post("/chaos/cpu")
async def manual_cpu():
    state["current_scenario"] = "MANUAL_CPU"
    def burn():
        end = time.time() + CPU_BURN_DURATION
        while time.time() < end:
            pass
    for _ in range(CPU_BURN_THREADS):
        threading.Thread(target=burn, daemon=True).start()
    return {"message": f"Manual CPU spike started ({CPU_BURN_THREADS} threads)"}

@app.post("/chaos/oom")
async def manual_oom():
    state["current_scenario"] = "MANUAL_OOM"
    # Fügt 100MB auf einmal hinzu für schnelleren OOM-Effekt
    state["memory_hoard"].append(" " * (100 * MEMORY_CHUNK_SIZE))
    return {"message": "Manual OOM pressure added (100MB)"}

@app.post("/chaos/crash")
def crash():
    """Harter Crash ohne Cleanup (Simuliert Segfault)."""
    os._exit(1)

@app.post("/chaos/unhealthy")
def toggle_health():
    state["is_unhealthy"] = not state["is_unhealthy"]
    return {"is_unhealthy": state["is_unhealthy"]}

@app.post("/chaos/disk")
async def manual_disk():
    state["current_scenario"] = "MANUAL_DISK_FILL"
    threading.Thread(target=fill_disk, daemon=True).start()
    return {"message": "Disk fill started"}
