import json
import re
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
        self.areas.append("reading")
        blocks = re.split(r"(?m)^\[(\d+)\] Source:", user)[1:]
        msgs = [{"n": int(n), "facts": next((v for k, v in READS.items() if k in body), [])}
                for n, body in zip(blocks[::2], blocks[1::2])]
        return json.dumps({"messages": msgs}), usage


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
    assert fake.areas == ["reading"] and r["total_tokens"] == 10  # whole pack = one call


def test_incremental_printing_only_budget(env):
    o, fake = env
    o.run(parse_messages(SAMPLE)); fake.areas.clear()
    r = o.run([msg("MSG_009", "Finance", "Printing now Rs 15,000")])
    assert r["planners_run"] == ["venue", "food", "budget"] and fake.areas == ["reading"]
    assert o.sm.load()["plans"][-1]["budget"]["printing"] == 15000 and o.sm.load()["plans"][-1]["food"]["total_cost"] > 0


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
    assert resolve({"budget.printing_cost"})[0] == ["venue", "food", "budget"]
    assert resolve({"event.student_count"})[0] == ["venue", "food", "judging", "schedule", "budget"]
    assert resolve({"nonsense"}) == (["venue", "food", "judging", "schedule", "budget"], ["nonsense"])


def test_headcount_and_authority():
    f = Facts([{"status": "ACCEPTED", "key": k, "subject": None, "value": v}
               for k, v in (("event.student_count", 5), ("event.staff_count", 2), ("judging.judge_count", 3))])
    assert headcount(f) == 10
    assert authority_rank("Dean's office") < authority_rank("Finance") < authority_rank("Caterer") < authority_rank("A judge")


def test_parser_formats():
    t = "MSG_1 | Dean's office, email | 9 Nov\nBudget is Rs 5.\nM2 | Finance | whatsapp | 2026-11-10 | hello there"
    m = parse_messages(t)
    assert [(x["id"], x["source"], x["channel"], x["date"]) for x in m] == [
        ("MSG_1", "Dean's office", "email", f"{__import__('datetime').datetime.now().year}-11-09"),
        ("M2", "Finance", "whatsapp", "2026-11-10")] and m[1]["text"] == "hello there"
    assert parse_messages("From: Dean\nDate: 9 Nov 2026\nMessage: hi all")[0]["date"] == "2026-11-09"
    with pytest.raises(ValueError):
        parse_messages("just some prose with no headers")


def test_unseen_constraint_kinds(env):
    o, _ = env
    READS["closing"] = [F("venue.closing_hour", 12), F("event.start_hour", 9), F("note.dress", True, "Wear ID badges")]
    READS["extra spend"] = [F("budget.security", 30000)]
    o.run(parse_messages(SAMPLE))
    r = o.run([msg("MSG_20", "Finance", "extra spend: security Rs 30,000")])
    assert r["outcome"] == "COMMITTED" and o.sm.load()["plans"][-1]["budget"]["security"] == 30000
    r = o.run([msg("MSG_21", "Dean's office", "closing hour is 12")])
    st = o.sm.load()
    assert r["outcome"] == "REJECTED" and "venue.closing_hour" in st["plans"][-1]["rejection_reason"]


def test_new_pack_starts_fresh(env):
    o, fake = env
    o.run(parse_messages(SAMPLE))
    pack = [msg(f"X{i}", "Dean's office", t) for i, t in enumerate(["4-hour", "Room D", "Standard lunch box Rs 1,000", "20 judges"])]
    r = o.run(pack)
    assert r["type"] == "full" and o.sm.path.with_name("s.json.old").exists()
    assert len(o.sm.load()["messages"]) == 4


CFG = {"name": "Mini Hack", "students": 40, "team_size": 4, "staff": 5, "duration_hours": 4, "budget": 400000,
       "prayer_minutes": 15, "venues": [{"name": "hall a", "capacity": 100, "price": 50000, "generator": True}],
       "food": [{"name": "basic", "price": 500}],
       "judging": {"count": 5, "honorarium": 2000, "minutes_per_team": 10, "max_teams_per_judge": 3},
       "extras": {"Prizes": 20000}, "notes": ["Bring ID"]}


def test_setup_form_plans_without_model_and_messages_override(env):
    from engine.setup import setup_message
    o, fake = env
    r = o.run([setup_message(CFG, 1)])
    plan = o.sm.load()["plans"][-1]
    assert r["outcome"] == "COMMITTED" and fake.areas == [] and plan["budget"]["prizes"] == 20000
    assert plan["unenforced"][0]["subject"] == "Bring ID"
    READS["prize raise"] = [F("budget.prizes", 30000)]
    o.run([msg("MSG_1", "A student", "prize raise")])  # student outranks "Setup form"
    assert o.sm.load()["plans"][-1]["budget"]["prizes"] == 30000


def test_setup_removal_retracts(env):
    from engine.setup import setup_message
    o, _ = env
    o.run([setup_message(CFG, 1)])
    cfg2 = {**CFG, "extras": {}}  # Prizes removed in the form
    o.run([setup_message(cfg2, 2)])
    assert "prizes" not in o.sm.load()["plans"][-1]["budget"]
