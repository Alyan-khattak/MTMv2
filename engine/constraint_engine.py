"""Validates a complete proposed plan against the hard constraints. Pure Python."""
from planners.budget_planner import headcount

SECTIONS = ("venue", "food", "judging", "schedule", "budget")


def _v(area, message, *facts):
    return {"area": area, "message": message, "fact_ids": [f["id"] for f in facts if f]}


def validate(sections, facts):
    """Returns a list of violations ({area, message, fact_ids}); empty means VALID."""
    out = []
    for s in SECTIONS:
        sec = sections.get(s)
        if not sec or sec.get("unresolved"):
            out.append(_v(s, f"{s}: unresolved ({(sec or {}).get('reason', 'not planned')})"))
    if out:
        return out
    venue, food, judging, sched, budget = (sections[s] for s in SECTIONS)
    need = facts.get("event.student_count", default=0) + facts.get("event.staff_count", default=0)
    if budget["total"] > budget["limit"]:
        out.append(_v("budget", f"budget: total {budget['total']} > limit {budget['limit']}",
                      facts.find("event.budget_limit")))
    if venue["capacity"] < need:
        out.append(_v("venue", f"venue.capacity: {venue['capacity']} < {need}"))
    if judging["max_load"] > judging["max_teams_per_judge"]:
        out.append(_v("judging", f"judging.coverage: {judging['teams']} teams need {judging['min_judges_needed']} judges, "
                      f"have {judging['judge_count']}", facts.find("judging.judge_count")))
    if not any(b["label"] == "Prayer break" and b.get("duration_min", 0) >= sched["prayer_break_min"] for b in sched["blocks"]):
        out.append(_v("schedule", "schedule.prayer_break: missing"))
    hc = headcount(facts)
    if food["headcount"] != hc:
        out.append(_v("food", f"food.quantity: {food['headcount']} != {hc}"))
    return out
