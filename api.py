"""FastAPI app: same Orchestrator as the CLI. Run: uvicorn api:app --port 8000"""
import json
import re
import threading
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(".env")

from engine.decision_engine import next_id  # noqa: E402
from agents.reading_agent import GroqClient  # noqa: E402
from engine.predict import predict  # noqa: E402
from engine.setup import setup_message, text_to_config  # noqa: E402
from state.state_manager import StateManager  # noqa: E402
from engine.orchestrator import Orchestrator, export_payload, parse_messages  # noqa: E402

app = FastAPI(title="Hackathon Event Planner")
ROOT = Path("hackathons")  # one folder per hackathon: config.json + state.json. "default" is the original state.json.
_orchs = {}


def orch_for(h):
    if not re.fullmatch(r"[a-z0-9-]{1,40}", h):
        raise HTTPException(400, "Bad hackathon id")
    if h != "default" and not (ROOT / h).is_dir():
        raise HTTPException(404, "No such hackathon")
    if h not in _orchs:
        _orchs[h] = Orchestrator(StateManager(None if h == "default" else ROOT / h / "state.json"))
    return _orchs[h]
lock = threading.Lock()  # one run at a time


class RunReq(BaseModel):
    messages_file: str


class MsgReq(BaseModel):
    text: str
    source: str = "Unknown"
    channel: str = "web"


def _run(h, msgs):
    orch = orch_for(h)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "A run is already in progress")
    try:
        return orch.run(msgs) or {"outcome": "NO_CHANGE"}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    finally:
        lock.release()


def _config_path(h):
    return ROOT / h / "config.json"


@app.get("/hackathons")
def hackathons():
    ids = ["default"] + sorted(p.name for p in ROOT.iterdir() if p.is_dir()) if ROOT.is_dir() else ["default"]
    out = []
    for i in ids:
        cfg = json.loads(_config_path(i).read_text()) if _config_path(i).exists() else {}
        out.append({"id": i, "name": cfg.get("name") or ("Default (sample)" if i == "default" else i)})
    return out


@app.post("/hackathons")
def create(cfg: dict):
    name = str(cfg.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Give the hackathon a name")
    h = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "hackathon"
    if h == "default" or (ROOT / h).exists():
        raise HTTPException(409, "A hackathon with that name exists")
    (ROOT / h).mkdir(parents=True)
    return {"id": h, **save_config(h, cfg)}


def save_config(h, cfg):
    """Stores the form and applies it as a lowest-authority message: later real messages override it."""
    _config_path(h).write_text(json.dumps(cfg, indent=2))
    orch = orch_for(h)
    n = sum(1 for m in orch.sm.load()["messages"] if m["source"] == "Setup form") + 1
    return {"run": _run(h, [setup_message(cfg, n)])}


@app.get("/hackathons/{h}/config")
def get_config(h: str):
    orch_for(h)
    return json.loads(_config_path(h).read_text()) if _config_path(h).exists() else {}


@app.put("/hackathons/{h}/config")
def put_config(h: str, cfg: dict):
    orch_for(h)
    if h == "default":
        _config_path(h).parent.mkdir(exist_ok=True)
    return save_config(h, cfg)


class TextReq(BaseModel):
    text: str


@app.post("/setup/from-text")
def from_text(req: TextReq):
    """Groq turns a description into form fields. Nothing is saved: the user reviews the form first."""
    if not req.text.strip():
        raise HTTPException(400, "Describe the hackathon first")
    try:
        return text_to_config(req.text, GroqClient)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except Exception as e:  # network/API/JSON failure
        raise HTTPException(502, f"Could not read the description: {e}")


@app.post("/run")
def run(req: RunReq, h: str = Query("default")):
    try:
        text = open(req.messages_file, encoding="utf-8").read()
    except OSError as e:
        raise HTTPException(400, str(e))
    try:
        msgs = parse_messages(text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _run(h, msgs)


class UploadReq(BaseModel):
    text: str


@app.post("/upload")
def upload(req: UploadReq, h: str = Query("default")):
    """Same path as the CLI: parse the pasted/uploaded message file, run, validate. 4+ unseen messages start a fresh run."""
    try:
        msgs = parse_messages(req.text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _run(h, msgs)


@app.post("/message")
def message(req: MsgReq, h: str = Query("default")):
    if not req.text.strip():
        raise HTTPException(400, "Message text is empty")
    m = {"id": next_id(orch_for(h).sm.load()["messages"], "MSG"), "source": req.source.strip() or "Unknown",
         "channel": req.channel, "date": date.today().isoformat(), "text": req.text.strip()}
    return _run(h, [m])


@app.get("/state")
def state(h: str = Query("default")):
    return orch_for(h).sm.load()


@app.get("/plan")
def plan(h: str = Query("default")):
    s = orch_for(h).sm.load()
    p = next((p for p in s["plans"] if p["id"] == s["active_plan_id"]), None)
    if not p:  # fall back to the latest attempt so the UI can show why there is no plan
        p = next((p for p in reversed(s["plans"]) if p["status"] == "INCOMPLETE"), None)
    last, rejection = (s["runs"][-1] if s["runs"] else None), None
    if last and last["outcome"] == "REJECTED":  # the active plan is unchanged; tell the UI why the last change was refused
        rejection = {"reason": next(x["rejection_reason"] for x in s["plans"] if x["id"] == last["plan_id"]),
                     "message_ids": last.get("rejected", [])}
    return {"rejection": rejection, "plan": p, "pending_planners": s["pending_planners"], "last_run": s["runs"][-1] if s["runs"] else None,
            "running": lock.locked()}


@app.get("/predict")
def predict_areas():
    return predict()


@app.get("/export")
def export(h: str = Query("default")):
    return export_payload(orch_for(h).sm.load())


@app.get("/trace")
def trace(h: str = Query("default")):
    s = orch_for(h).sm.load()
    return {"trace": s["trace"], "runs": s["runs"]}


@app.get("/messages")
def messages(h: str = Query("default")):
    s = orch_for(h).sm.load()
    facts = {}
    for f in s["facts"]:
        facts.setdefault(f["source_message_id"], []).append(f)
    return [{**m, "facts": facts.get(m["id"], [])} for m in s["messages"]]


app.mount("/", StaticFiles(directory="frontend/out", html=True), name="ui")
