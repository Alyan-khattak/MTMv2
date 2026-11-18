"""Pure arithmetic. No LLM. Also hosts the shared cost/headcount helpers."""
import math

RESERVED = {"venue", "food", "judging_honorarium", "total", "limit", "remaining", "within_budget", "selection_method"}


def headcount(facts):
    """students + staff + judges + extra guests, always computed from accepted facts. None if a required one is unknown."""
    parts = [facts.get("event.student_count"), facts.get("event.staff_count"), facts.get("judging.judge_count")]
    return None if any(p is None for p in parts) else sum(parts) + facts.get("event.guest_count", default=0)


def teams(facts):
    s, t = facts.get("event.student_count"), facts.get("event.team_size")
    return math.ceil(s / t) if s and t else None


def fixed_costs(facts):
    """Every accepted `budget.<item>` fact is a cost, so a cost kind never seen before is still counted."""
    out = {}
    for f in facts.items:
        k, v = f["key"], f["value"]
        if not k.startswith("budget.") or isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        name = k[len("budget."):].removesuffix("_cost")
        if f.get("subject"):
            name += "_" + f["subject"].lower().replace(" ", "_")
        out["extra_" + name if name in RESERVED else name] = v
    return out


def honorarium_total(facts):
    n, h = facts.get("judging.judge_count"), facts.get("judging.honorarium")
    return None if n is None or h is None else n * h


def unresolved(reason):
    return {"unresolved": True, "reason": reason}


def plan(facts, ctx, sections):
    limit = facts.get("event.budget_limit")
    if limit is None:
        return unresolved("budget limit unknown"), []
    bad = [k for k in ("venue", "food", "judging") if sections.get(k, {"unresolved": True}).get("unresolved", False)]
    if bad:
        return unresolved("depends on unresolved: " + ", ".join(bad)), []
    items = {"venue": sections["venue"]["price"], "food": sections["food"]["total_cost"],
             "judging_honorarium": sections["judging"]["total_honorarium"], **fixed_costs(facts)}
    total = sum(items.values())
    return {**items, "total": total, "limit": limit, "remaining": limit - total, "within_budget": total <= limit,
            "selection_method": "deterministic"}, []
