"""Timetable from accepted facts. Times are minutes from event start unless a start hour is stated.

shortcut: one canonical arrangement (break mid-build, judging last), so there are never 2+ valid
schedules to rank and no LLM call is made; upgrade if real alternatives (e.g. fixed meal times) appear.
"""
from planners.budget_planner import unresolved

DEFAULT_LUNCH_MIN = 30  # assumed when no message gives a lunch break; dropped if the event is too short for it


def _clock(m, start):
    m += int(start * 60) if start is not None else 0
    return f"{m // 60 % 24}:{m % 60:02d}"


def plan(facts, ctx, sections):
    hours, prayer = facts.get("event.duration_hours"), facts.get("event.prayer_break_minutes")
    j = sections.get("judging", {"unresolved": True})
    if hours is None or prayer is None or j.get("unresolved", False):
        return unresolved("duration, prayer break or judging workload unknown"), []
    start = facts.get("event.start_hour")
    lunch = facts.get("event.lunch_break_minutes")
    assumed = lunch is None
    lunch = DEFAULT_LUNCH_MIN if assumed else lunch
    total, judging = int(hours * 60), j["workload_minutes"]
    build = total - judging
    if assumed and build < prayer + lunch:
        lunch = 0  # no room for an assumed lunch: never invent a break the event cannot fit
    work = build - prayer - lunch
    if work < 0:
        return unresolved("event too short for build, breaks and judging"), []
    seg = work // (3 if lunch else 2)
    blocks = [{"minute": 0, "label": "Build starts"},
              {"minute": seg, "label": "Prayer break", "duration_min": prayer}]
    if lunch:
        blocks.append({"minute": 2 * seg + prayer, "label": "Lunch", "duration_min": lunch})
    blocks += [{"minute": build, "label": "Code freeze, judge visits begin", "duration_min": judging},
               {"minute": total, "label": "Event ends"}]
    for b in blocks:
        b["time"] = _clock(b["minute"], start)
    notes = []
    if assumed and lunch:
        notes.append(f"Lunch break of {lunch} min assumed (no message states one)")
    if start is None:
        notes.append("No start time given: times are hours:minutes from event start")
    return {"duration_min": total, "start_hour": start, "blocks": blocks, "prayer_break_min": prayer,
            "lunch_min": lunch, "judging_window_min": judging, "selection_method": "deterministic",
            "reasons": "; ".join(notes) or None}, []
