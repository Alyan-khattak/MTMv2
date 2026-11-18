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
    need = (facts.get("event.student_count", default=0) + facts.get("event.staff_count", default=0)
            + facts.get("event.guest_count", default=0))
    if budget["total"] > budget["limit"]:
        out.append(_v("budget", f"budget: total {budget['total']} > limit {budget['limit']}",
                      facts.find("event.budget_limit")))
    if venue["capacity"] < need:
        out.append(_v("venue", f"venue.capacity: {venue['capacity']} < {need}"))
    mincap = facts.find("venue.min_capacity")
    if mincap and venue["capacity"] < mincap["value"]:
        out.append(_v("venue", f"venue.min_capacity: {venue['capacity']} < {mincap['value']}", mincap))
    maxp = facts.find("venue.max_price")
    if maxp and venue["price"] > maxp["value"]:
        out.append(_v("venue", f"venue.max_price: {venue['price']} > {maxp['value']}", maxp))
    gen = facts.find("venue.requires_generator")
    if gen and gen["value"] and not venue["generator"]:
        out.append(_v("venue", "venue.generator: required but missing", gen))
    fmax = facts.find("food.max_price_per_person")
    if fmax and food["price_per_person"] > fmax["value"]:
        out.append(_v("food", f"food.max_price_per_person: {food['price_per_person']} > {fmax['value']}", fmax))
    if judging["max_load"] > judging["max_teams_per_judge"]:
        out.append(_v("judging", f"judging.coverage: {judging['teams']} teams need {judging['min_judges_needed']} judges, "
                      f"have {judging['judge_count']}", facts.find("judging.judge_count")))
    minj = facts.find("judging.min_judges")
    if minj and judging["judge_count"] < minj["value"]:
        out.append(_v("judging", f"judging.min_judges: {judging['judge_count']} < {minj['value']}", minj,
                      facts.find("judging.judge_count")))
    if not any(b["label"] == "Prayer break" and b.get("duration_min", 0) >= sched["prayer_break_min"] for b in sched["blocks"]):
        out.append(_v("schedule", "schedule.prayer_break: missing"))
    minutes = [b["minute"] for b in sched["blocks"]]
    if minutes != sorted(minutes) or minutes[-1] != sched["duration_min"]:
        out.append(_v("schedule", "schedule.order: blocks overlap or overrun the event"))
    closing, start = facts.find("venue.closing_hour"), sched.get("start_hour")
    if closing and start is not None and start + sched["duration_min"] / 60 > closing["value"]:
        out.append(_v("schedule", f"venue.closing_hour: event ends after {closing['value']}:00", closing,
                      facts.find("event.start_hour")))
    hc = headcount(facts)
    if food["headcount"] != hc:
        out.append(_v("food", f"food.quantity: {food['headcount']} != {hc}"))
    return out
