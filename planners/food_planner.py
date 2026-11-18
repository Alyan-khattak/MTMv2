"""Headcount = students + staff + judges + guests. Rejects conflicting box counts. Pure code, no LLM."""
from planners.budget_planner import fixed_costs, headcount, honorarium_total, unresolved


def plan(facts, ctx, sections):
    n = headcount(facts)
    if n is None:
        return unresolved("student, staff or judge count unknown"), []
    box = facts.find("food.box_count")
    if box and box["value"] != n:  # headcount is computed, never taken from a message
        return None, [{"area": "food", "message": f"food.quantity: {box['value']} < {n}" if box["value"] < n
                       else f"food.quantity: {box['value']} != {n}", "fact_ids": [box["id"]]}]
    pkgs = [{"name": k, "price_per_person": v, "total": v * n} for k, v in facts.subjects("food.price_per_person").items()]
    cap = facts.get("food.max_price_per_person")
    if cap is not None:
        pkgs = [p for p in pkgs if p["price_per_person"] <= cap]
    limit, hon = facts.get("event.budget_limit"), honorarium_total(facts)
    if limit is not None and hon is not None:
        venue = sections.get("venue")
        if venue and not venue.get("unresolved"):  # the venue actually chosen, not the cheapest possible one
            venue_cost = venue["price"]
        else:
            seats = (facts.get("event.student_count", default=0) + facts.get("event.staff_count", default=0)
                     + facts.get("event.guest_count", default=0))
            caps, prices = facts.subjects("venue.capacity"), facts.subjects("venue.price")
            venue_cost = min((prices[v] for v in caps if v in prices and caps[v] >= seats), default=0)
        room = limit - hon - sum(fixed_costs(facts).values()) - venue_cost
        pkgs = [p for p in pkgs if p["total"] <= room]
    if not pkgs:
        return unresolved("no food package fits the budget"), []
    pick = max(pkgs, key=lambda p: p["price_per_person"])  # best package the budget still allows
    return {"package": pick["name"], "price_per_person": pick["price_per_person"], "headcount": n,
            "total_cost": pick["total"], "selection_method": "deterministic",
            "reasons": f"Highest-priced package that still fits the budget ({len(pkgs)} option(s) fit)",
            "trade_offs": None, "alternatives": [p["name"] for p in pkgs if p is not pick]}, []
