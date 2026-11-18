"""Timetable from accepted facts. Times are minutes from event start (no start time is given in any message).

shortcut: one canonical arrangement (break mid-build, judging last), so there are never 2+ valid
schedules to rank and no LLM call is made; upgrade if real alternatives (e.g. fixed start time) appear.
"""
from planners.budget_planner import unresolved


def _clock(m):
    return f"{m // 60}:{m % 60:02d}"


def plan(facts, ctx, sections):
    hours, prayer = facts.get("event.duration_hours"), facts.get("event.prayer_break_minutes")
    j = sections.get("judging", {"unresolved": True})
    if hours is None or prayer is None or j.get("unresolved", False):
        return unresolved("duration, prayer break or judging workload unknown"), []
    total, judging = int(hours * 60), j["workload_minutes"]
    build = total - judging
    if build < prayer:
        return unresolved("event too short for build, prayer break and judging"), []
    brk = (build - prayer) // 2
    blocks = [{"minute": 0, "time": _clock(0), "label": "Build starts"},
              {"minute": brk, "time": _clock(brk), "label": "Prayer break", "duration_min": prayer},
              {"minute": build, "time": _clock(build), "label": "Code freeze, judge visits begin"},
              {"minute": total, "time": _clock(total), "label": "Event ends"}]
    return {"duration_min": total, "blocks": blocks, "prayer_break_min": prayer, "judging_window_min": judging,
            "selection_method": "deterministic"}, []
