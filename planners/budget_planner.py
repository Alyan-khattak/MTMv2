"""Pure arithmetic. No LLM. Also hosts the shared cost/headcount helpers."""
import math

FIXED_KEYS = {"prizes": "budget.prizes", "backup_internet": "budget.backup_internet",
              "printing": "budget.printing_cost", "dj": "budget.dj"}


def headcount(facts):
    """students + staff + judges, always computed from accepted facts. None if any is unknown."""
    parts = [facts.get("event.student_count"), facts.get("event.staff_count"), facts.get("judging.judge_count")]
    return None if any(p is None for p in parts) else sum(parts)


def teams(facts):
    s, t = facts.get("event.student_count"), facts.get("event.team_size")
    return math.ceil(s / t) if s and t else None


def fixed_costs(facts):
    return {name: facts.get(key, default=0) for name, key in FIXED_KEYS.items()}


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
