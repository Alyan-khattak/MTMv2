"""Owns every read/write of state.json. Two-phase write with .bak recovery."""
import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

log = logging.getLogger("state")


def empty_state():
    return {"version": 1, "last_updated": None, "messages": [], "facts": [], "constraints": [],
            "decisions": [], "plans": [], "active_plan_id": None, "pending_planners": [], "trace": [], "runs": []}


class StateManager:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("STATE_FILE", "state.json"))
        self.tmp = self.path.with_name(self.path.name + ".tmp")
        self.bak = self.path.with_name(self.path.name + ".bak")
        self.warnings = []

    def _warn(self, msg):
        self.warnings.append(msg)
        log.warning(msg)

    def load(self):
        if self.tmp.exists():  # interrupted write: discard
            self.tmp.unlink()
        for p in (self.path, self.bak):
            if not p.exists():
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._warn(f"{p.name} is corrupted; trying backup")
                continue
            if p is self.bak:
                self._warn("Loaded state from backup")
            return {**empty_state(), **data}
        return empty_state()

    def save(self, state):
        state = {**state, "last_updated": datetime.now().isoformat(timespec="seconds")}
        payload = json.dumps(state, indent=2, ensure_ascii=False)
        with open(self.tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        json.loads(self.tmp.read_text(encoding="utf-8"))  # validate before swapping in
        if self.path.exists():
            os.replace(self.path, self.bak)
        os.replace(self.tmp, self.path)
        if not self.bak.exists():  # first ever write: keep a backup anyway
            shutil.copyfile(self.path, self.bak)
