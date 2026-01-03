from fastapi import FastAPI, Response
import random
import asyncio 
import os
import threading
import time

app = FastAPI()

state = {
    "request_count": 0,
    "is_unhealthy": False,
    "memory_hoard": [],
    "current_scenario": "NONE"
}

# --- KUBERNETES PROBES ---

@app.get("/healthz")
def healthz():
    if state["is_unhealthy"]:
        return Response("Unhealthy", status_code=500)
    return {"status": "ok", "scenario": state["current_scenario"]}

@app.get("/readyz")
def readyz():
    return {"status": "ready"}

@app.get("/")
async def root():
    state["request_count"] += 1
    if state["request_count"] % 3 == 0:
        return Response("Chaos Error", status_code=500)
    return {"message": "Stable", "scenario": state["current_scenario"]}

# --- CHAOS LOGIK ---

def reset_state():
    """Bereinigt den Status für das nächste Intervall."""
    state["is_unhealthy"] = False
    state["memory_hoard"] = [] 
    # Hinweis: CPU Threads lassen sich schwer stoppen, 
    # daher nutzen wir dort im 'burn' eine Zeitbegrenzung.

async def chaos_loop():
    """Die Endlosschleife, die alle 5 Minuten zuschlägt."""
    await asyncio.sleep(10) # Initialer Puffer beim Start
    
    while True:
        reset_state()
        scenarios = ["OOM_KILL", "CPU_BURN", "SLOW_DEATH", "STABLE", "CRASH"]
        state["current_scenario"] = random.choice(scenarios)
        
        print(f"[{time.ctime()}] --- NEW CHAOS CYCLE: {state['current_scenario']} ---")

        if state["current_scenario"] == "OOM_KILL":
            # Füllt den Speicher langsam über 2 Minuten, bis das Limit (256Mi) knallt
            for _ in range(100):
                state["memory_hoard"].append(" " * 10**6) # 1MB
                await asyncio.sleep(1)

        elif state["current_scenario"] == "CPU_BURN":
            # Erzeugt Last für 4 Minuten (etwas weniger als das Intervall)
            def burn():
                end = time.time() + 240
                while time.time() < end: pass
            threading.Thread(target=burn, daemon=True).start()

        elif state["current_scenario"] == "SLOW_DEATH":
            state["is_unhealthy"] = True

        elif state["current_scenario"] == "CRASH":
            await asyncio.sleep(30)
            os._exit(1)

        # Warte 5 Minuten bis zum nächsten Würfeln
        await asyncio.sleep(300)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(chaos_loop())

@app.post("/chaos/cpu")
async def manual_cpu():
    state["current_scenario"] = "MANUAL_CPU"
    threading.Thread(target=lambda: [time.time() for _ in range(10**8)], daemon=True).start()
    return {"message": "Manual CPU spike started"}

@app.post("/chaos/oom")
async def manual_oom():
    state["current_scenario"] = "MANUAL_OOM"
    state["memory_hoard"].append(" " * 10**8)
    return {"message": "Manual OOM pressure added"}

@app.post("/chaos/crash")
def crash():
    """Harter Crash ohne Cleanup (Simuliert Segfault)."""
    os._exit(1)

@app.post("/chaos/unhealthy")
def toggle_health():
    state["is_unhealthy"] = not state["is_unhealthy"]
    return {"is_unhealthy": state["is_unhealthy"]}
