"""Deterministic judge-to-team allocation and honorarium. No LLM."""
import math

from planners.budget_planner import teams as team_count, unresolved


def plan(facts, ctx, sections):
    judges, per_team = facts.get("judging.judge_count"), facts.get("judging.minutes_per_team")
    cap, honor, teams = facts.get("judging.max_teams_per_judge"), facts.get("judging.honorarium"), team_count(facts)
    if None in (judges, per_team, cap, honor, teams) or judges <= 0:
        return unresolved("judge count, rates, limits or team count unknown"), []
    base, extra = divmod(teams, judges)
    alloc, start = [], 1
    for j in range(judges):  # contiguous team ranges, first `extra` judges take one more
        n = base + (1 if j < extra else 0)
        alloc.append({"judge": j + 1, "teams": [start, start + n - 1] if n else []})
        start += n
    max_load = base + (1 if extra else 0)
    return {"judge_count": judges, "teams": teams, "max_teams_per_judge": cap, "minutes_per_team": per_team,
            "min_judges_needed": math.ceil(teams / cap), "max_load": max_load,
            "workload_minutes": max_load * per_team, "honorarium_per_judge": honor,
            "total_honorarium": judges * honor, "allocation": alloc, "selection_method": "deterministic"}, []
