"""Headcount = students + staff + judges. Rejects conflicting box counts. LLM only if 2+ packages fit."""
from planners.budget_planner import fixed_costs, headcount, honorarium_total, unresolved

SYSTEM = """You choose one food package for an event. Reply with JSON only:
{"selected": "<package name exactly as given>", "reasons": "<short>", "trade_offs": "<short>"}
All options already fit the budget. Pick the best value for attendees without risking the budget."""


def plan(facts, ctx, sections):
    n = headcount(facts)
    if n is None:
        return unresolved("student, staff or judge count unknown"), []
    box = facts.find("food.box_count")
    if box and box["value"] != n:  # headcount is computed, never taken from a message
        return None, [{"area": "food", "message": f"food.quantity: {box['value']} < {n}" if box["value"] < n
                       else f"food.quantity: {box['value']} != {n}", "fact_ids": [box["id"]]}]
    pkgs = [{"name": k, "price_per_person": v, "total": v * n} for k, v in facts.subjects("food.price_per_person").items()]
    limit, hon = facts.get("event.budget_limit"), honorarium_total(facts)
    if limit is not None and hon is not None:  # leave room for the cheapest venue that seats everyone
        seats = facts.get("event.student_count", default=0) + facts.get("event.staff_count", default=0)
        caps, prices = facts.subjects("venue.capacity"), facts.subjects("venue.price")
        venue_min = min((prices[v] for v in caps if v in prices and caps[v] >= seats), default=0)
        room = limit - hon - sum(fixed_costs(facts).values()) - venue_min
        pkgs = [p for p in pkgs if p["total"] <= room]
    if not pkgs:
        return unresolved("no food package fits the budget"), []
    if len(pkgs) == 1:
        pick, how, out = pkgs[0], "deterministic", {}
    else:
        out = ctx.call("food", SYSTEM, f"Headcount: {n}\nOptions: {pkgs}")
        pick = next((p for p in pkgs if isinstance(out, dict) and p["name"] == out.get("selected")), None)
        if not pick:
            return unresolved("food selection unavailable" + (" (budget exhausted)" if ctx.exhausted else "")), []
        how = "llm"
    return {"package": pick["name"], "price_per_person": pick["price_per_person"], "headcount": n,
            "total_cost": pick["total"], "selection_method": how,
            "reasons": out.get("reasons"), "trade_offs": out.get("trade_offs")}, []
