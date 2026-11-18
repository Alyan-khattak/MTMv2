"""Filter by capacity and budget headroom; LLM only if 2+ options remain."""
from planners.budget_planner import fixed_costs, honorarium_total, unresolved

SYSTEM = """You choose one event venue. Reply with JSON only:
{"selected": "<venue name exactly as given>", "ranked_alternatives": ["<names, best first>"], "reasons": "<short>", "trade_offs": "<short>"}
All options already satisfy capacity and budget. Soft preference: a standby generator is desirable; weigh it against cost."""


def min_food_cost(facts, headcount):
    prices = facts.subjects("food.price_per_person")
    return min(prices.values()) * headcount if prices and headcount else 0


def plan(facts, ctx, sections):
    from planners.budget_planner import headcount
    students, staff = facts.get("event.student_count"), facts.get("event.staff_count")
    if students is None or staff is None:
        return unresolved("student or staff count unknown"), []
    required = students + staff
    caps, prices, gens = (facts.subjects(k) for k in ("venue.capacity", "venue.price", "venue.generator"))
    venues = [{"name": n, "capacity": caps[n], "price": prices[n], "generator": bool(gens.get(n, False))}
              for n in caps if n in prices]
    ok = [v for v in venues if v["capacity"] >= required]
    limit, hon = facts.get("event.budget_limit"), honorarium_total(facts)
    if limit is not None and hon is not None:  # price must leave room for the cheapest food + known fixed costs
        room = limit - hon - sum(fixed_costs(facts).values()) - min_food_cost(facts, headcount(facts))
        ok = [v for v in ok if v["price"] <= room]
    if not ok:
        return unresolved(f"no venue seats {required} within budget"), []
    if len(ok) == 1:
        return {**ok[0], "selection_method": "deterministic", "alternatives": []}, []
    out = ctx.call("venue", SYSTEM, f"Required seats: {required}\nOptions: {ok}")
    pick = next((v for v in ok if isinstance(out, dict) and v["name"] == out.get("selected")), None)
    if not pick:
        return unresolved("venue selection unavailable" + (" (budget exhausted)" if ctx.exhausted else "")), []
    return {**pick, "selection_method": "llm", "alternatives": out.get("ranked_alternatives", []),
            "reasons": out.get("reasons"), "trade_offs": out.get("trade_offs")}, []
