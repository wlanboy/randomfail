import asyncio
import datetime
import os
import random
import signal
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.templating import Jinja2Templates

# Konfiguration via Environment-Variablen
CHAOS_INTERVAL = int(os.getenv("CHAOS_INTERVAL", "300"))  # Sekunden zwischen Chaos-Zyklen
CHAOS_STARTUP_DELAY = int(os.getenv("CHAOS_STARTUP_DELAY", "10"))  # Initialer Puffer
MEMORY_CHUNK_SIZE = int(os.getenv("MEMORY_CHUNK_SIZE", str(10**6)))  # 1MB default
DISK_FILL_SIZE_MB = int(os.getenv("DISK_FILL_SIZE_MB", "110"))
CPU_BURN_THREADS = int(os.getenv("CPU_BURN_THREADS", "2"))  # Anzahl CPU-Burn Threads
CPU_BURN_DURATION = int(os.getenv("CPU_BURN_DURATION", "120"))  # Sekunden (max CHAOS_INTERVAL / 2)
SLOW_RESPONSE_DELAY = int(os.getenv("SLOW_RESPONSE_DELAY", "5"))  # Sekunden künstliche Verzögerung
SIGTERM_DELAY = int(os.getenv("SIGTERM_DELAY", "30"))  # Sekunden bis zum sauberen Shutdown
READINESS_FLAP_INTERVAL = int(os.getenv("READINESS_FLAP_INTERVAL", "5"))  # Sekunden zwischen Readiness-Toggles
SLOW_AFFECTS_PROBES = os.getenv("SLOW_AFFECTS_PROBES", "false").lower() == "true"  # Verzögerung auch für /healthz & /readyz

PROBE_PATHS = ("/healthz", "/readyz")
DISK_WRITE_CHUNK = 1024 * 1024  # Disk-Fill in 1MB-Blöcken, um RAM-Spitzen zu vermeiden

DISK_JUNK_PATH = "/tmp/chaos_junk.bin"

# Thread-safe Lock für gemeinsam genutzten State (request_count, fd_hoard, memory_hoard)
state_lock = threading.Lock()

state = {
    "request_count": 0,
    "is_unhealthy": False,
    "is_not_ready": False,
    "memory_hoard": [],
    "fd_hoard": [],
    "current_scenario": "NONE"
}

# Laufende Hintergrund-Tasks je Szenario-Typ. Die Referenz verhindert, dass der GC laufende
# Tasks einsammelt; pro Name läuft höchstens ein Task (ein Neustart bricht den alten ab).
background_tasks: dict[str, asyncio.Task] = {}

# Stop-Signal für die aktuell laufenden CPU-Burn-Threads
cpu_stop = threading.Event()


def spawn(name: str, coro) -> None:
    """Startet einen Hintergrund-Task und bricht einen laufenden Task gleichen Namens ab."""
    task = asyncio.create_task(coro)
    with state_lock:
        old = background_tasks.get(name)
        background_tasks[name] = task
    if old is not None:
        old.cancel()
    task.add_done_callback(lambda t: _forget_task(name, t))


def _forget_task(name: str, task: asyncio.Task) -> None:
    with state_lock:
        if background_tasks.get(name) is task:
            del background_tasks[name]


def cancel_background_tasks() -> None:
    """Bricht alle Hintergrund-Tasks ab. Threadsafe, da sync-Endpoints im Threadpool laufen."""
    with state_lock:
        tasks = list(background_tasks.values())
        background_tasks.clear()
    for task in tasks:
        loop = task.get_loop()
        if not task.done() and not loop.is_closed():
            loop.call_soon_threadsafe(task.cancel)


def stop_cpu_burn() -> None:
    """Signalisiert allen laufenden Burn-Threads das Ende."""
    global cpu_stop
    cpu_stop.set()
    cpu_stop = threading.Event()


_sigterm_task: asyncio.Task | None = None


def _on_sigterm() -> None:
    global _sigterm_task
    if _sigterm_task is None:
        _sigterm_task = asyncio.create_task(_sigterm_delay())


async def _sigterm_delay():
    """Verzögerter SIGTERM-Handler – testet terminationGracePeriodSeconds."""
    print(f"[{time.ctime()}] SIGTERM received, waiting {SIGTERM_DELAY}s before exit...")
    state["current_scenario"] = "SIGTERM_DELAY"
    state["is_unhealthy"] = True
    await asyncio.sleep(SIGTERM_DELAY)
    os._exit(0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan Context Manager für Startup/Shutdown."""
    # Startup
    # Muss über die Event-Loop registriert werden (nicht signal.signal auf Modulebene):
    # uvicorn installiert seinen eigenen SIGTERM-Handler erst beim Server-Start und
    # würde einen zuvor über signal.signal() gesetzten Handler sonst überschreiben.
    # Zudem bleibt der Event-Loop so während der Wartezeit responsive für /healthz & /readyz.
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, _on_sigterm)
    except (RuntimeError, NotImplementedError) as e:
        # z.B. in Tests, wo die Event-Loop nicht im Hauptthread läuft
        print(f"Could not register SIGTERM handler: {e}")
    chaos_task = asyncio.create_task(chaos_loop())
    yield
    chaos_task.cancel()
    cancel_background_tasks()
    stop_cpu_burn()

app = FastAPI(lifespan=lifespan)

templates = Jinja2Templates(directory="templates")

@app.middleware("http")
async def slow_response_middleware(request: Request, call_next):
    if state["current_scenario"] in ("SLOW_RESPONSE", "MANUAL_SLOW") and (
        SLOW_AFFECTS_PROBES or request.url.path not in PROBE_PATHS
    ):
        await asyncio.sleep(SLOW_RESPONSE_DELAY)
    return await call_next(request)

# --- KUBERNETES PROBES ---

@app.get("/healthz")
def healthz(response: Response):
    if state["is_unhealthy"]:
        response.status_code = 500
        return {"status": "unhealthy", "scenario": state["current_scenario"]}
    return {"status": "ok", "scenario": state["current_scenario"]}

@app.get("/readyz")
def readyz(response: Response):
    if state["is_unhealthy"] or state["is_not_ready"]:
        response.status_code = 503
        return {"status": "not ready"}
    return {"status": "ready"}

@app.get("/")
async def index(request: Request):
    with state_lock:
        state["request_count"] += 1
        count = state["request_count"]

    if count % 3 == 0:
        return Response("Chaos Error", status_code=500)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "TIME": datetime.datetime.now(tz=datetime.UTC).astimezone().strftime("%H:%M:%S"),
            "SCENARIO": state["current_scenario"]
        }
    )

# --- CHAOS LOGIK ---

def fill_disk():
    """Schreibt DISK_FILL_SIZE_MB blockweise, damit nie mehr als ein Block im RAM liegt."""
    try:
        with open(DISK_JUNK_PATH, "wb") as f:
            f.writelines(os.urandom(DISK_WRITE_CHUNK) for _ in range(DISK_FILL_SIZE_MB * 1024 * 1024 // DISK_WRITE_CHUNK))
    except OSError as e:
        print(f"Disk full error as expected: {e}")


def cleanup_disk():
    """Entfernt die Chaos-Disk-Datei falls vorhanden."""
    try:
        if os.path.exists(DISK_JUNK_PATH):
            os.remove(DISK_JUNK_PATH)
    except OSError as e:
        print(f"Could not cleanup disk junk: {e}")

def exhaust_fds():
    """Öffnet /dev/null so lange, bis das FD-Limit erreicht ist."""
    try:
        while True:
            fd = open("/dev/null", "r")  # noqa: SIM115
            with state_lock:
                state["fd_hoard"].append(fd)
    except OSError as e:
        print(f"FD exhaustion reached as expected: {e}")

def cleanup_fds():
    with state_lock:
        fds = state["fd_hoard"]
        state["fd_hoard"] = []
    for f in fds:
        try:
            f.close()
        except OSError:
            pass

def reset_state():
    """Bereinigt den Status für das nächste Intervall."""
    cancel_background_tasks()
    stop_cpu_burn()
    state["is_unhealthy"] = False
    state["is_not_ready"] = False
    with state_lock:
        state["memory_hoard"] = []
    cleanup_disk()
    cleanup_fds()

# --- SZENARIEN (genutzt von chaos_loop und den manuellen Endpoints) ---

def start_oom() -> None:
    """Allokiert ohne Obergrenze 1 Chunk/s, bis der OOM-Killer eingreift oder reset erfolgt."""
    async def fill_memory():
        while True:
            with state_lock:
                state["memory_hoard"].append(" " * MEMORY_CHUNK_SIZE)
            await asyncio.sleep(1)
    spawn("oom", fill_memory())


def start_cpu_burn() -> None:
    """Startet CPU_BURN_THREADS Burn-Threads; bereits laufende werden vorher gestoppt."""
    stop_cpu_burn()
    stop = cpu_stop

    def burn():
        end = time.time() + CPU_BURN_DURATION
        while time.time() < end and not stop.is_set():
            pass
    for _ in range(CPU_BURN_THREADS):
        threading.Thread(target=burn, daemon=True).start()


def start_readiness_flap() -> None:
    async def flap_readiness():
        try:
            while True:
                state["is_not_ready"] = not state["is_not_ready"]
                await asyncio.sleep(READINESS_FLAP_INTERVAL)
        finally:
            state["is_not_ready"] = False
    spawn("flap", flap_readiness())

async def chaos_loop():
    """Die Endlosschleife, die periodisch Chaos verursacht."""
    await asyncio.sleep(CHAOS_STARTUP_DELAY)

    while True:
        reset_state()
        scenarios = ["OOM_KILL", "CPU_BURN", "SLOW_DEATH", "STABLE", "CRASH", "DISK_FILL", "SLOW_RESPONSE", "FD_EXHAUSTION", "READINESS_FLAP"]
        state["current_scenario"] = random.choice(scenarios)

        print(f"[{time.ctime()}] --- NEW CHAOS CYCLE: {state['current_scenario']} ---")

        if state["current_scenario"] == "OOM_KILL":
            start_oom()

        elif state["current_scenario"] == "CPU_BURN":
            start_cpu_burn()

        elif state["current_scenario"] == "SLOW_DEATH":
            state["is_unhealthy"] = True

        elif state["current_scenario"] == "CRASH":
            await asyncio.sleep(30)
            os._exit(1)

        elif state["current_scenario"] == "DISK_FILL":
            await asyncio.to_thread(fill_disk)

        elif state["current_scenario"] == "SLOW_RESPONSE":
            pass  # Middleware wertet current_scenario aus

        elif state["current_scenario"] == "FD_EXHAUSTION":
            threading.Thread(target=exhaust_fds, daemon=True).start()

        elif state["current_scenario"] == "READINESS_FLAP":
            start_readiness_flap()

        await asyncio.sleep(CHAOS_INTERVAL)

@app.get("/status")
def get_status():
    """Gibt den kompletten aktuellen Status zurück."""
    with state_lock:
        request_count = state["request_count"]
        memory_hoard_len = len(state["memory_hoard"])
        fd_hoard_count = len(state["fd_hoard"])
    return {
        "current_scenario": state["current_scenario"],
        "is_unhealthy": state["is_unhealthy"],
        "is_not_ready": state["is_not_ready"],
        "request_count": request_count,
        "memory_hoard_size_mb": memory_hoard_len * MEMORY_CHUNK_SIZE / (1024 * 1024),
        "fd_hoard_count": fd_hoard_count,
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
    start_cpu_burn()
    return {"message": f"Manual CPU spike started ({CPU_BURN_THREADS} threads)"}

@app.post("/chaos/oom")
async def manual_oom():
    state["current_scenario"] = "MANUAL_OOM"
    # Fügt 100 Chunks (100MB) auf einmal hinzu für schnelleren OOM-Effekt
    with state_lock:
        state["memory_hoard"].extend(" " * MEMORY_CHUNK_SIZE for _ in range(100))
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

@app.post("/chaos/slow")
async def manual_slow():
    state["current_scenario"] = "MANUAL_SLOW"
    return {"message": f"Slow response mode active ({SLOW_RESPONSE_DELAY}s delay per request)"}

@app.post("/chaos/fd")
async def manual_fd():
    state["current_scenario"] = "MANUAL_FD_EXHAUSTION"
    threading.Thread(target=exhaust_fds, daemon=True).start()
    return {"message": "FD exhaustion started"}

@app.post("/chaos/flap")
async def manual_flap():
    state["current_scenario"] = "READINESS_FLAP"
    start_readiness_flap()
    return {"message": f"Readiness flapping started (interval: {READINESS_FLAP_INTERVAL}s)"}
