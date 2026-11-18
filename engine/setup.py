"""Hackathon setup: saved config -> facts (no model call), and free text -> config (one model call)."""
import json
from datetime import date

SETUP_SOURCE = "Setup form"


def config_to_facts(c):
    """Turns the setup form into the same raw facts the reading agent produces. Empty/missing fields are skipped."""
    f = []
    add = lambda k, v, s=None: v not in (None, "") and f.append({"key": k, "subject": s, "value": v, "approved": True})
    for key, field in (("event.student_count", "students"), ("event.team_size", "team_size"), ("event.staff_count", "staff"),
                       ("event.guest_count", "guests"), ("event.duration_hours", "duration_hours"),
                       ("event.start_hour", "start_hour"), ("event.budget_limit", "budget"),
                       ("event.prayer_break_minutes", "prayer_minutes"), ("event.lunch_break_minutes", "lunch_minutes")):
        add(key, c.get(field))
    for v in c.get("venues", []):
        n = (v.get("name") or "").strip().title()
        if n:
            add("venue.capacity", v.get("capacity"), n); add("venue.price", v.get("price"), n)
            add("venue.generator", bool(v.get("generator")), n)
    for p in c.get("food", []):
        add("food.price_per_person", p.get("price"), (p.get("name") or "").strip().title() or None)
    j = c.get("judging", {})
    for key, field in (("judging.judge_count", "count"), ("judging.honorarium", "honorarium"),
                       ("judging.minutes_per_team", "minutes_per_team"), ("judging.max_teams_per_judge", "max_teams_per_judge"),
                       ("judging.min_judges", "min_judges")):
        add(key, j.get(field))
    for item, cost in (c.get("extras") or {}).items():
        add("budget." + item.strip().lower().replace(" ", "_"), cost)
    r = c.get("rules", {})
    add("venue.max_price", r.get("max_venue_price")); add("food.max_price_per_person", r.get("max_food_price"))
    add("venue.closing_hour", r.get("closing_hour"))
    if r.get("requires_generator"):
        add("venue.requires_generator", True)
    for i, note in enumerate(c.get("notes", []), 1):
        add(f"note.setup_{i}", True, note)
    return f


def setup_message(cfg, n):
    """A message the orchestrator takes as-is; its facts skip the reading call."""
    return {"id": f"SETUP_{n:03d}", "source": SETUP_SOURCE, "channel": "web", "date": date.today().isoformat(),
            "text": json.dumps(cfg, sort_keys=True), "facts": config_to_facts(cfg)}


TEXT_SYSTEM = """Turn a hackathon description into a setup form. Reply with JSON only, omit anything not stated:
{"name":str,"students":int,"team_size":int,"staff":int,"guests":int,"duration_hours":number,"start_hour":number (24h),
"budget":int (rupees),"prayer_minutes":int,"lunch_minutes":int,
"venues":[{"name":str,"capacity":int,"price":int,"generator":bool}],"food":[{"name":str,"price":int (per person)}],
"judging":{"count":int,"honorarium":int,"minutes_per_team":int,"max_teams_per_judge":int,"min_judges":int},
"extras":{"<item>":rupees},"rules":{"max_venue_price":int,"max_food_price":int,"closing_hour":int,"requires_generator":bool},
"notes":[str]}  (notes = any rule none of the fields can express). Numbers as digits."""


def text_to_config(text, client_factory):
    out, _ = client_factory().chat(TEXT_SYSTEM, text, timeout=30)
    cfg = json.loads(out)
    if not isinstance(cfg, dict):
        raise ValueError("The model did not return a setup")
    return cfg
