import json
from types import SimpleNamespace as NS

import pytest

from engine.decision_engine import authority_rank
from engine.dependency_resolver import resolve
from engine.orchestrator import Orchestrator, parse_messages
from planners.budget_planner import headcount
from models.schemas import Facts
from state.state_manager import StateManager

SAMPLE = open("data/sample_messages.txt", encoding="utf-8").read()
F = lambda k, v, s=None, a=True: {"key": k, "subject": s, "value": v, "approved": a}
READS = {
    "4-hour": [F("event.duration_hours", 4), F("event.student_count", 150), F("event.team_size", 3), F("event.staff_count", 10),
               F("event.budget_limit", 650000), F("event.prayer_break_minutes", 15)],
    "Room D": [F(k, v, n) for n, c, p, g in (("Room D", 80, 40000, False), ("Hall A", 200, 120000, False), ("Hall B", 200, 150000, True),
               ("Hall C", 300, 220000, True)) for k, v in (("venue.capacity", c), ("venue.price", p), ("venue.generator", g))],
    "Standard lunch box Rs 1,000": [F("food.price_per_person", 1000, "Standard")],
    "ab Rs 1,200": [F("food.price_per_person", 1200, "Standard"), F("food.price_per_person", 800, "Basic")],
    "20 judges": [F("judging.judge_count", 20), F("judging.honorarium", 5000), F("judging.minutes_per_team", 15), F("judging.max_teams_per_judge", 3)],
    "prizes": [F("budget.prizes", 100000), F("budget.backup_internet", 20000), F("budget.printing_cost", 10000)],
    "DJ": [F("budget.dj", 50000, a=False)],
    "late on the day": [],
    "Printing now": [F("budget.printing_cost", 15000)],
    "100 boxes": [F("food.box_count", 100)],
}


class Fake:
    def __init__(self):
        self.areas = []

    def chat(self, system, user, timeout):
        usage = NS(prompt_tokens=7, completion_tokens=3, total_tokens=10)
        if user.startswith("Source:"):
            self.areas.append("reading")
            out = {"facts": next(v for k, v in READS.items() if k in user)}
        else:
            self.areas.append("venue" if "venue" in system else "food")
            out = {"selected": "Hall A" if "venue" in system else "Standard"}
        return json.dumps(out), usage


@pytest.fixture
def env(tmp_path):
    fake = Fake()
    return Orchestrator(StateManager(tmp_path / "s.json"), lambda: fake), fake


def msg(i, src, text, date="2026-11-20"):
    return {"id": i, "source": src, "channel": "email", "date": date, "text": text}


def test_full_run(env):
    o, fake = env
    r = o.run(parse_messages(SAMPLE))
    st = o.sm.load()
    assert r["outcome"] == "COMMITTED" and r["planners_run"] == ["venue", "food", "judging", "schedule", "budget"]
    plan = st["plans"][-1]
    assert plan["budget"]["total"] <= 650000 and plan["food"]["headcount"] == 180
    status = {m["id"]: m["status"] for m in st["messages"]}
    assert status["MSG_003"] == "SUPERSEDED" and status["MSG_008"] == "IRRELEVANT" and status["MSG_007"] == "REJECTED"
    assert r["total_tokens"] == 10 * len(fake.areas)


def test_incremental_printing_only_budget(env):
    o, fake = env
    o.run(parse_messages(SAMPLE)); fake.areas.clear()
    r = o.run([msg("MSG_009", "Finance", "Printing now Rs 15,000")])
    assert r["planners_run"] == ["budget"] and fake.areas == ["reading"]
    assert o.sm.load()["plans"][-1]["budget"]["printing"] == 15000


def test_wrong_message_rejected_and_plan_unchanged(env):
    o, _ = env
    o.run(parse_messages(SAMPLE))
    before = o.sm.load()["active_plan_id"]
    r = o.run([msg("MSG_010", "Caterer", "Order 100 boxes please")])
    st = o.sm.load()
    m = next(m for m in st["messages"] if m["id"] == "MSG_010")
    assert r["outcome"] == "REJECTED" and st["active_plan_id"] == before
    assert m["status"] == "REJECTED" and "food.quantity: 100 < 180" in m["reason"]


def test_duplicate_skipped(env):
    o, fake = env
    o.run(parse_messages(SAMPLE)); fake.areas.clear()
    assert o.run(parse_messages(SAMPLE)) is None
    r = o.run([msg("MSG_X", "A judge", "I may be 10 minutes late on the day. Traffic on Srinagar Highway.")])
    assert fake.areas == [] and o.sm.load()["messages"][-1]["status"] == "DUPLICATE"


def test_resolver():
    assert resolve({"budget.printing_cost"})[0] == ["budget"]
    assert resolve({"event.student_count"})[0] == ["venue", "food", "judging", "schedule", "budget"]
    assert resolve({"nonsense"}) == ([], ["nonsense"])


def test_headcount_and_authority():
    f = Facts([{"status": "ACCEPTED", "key": k, "subject": None, "value": v}
               for k, v in (("event.student_count", 5), ("event.staff_count", 2), ("judging.judge_count", 3))])
    assert headcount(f) == 10
    assert authority_rank("Dean's office") < authority_rank("Finance") < authority_rank("Caterer") < authority_rank("A judge")
