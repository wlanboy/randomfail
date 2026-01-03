from fastapi import FastAPI, Response
import random
import asyncio 
import os
import threading
import time

app = FastAPI()

# Globaler Status für dynamische Tests
state = {
    "request_count": 0,
    "is_unhealthy": False,
    "memory_hoard": []
}

@app.get("/")
async def root():
    state["request_count"] += 1
    # Simuliere intermittierende Fehler (Flapping)
    if state["request_count"] % 3 == 0:
        return Response("Chaos Error", status_code=500)
    return {"message": "Stable for now", "requests": state["request_count"]}

# --- KUBERNETES PROBES ---

@app.get("/healthz")
def healthz():
    # Erlaubt es dir, den Container manuell über API "krank" zu machen
    if state["is_unhealthy"] or random.random() < 0.1:
        return Response("Unhealthy", status_code=500)
    return {"status": "ok"}

@app.get("/readyz")
def readyz():
    # Simuliere eine langsame Applikation (Latenz-Monitoring Test)
    if random.random() < 0.3:
        time.sleep(2) 
    return {"status": "ready"}

# --- CHAOS ENDPUNKTE ---

@app.post("/chaos/oom")
async def cause_oom():
    """Simuliert einen Memory Leak bis zum OOMKill."""
    def leak():
        while True:
            state["memory_hoard"].append(" " * 10**7) # 10MB Schritte
            time.sleep(0.1)
    threading.Thread(target=leak, daemon=True).start()
    return {"message": "Memory leak started. Watch out for OOMKill!"}

@app.post("/chaos/cpu")
async def cause_cpu_spike():
    """Erzeugt 100% CPU Last auf einem Kern für 30 Sekunden."""
    def burn():
        start = time.time()
        while time.time() - start < 30:
            pass
    threading.Thread(target=burn, daemon=True).start()
    return {"message": "CPU spike started for 30s"}

@app.post("/chaos/crash")
def crash():
    """Harter Crash ohne Cleanup (Simuliert Segfault)."""
    os._exit(1)

@app.post("/chaos/unhealthy")
def toggle_health():
    state["is_unhealthy"] = not state["is_unhealthy"]
    return {"is_unhealthy": state["is_unhealthy"]}

async def schedule_chaos():
    """Wählt beim Start zufällig ein Versagensszenario aus."""
    
    # Warte eine kurze Zeit, damit der Pod erst mal als "Ready" erscheint
    await asyncio.sleep(30) 
    
    scenarios = [
        "OOM_KILL",      # Speicher vollhauen
        "CPU_BURN",      # CPU auf 100%
        "ZOMBIE",        # Prozess läuft, reagiert aber nicht mehr (Deadlock)
        "RANDOM_CRASH",  # Einfach sofort beenden
        "SLOW_DEATH"     # Immer langsamer werdende Probes
    ]
    
    chosen = random.choice(scenarios)
    print(f"--- CHAOS MODE ACTIVATED: {chosen} ---")

    if chosen == "OOM_KILL":
        # Simuliert ein Memory Leak bis zum Limit
        while True:
            state["memory_hoard"].append(" " * 10**6)
            await asyncio.sleep(0.1)

    elif chosen == "CPU_BURN":
        # Erzeugt Dauerlast auf einem Kern
        def burn():
            while True: pass
        threading.Thread(target=burn, daemon=True).start()

    elif chosen == "ZOMBIE":
        # Blockiert den Event-Loop -> Probes werden fehlschlagen (Timeout)
        time.sleep(3600) 

    elif chosen == "RANDOM_CRASH":
        # Stirbt einfach irgendwann zwischen 10 und 60 Sekunden
        await asyncio.sleep(random.randint(10, 60))
        os._exit(1)

    elif chosen == "SLOW_DEATH":
        # Setzt die Health auf False, damit die Liveness Probe zuschlägt
        state["is_unhealthy"] = True

@app.on_event("startup")
async def startup_event():
    # Wir starten das Chaos in einem Background-Task
    asyncio.create_task(schedule_chaos())