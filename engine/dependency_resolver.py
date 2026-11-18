"""Changed fact keys -> ordered list of planners to re-run. Pure Python."""
from models.schemas import PLANNERS

ALL = list(PLANNERS)
# Venue and food prices share one budget, so anything that changes the money room re-checks venue and food too.
MONEY = ["venue", "food", "budget"]
DEPENDENCY_MAP = {
    "event.student_count": ALL,
    "event.guest_count": MONEY,
    "event.team_size": ["judging", "schedule", "budget"],
    "event.staff_count": MONEY,
    "event.duration_hours": ["judging", "schedule"],
    "event.start_hour": ["schedule"],
    "event.budget_limit": MONEY,
    "event.prayer_break_minutes": ["schedule"],
    "event.lunch_break_minutes": ["schedule"],
    "venue.capacity": MONEY,
    "venue.price": MONEY,
    "venue.generator": MONEY,
    "venue.max_price": MONEY,
    "venue.min_capacity": MONEY,
    "venue.requires_generator": MONEY,
    "venue.closing_hour": ["schedule"],
    "food.price_per_person": MONEY,
    "food.max_price_per_person": MONEY,
    "food.box_count": ["food"],
    "judging.judge_count": ALL,  # judges are part of food headcount and the money room
    "judging.honorarium": ["venue", "food", "judging", "budget"],
    "judging.min_judges": ["judging"],
    "judging.minutes_per_team": ["judging", "schedule"],
    "judging.max_teams_per_judge": ["judging", "schedule"],
}


def resolve(changed_keys, full=False):
    """Returns (ordered planner names, keys not in DEPENDENCY_MAP).
    Unknown keys are never dropped: `budget.*` costs re-run the money planners, `note.*` rebuilds the budget
    snapshot, and any other unknown key re-runs everything (planners are free; only reading calls the model)."""
    if full:
        return list(PLANNERS), []
    need, unknown = set(), []
    for k in sorted(set(changed_keys)):
        if k in DEPENDENCY_MAP:
            need.update(DEPENDENCY_MAP[k])
        elif k.startswith("budget."):
            need.update(MONEY)
        elif k.startswith("note."):
            need.add("budget")
        else:
            need.update(PLANNERS)
            unknown.append(k)
    return [p for p in PLANNERS if p in need], unknown
