"""Changed fact keys -> ordered list of planners to re-run. Pure Python."""
from models.schemas import PLANNERS

DEPENDENCY_MAP = {
    "event.student_count": ["venue", "food", "judging", "schedule", "budget"],
    "event.team_size": ["judging", "schedule", "budget"],
    "event.staff_count": ["venue", "food", "budget"],
    "event.duration_hours": ["judging", "schedule"],
    "event.budget_limit": ["venue", "food", "budget"],
    "event.prayer_break_minutes": ["schedule"],
    "venue.capacity": ["venue", "budget"],
    "venue.price": ["venue", "budget"],
    "venue.generator": ["venue", "budget"],
    "food.price_per_person": ["food", "budget"],
    "food.box_count": ["food"],
    "judging.judge_count": ["food", "judging", "schedule", "budget"],  # judges are part of food headcount
    "judging.honorarium": ["judging", "budget"],
    "judging.minutes_per_team": ["judging", "schedule"],
    "judging.max_teams_per_judge": ["judging", "schedule"],
    "budget.prizes": ["budget"],
    "budget.backup_internet": ["budget"],
    "budget.printing_cost": ["budget"],
    "budget.dj": ["budget"],
}


def resolve(changed_keys, full=False):
    """Returns (ordered planner names, keys missing from DEPENDENCY_MAP). Unknown keys are reported, never dropped silently."""
    if full:
        return list(PLANNERS), []
    need, unresolved = set(), []
    for k in sorted(set(changed_keys)):
        if k in DEPENDENCY_MAP:
            need.update(DEPENDENCY_MAP[k])
        else:
            unresolved.append(k)
    return [p for p in PLANNERS if p in need], unresolved
