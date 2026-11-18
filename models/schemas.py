"""Data shapes. State stores plain dicts (asdict of these); Facts is a read view over accepted facts."""
import os
from dataclasses import dataclass, field
from typing import Any, Optional

DEFAULT_MODEL = "llama-3.3-70b-versatile"


def model_name():
    # GROQ_MODEL override exists because the documented model is not served to every key
    return os.getenv("GROQ_MODEL", DEFAULT_MODEL)


AREAS = ("reading", "venue", "food", "judging", "schedule", "budget")
PLANNERS = ("venue", "food", "judging", "schedule", "budget")  # execution order


@dataclass
class Message:
    id: str
    hash: str
    source: str
    channel: str
    date: str
    text: str
    status: str = "PENDING"  # ACCEPTED / SUPERSEDED / REJECTED / IRRELEVANT / DUPLICATE
    processed_at: Optional[str] = None
    run_id: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class Fact:
    id: str
    key: str
    subject: Optional[str]
    value: Any
    source_message_id: str
    source_name: str
    source_date: str
    authority_rank: int
    approved: bool = True
    status: str = "CANDIDATE"  # CANDIDATE / ACCEPTED / SUPERSEDED / REJECTED
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    rejection_reason: Optional[str] = None
    extracted_at: Optional[str] = None


@dataclass
class TraceEntry:
    run_id: str
    call_number: Optional[int]  # None for unnumbered notes (TIMEOUT / REJECTED)
    area: str
    input: str
    output: str
    status: str  # SUCCESS / BUDGET_EXHAUSTED / TIMEOUT / ERROR / REJECTED
    timestamp: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    note: Optional[str] = None


@dataclass
class Plan:
    id: str
    created_at: str
    run_id: str
    status: str  # COMMITTED / REJECTED / INCOMPLETE
    fact_snapshot: list = field(default_factory=list)
    venue: Optional[dict] = None
    food: Optional[dict] = None
    judging: Optional[dict] = None
    schedule: Optional[dict] = None
    budget: Optional[dict] = None
    constraint_result: Optional[dict] = None
    rejection_reason: Optional[str] = None


@dataclass
class RunResult:
    id: str
    type: str
    started_at: str
    ended_at: str
    duration_seconds: float
    messages_processed: int
    planners_run: list
    model_calls: int
    total_tokens: int
    outcome: str
    plan_id: Optional[str]
    unresolved_dependencies: list = field(default_factory=list)
    rejected_message_ids: list = field(default_factory=list)


class Facts:
    """Read view over ACCEPTED facts, keyed by (key, subject)."""

    def __init__(self, facts):
        self.items = [f for f in facts if f["status"] == "ACCEPTED"]

    def find(self, key, subject=None):
        return next((f for f in self.items if f["key"] == key and f.get("subject") == subject), None)

    def get(self, key, subject=None, default=None):
        f = self.find(key, subject)
        return f["value"] if f else default

    def subjects(self, key):
        return {f["subject"]: f["value"] for f in self.items if f["key"] == key}

    def ids(self):
        return [f["id"] for f in self.items]
