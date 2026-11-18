"""Filter by capacity, rules and budget headroom, then pick by rule (generator first, then cheapest). No LLM."""
from planners.budget_planner import fixed_costs, headcount, honorarium_total, unresolved


def min_food_cost(facts, hc):
    prices = facts.subjects("food.price_per_person")
    cap = facts.get("food.max_price_per_person")
    if cap is not None:
        prices = {k: v for k, v in prices.items() if v <= cap}
    return min(prices.values()) * hc if prices and hc else 0


def plan(facts, ctx, sections):
    students, staff = facts.get("event.student_count"), facts.get("event.staff_count")
    if students is None or staff is None:
        return unresolved("student or staff count unknown"), []
    required = max(students + staff + facts.get("event.guest_count", default=0), facts.get("venue.min_capacity", default=0))
    caps, prices, gens = (facts.subjects(k) for k in ("venue.capacity", "venue.price", "venue.generator"))
    venues = [{"name": n, "capacity": caps[n], "price": prices[n], "generator": bool(gens.get(n, False))}
              for n in caps if n in prices]
    ok = [v for v in venues if v["capacity"] >= required]
    max_price = facts.get("venue.max_price")
    if max_price is not None:
        ok = [v for v in ok if v["price"] <= max_price]
    if facts.get("venue.requires_generator"):
        ok = [v for v in ok if v["generator"]]
    limit, hon = facts.get("event.budget_limit"), honorarium_total(facts)
    if limit is not None and hon is not None:  # price must leave room for the cheapest food + known fixed costs
        room = limit - hon - sum(fixed_costs(facts).values()) - min_food_cost(facts, headcount(facts))
        ok = [v for v in ok if v["price"] <= room]
    if not ok:
        return unresolved(f"no venue seats {required} within the rules and budget"), []
    ok.sort(key=lambda v: (not v["generator"], v["price"]))
    pick = ok[0]
    why = ("Has a standby generator and is the cheapest such option" if pick["generator"]
           else "Cheapest option") + f" among {len(ok)} venue(s) that seat {required} within budget"
    return {**pick, "selection_method": "deterministic", "alternatives": [v["name"] for v in ok[1:]],
            "reasons": why, "trade_offs": None}, []
