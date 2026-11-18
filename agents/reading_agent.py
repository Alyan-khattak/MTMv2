"""Groq client wrapper (TASK-006) and the LLM fact extractor (area: reading)."""
import os

from models.schemas import model_name


class MissingApiKey(RuntimeError):
    pass


class GroqClient:
    def __init__(self):
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise MissingApiKey("GROQ_API_KEY not set. Check .env file.")
        from groq import Groq
        self.model = model_name()
        self._c = Groq(api_key=key)

    def chat(self, system, user, timeout):
        """Returns (text, usage). Usage is the API's own object: prompt/completion/total_tokens."""
        extra = {"extra_body": {"reasoning_effort": "low"}} if self.model.startswith("openai/gpt-oss") else {}
        r = self._c.chat.completions.create(
            model=self.model, temperature=0, timeout=timeout, **extra,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return r.choices[0].message.content, r.usage


# Vocabulary of fact keys (structure, not event values).
SYSTEM = """You extract event-planning facts from ONE message (English or Roman Urdu).
Reply with JSON only: {"facts":[{"key":str,"subject":str|null,"value":number|boolean,"approved":boolean}]}
Allowed keys:
event.student_count, event.team_size (students per team), event.staff_count, event.duration_hours, event.budget_limit (total, rupees), event.prayer_break_minutes,
venue.capacity, venue.price, venue.generator (true/false) - subject = venue name; emit all three for every venue named,
food.price_per_person - subject = package name (e.g. standard, basic); food.box_count (number of food boxes/meals ordered),
judging.judge_count, judging.honorarium (per judge), judging.minutes_per_team, judging.max_teams_per_judge,
budget.prizes, budget.backup_internet, budget.printing_cost, budget.dj (rupee amounts already spent/ordered or quoted).
Rules: write numbers as digits in rupees/minutes/hours. approved=false when the message only asks or proposes (a question, a quote awaiting a decision); true when it states a decision, order, price list or confirmation. Use subject=null when not applicable. If the message has no planning facts, return {"facts":[]}."""


def _num(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        try:
            v = float(v.replace(",", ""))
        except ValueError:
            return None
    if isinstance(v, (int, float)):
        return int(v) if float(v).is_integer() else v
    return None


def read_message(ctx, msg):
    """Returns list of {key, subject, value, approved}, or None if the model call failed."""
    user = f"Source: {msg['source']}\nChannel: {msg['channel']}\nDate: {msg['date']}\nMessage: {msg['text']}"
    out = ctx.call("reading", SYSTEM, user)
    if not isinstance(out, dict) or not isinstance(out.get("facts"), list):
        return None
    facts = []
    for f in out["facts"]:
        if not isinstance(f, dict) or not isinstance(f.get("key"), str):
            continue
        value = _num(f.get("value"))
        if value is None:
            continue
        subject = f.get("subject")
        subject = subject.strip().title() if isinstance(subject, str) and subject.strip() else None
        facts.append({"key": f["key"].strip(), "subject": subject, "value": value,
                      "approved": f.get("approved") is not False})
    return facts
