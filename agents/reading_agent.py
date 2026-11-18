"""Groq client wrapper and the LLM fact extractor (area: reading). One call reads the whole pack."""
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
SYSTEM = """You extract event-planning facts from several numbered messages (English or Roman Urdu).
Reply with JSON only: {"messages":[{"n":int,"facts":[{"key":str,"subject":str|null,"value":number|boolean,"approved":boolean}]}]}
Give one entry per message number; use "facts":[] when a message has no planning facts.
Allowed keys:
event.student_count, event.team_size (students per team), event.staff_count, event.guest_count (extra people to seat and feed besides students, staff and judges), event.duration_hours, event.start_hour (24h clock hour the event starts), event.budget_limit (total, rupees), event.prayer_break_minutes, event.lunch_break_minutes,
venue.capacity, venue.price, venue.generator (true/false) - subject = venue name; emit all three for every venue named,
venue.max_price, venue.min_capacity, venue.requires_generator (true if a generator is mandatory), venue.closing_hour (24h hour the venue must be empty),
food.price_per_person - subject = package name (e.g. standard, basic); food.max_price_per_person (a cap on any package); food.box_count (number of food boxes/meals ordered),
judging.judge_count, judging.min_judges, judging.honorarium (per judge), judging.minutes_per_team, judging.max_teams_per_judge,
budget.<item> for ANY other rupee cost already spent, ordered or quoted - use a short snake_case item name, e.g. budget.prizes, budget.backup_internet, budget.printing_cost, budget.dj, budget.security,
note.<short_snake_name> for any other rule or constraint that none of the keys above can express: value true, subject = one plain sentence describing it.
Rules: write numbers as digits in rupees/minutes/hours. approved=false when the message only asks or proposes (a question, a quote awaiting a decision); true when it states a decision, order, price list or confirmation. Use subject=null when not applicable. Facts must come only from the message they are listed under."""


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


def _clean(raw):
    facts = []
    for f in raw if isinstance(raw, list) else []:
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


def read_messages(ctx, msgs):
    """Returns {1-based message position: [{key, subject, value, approved}]} for every message the model answered.
    Empty dict if the call failed. One retry: a bad reply must not lose the whole pack."""
    user = "\n\n".join(f"[{i}] Source: {m['source']}\nChannel: {m['channel']}\nDate: {m['date']}\nMessage: {m['text']}"
                       for i, m in enumerate(msgs, 1))
    for _ in range(2):
        out = ctx.call("reading", SYSTEM, user)
        if isinstance(out, dict) and isinstance(out.get("messages"), list):
            break
        if ctx.exhausted or ctx.timed_out:
            return {}
    else:
        return {}
    res = {}
    for e in out["messages"]:
        try:
            n = int(e["n"])
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(e, dict) and 1 <= n <= len(msgs):
            res[n] = _clean(e.get("facts"))
    return res
