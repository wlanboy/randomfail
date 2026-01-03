from fastapi import FastAPI, Response, status
from fastapi.responses import HTMLResponse
from datetime import datetime
import random

app = FastAPI()

# Toggle für jeden zweiten Request
request_counter = {"count": 0}

def maybe_fail():
    # Jeder zweite Request schlägt fehl
    request_counter["count"] += 1
    if request_counter["count"] % 2 == 0:
        return True
    return False

@app.get("/", response_class=HTMLResponse)
def index():
    if maybe_fail():
        return Response("Internal Server Error", status_code=500)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("index.html", "r") as f:
        html = f.read().replace("{{TIME}}", now)
    return HTMLResponse(content=html, status_code=200)

@app.get("/healthz")
def healthz():
    # 20% zufällige Fehler
    if random.random() < 0.2:
        return Response("Unhealthy", status_code=500)
    return {"status": "ok"}

@app.get("/readyz")
def readyz():
    # 20% zufällige Fehler
    if random.random() < 0.2:
        return Response("Not Ready", status_code=500)
    return {"status": "ready"}
