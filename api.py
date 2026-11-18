"""FastAPI app: same Orchestrator as the CLI. Run: uvicorn api:app --port 8000"""
import threading
from datetime import date

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(".env")

from engine.decision_engine import next_id  # noqa: E402
from engine.orchestrator import Orchestrator, parse_messages  # noqa: E402

app = FastAPI(title="Hackathon Event Planner")
orch = Orchestrator()
lock = threading.Lock()  # one run at a time


class RunReq(BaseModel):
    messages_file: str


class MsgReq(BaseModel):
    text: str
    source: str = "Unknown"
    channel: str = "web"


def _run(msgs):
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "A run is already in progress")
    try:
        return orch.run(msgs) or {"outcome": "NO_CHANGE"}
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    finally:
        lock.release()


@app.post("/run")
def run(req: RunReq):
    try:
        text = open(req.messages_file, encoding="utf-8").read()
    except OSError as e:
        raise HTTPException(400, str(e))
    return _run(parse_messages(text))


@app.post("/message")
def message(req: MsgReq):
    if not req.text.strip():
        raise HTTPException(400, "Message text is empty")
    m = {"id": next_id(orch.sm.load()["messages"], "MSG"), "source": req.source.strip() or "Unknown",
         "channel": req.channel, "date": date.today().isoformat(), "text": req.text.strip()}
    return _run([m])


@app.get("/state")
def state():
    return orch.sm.load()


@app.get("/plan")
def plan():
    s = orch.sm.load()
    p = next((p for p in s["plans"] if p["id"] == s["active_plan_id"]), None)
    if not p:  # fall back to the latest attempt so the UI can show why there is no plan
        p = next((p for p in reversed(s["plans"]) if p["status"] == "INCOMPLETE"), None)
    return {"plan": p, "pending_planners": s["pending_planners"], "last_run": s["runs"][-1] if s["runs"] else None,
            "running": lock.locked()}


@app.get("/trace")
def trace():
    s = orch.sm.load()
    return {"trace": s["trace"], "runs": s["runs"]}


@app.get("/messages")
def messages():
    s = orch.sm.load()
    facts = {}
    for f in s["facts"]:
        facts.setdefault(f["source_message_id"], []).append(f)
    return [{**m, "facts": facts.get(m["id"], [])} for m in s["messages"]]


app.mount("/", StaticFiles(directory="frontend/out", html=True), name="ui")
