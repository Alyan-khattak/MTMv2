"""Single entry point for CLI and API: ingest messages -> read -> decide -> resolve -> plan -> validate -> commit."""
import copy
import hashlib
import json
import os
import re
import time
from dataclasses import asdict
from datetime import datetime

from agents.reading_agent import GroqClient, read_messages
from engine import constraint_engine, dependency_resolver
from engine.decision_engine import decide, derive_message_statuses, next_id
from engine.dependency_resolver import DEPENDENCY_MAP
from models.schemas import PLANNERS, Facts, Plan, RunResult, TraceEntry, model_name
from planners import budget_planner, food_planner, judging_planner, schedule_planner, venue_planner
from state.state_manager import StateManager

PLANNER_FUNCS = {"venue": venue_planner.plan, "food": food_planner.plan, "judging": judging_planner.plan,
                 "schedule": schedule_planner.plan, "budget": budget_planner.plan}
NEW_PACK_MIN = 4  # this many unseen messages at once = a fresh pack, not a live update


def now():
    return datetime.now().isoformat(timespec="seconds")


MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
CHANNELS = {"email", "whatsapp", "notice", "sms", "chat", "telegram", "call", "phone", "web", "slack", "memo", "letter",
            "poster", "announcement", "text", "message", "voicenote", "group"}
KV = {"from": "source", "source": "source", "sender": "source", "date": "date", "channel": "channel", "id": "id",
      "message": "text", "text": "text", "body": "text"}


def parse_date(s):
    """'2026-11-09', '9 Nov', '9 Nov 2026', 'Nov 9', '09/11/2026' -> ISO date, else None."""
    s = s.strip().strip("()[]")
    year = datetime.now().year
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s):
        y, mo, d = m[1], m[2], m[3]
    elif m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", s):
        d, mo, y = m[1], m[2], m[3]
    elif m := re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3})[a-z]*\.?,?(?:\s+(\d{4}))?", s):
        d, mo, y = m[1], MONTHS.get(m[2].lower()), m[3] or year
    elif m := re.fullmatch(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?(?:\s+(\d{4}))?", s):
        mo, d, y = MONTHS.get(m[1].lower()), m[2], m[3] or year
    else:
        return None
    try:
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}" if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31 else None
    except (TypeError, ValueError):
        return None


def _split_source(s):
    """'Dean's office, email' -> ("Dean's office", "email")."""
    head, _, tail = s.rpartition(",")
    if head and tail.strip().lower() in CHANNELS:
        return head.strip(), tail.strip().lower()
    return s.strip(), None


def _header(line):
    """`ID | source[, channel] | [channel |] date [| text]` in any column order -> dict, or None."""
    parts = [p.strip() for p in line.strip().strip("|").split("|")]
    if len(parts) < 3:
        return None
    di = next((i for i, p in enumerate(parts) if parse_date(p)), None)
    if di is None:
        return None
    date, rest = parse_date(parts[di]), [p for i, p in enumerate(parts) if i != di]
    mid = None
    if re.fullmatch(r"#?\w[\w.-]*", rest[0]) and re.search(r"\d", rest[0]):
        mid, rest = rest[0].lstrip("#"), rest[1:]
    if not rest:
        return None
    source, channel = _split_source(rest[0])
    rest = rest[1:]
    if rest and rest[0].lower() in CHANNELS or (len(rest) > 1 and len(rest[0].split()) <= 2):
        channel, rest = rest[0].lower(), rest[1:]
    return {"id": mid, "source": source, "channel": channel or "unknown", "date": date,
            "text": " | ".join(rest).strip(" \"'\u201c\u201d")}


def _blocks_kv(text):
    """Fallback format: blocks of `From: ... / Date: ... / Channel: ... / Message: ...` lines."""
    out = []
    for block in re.split(r"\n\s*\n", text):
        cur = {}
        for line in block.splitlines():
            k, sep, v = line.partition(":")
            if sep and k.strip().lower() in KV:
                cur[KV[k.strip().lower()]] = v.strip()
            elif cur.get("text") is not None and line.strip():
                cur["text"] += " " + line.strip()
        if cur.get("text") and cur.get("source") and parse_date(cur.get("date", "")):
            src, ch = _split_source(cur["source"])
            out.append({"id": cur.get("id"), "source": src, "channel": cur.get("channel") or ch or "unknown",
                        "date": parse_date(cur["date"]), "text": cur["text"]})
    return out


def parse_messages(text):
    """Header lines (`ID | source | channel | date`, flexible) followed by body lines, or `From:/Date:/Message:` blocks.
    Raises ValueError when the text has content but no message could be read, so a format miss is never silent."""
    out = []
    for line in text.splitlines():
        h = _header(line) if "|" in line else None
        if h:
            out.append(h)
        elif out and line.strip() and not re.fullmatch(r"[|\s:-]+", line):
            out[-1]["text"] = (out[-1]["text"] + " " + line.strip()).strip()
    out = [m for m in out if m["text"]] or _blocks_kv(text)
    if text.strip() and not out:
        raise ValueError("Could not read any messages from the file (expected `ID | source | channel | date` headers)")
    used = {m["id"] for m in out if m["id"]}
    for i, m in enumerate(out, 1):
        if not m["id"]:
            m["id"] = next(f"MSG_{n:03d}" for n in range(i, 10_000) if f"MSG_{n:03d}" not in used)
            used.add(m["id"])
    return out


def unenforced(facts):
    """Accepted facts no planner checks (notes and unknown keys), listed so nothing is silently ignored."""
    return [{"key": f["key"], "subject": f.get("subject"), "value": f["value"], "message_id": f["source_message_id"]}
            for f in facts.items if f["key"].startswith("note.")
            or (f["key"] not in DEPENDENCY_MAP and not f["key"].startswith("budget."))]


def msg_hash(source, text):
    return hashlib.sha256(f"{source}\n{text.strip()}".encode()).hexdigest()


class RunContext:
    """Owns the call counter, limits and trace for one run. Every model call goes through call()."""

    def __init__(self, run_id, mode, client_factory):
        self.run_id, self.mode, self._factory, self._client = run_id, mode, client_factory, None
        full = mode == "full"
        self.max_seconds = float(os.getenv("MAX_FULL_RUN_SECONDS" if full else "MAX_INCREMENTAL_SECONDS", 120 if full else 60))
        self.max_calls = None if full else int(os.getenv("MAX_INCREMENTAL_CALLS", 5))
        self.start, self.trace, self.real_calls, self.exhausted, self.timed_out = time.time(), [], 0, False, False

    def remaining(self):
        return self.max_seconds - (time.time() - self.start)

    def _add(self, area, inp, out, status, usage=None, numbered=True):
        n = sum(1 for t in self.trace if t["call_number"]) + 1 if numbered else None
        e = TraceEntry(self.run_id, n, area, inp, out, status, now(), model=model_name(),
                       prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                       completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                       total_tokens=getattr(usage, "total_tokens", 0) or 0)
        self.trace.append(asdict(e))

    def note(self, area, text, status):
        self._add(area, "", text, status, numbered=False)

    def call(self, area, system, user):
        """Returns parsed JSON dict, or None (budget exhausted, timeout, error, bad JSON). Tokens come only from response.usage."""
        inp = f"{system}\n\n{user}"
        if self.remaining() <= 0:
            self.timed_out = True
            self._add(area, "", "TIMEOUT", "TIMEOUT", numbered=False)
            return None
        if self.max_calls is not None and self.real_calls >= self.max_calls:
            self.exhausted = True
            self._add(area, "", "BUDGET_EXHAUSTED", "BUDGET_EXHAUSTED", numbered=False)
            return None
        self.real_calls += 1
        try:
            self._client = self._client or self._factory()
            text, usage = self._client.chat(system, user, timeout=max(1, min(self.remaining(), 60)))
        except Exception as e:  # network/API failure: recorded, run continues unresolved
            self._add(area, inp, f"{type(e).__name__}: {e}", "ERROR")
            return None
        try:
            out = json.loads(text)
        except (TypeError, ValueError):
            self._add(area, inp, text or "", "ERROR", usage)
            return None
        self._add(area, inp, text, "SUCCESS", usage)
        return out if isinstance(out, dict) else None


class Orchestrator:
    def __init__(self, state_manager=None, client_factory=None):
        self.sm = state_manager or StateManager()
        self.client_factory = client_factory or GroqClient  # injectable for tests

    def run(self, incoming):
        """incoming: list of {id, source, channel, date, text}. Returns the run record, or None if nothing to do."""
        state = self.sm.load()
        known = {m["hash"] for m in state["messages"]}
        unseen = {msg_hash(m["source"], m["text"]) for m in incoming} - known
        if state["messages"] and len(unseen) >= NEW_PACK_MIN:  # a whole new pack, not a live update: start clean
            self.sm.archive()
            state = self.sm.load()
        incremental = state["active_plan_id"] is not None
        new, dups = self._intake(state, incoming)
        pending = list(state.get("pending_planners", []))
        needs_plan = bool(new) or bool(pending) or (not incremental and state["messages"] and not state["plans"])
        if not new and not dups and not needs_plan:
            return None
        run_id = next_id(state["runs"], "run")
        ctx = RunContext(run_id, "incremental" if incremental else "full", self.client_factory)
        started = now()
        if new and self.client_factory is GroqClient and not os.getenv("GROQ_API_KEY"):
            self.client_factory()  # raises MissingApiKey before any state change
        work = copy.deepcopy(state)  # the committed state is never mutated in place
        work["messages"].extend(dups)
        run = {"messages_processed": len(dups), "planners": [], "outcome": "NO_CHANGE", "plan_id": None, "unresolved": []}
        if not new and not needs_plan:
            return self._finish(work, ctx, run_id, started, run)

        # --- read + decide
        changed, processed = set(), []
        ordered = sorted(new, key=lambda m: m["date"])
        to_read = [m for m in ordered if "facts" not in m]  # setup-form messages already carry their facts
        got = read_messages(ctx, to_read) if to_read else {}  # one model call for the whole batch
        read = {i: m["facts"] if "facts" in m else got.get(to_read.index(m) + 1) for i, m in enumerate(ordered, 1)}
        for i, msg in enumerate(ordered, 1):
            msg = {k: v for k, v in msg.items() if k != "facts"}
            raw = read.get(i)
            if msg["source"] == "Setup form" and raw is not None:  # items dropped from the form stop counting
                keep = {(r["key"], r["subject"]) for r in raw}
                for f in work["facts"]:
                    if f["status"] == "ACCEPTED" and f["source_name"] == "Setup form" and (f["key"], f["subject"]) not in keep:
                        f["status"], f["rejection_reason"] = "SUPERSEDED", "Removed in setup"
                        changed.add(f["key"])
            if raw is None:
                continue  # unreadable: left unrecorded so it can be resubmitted
            rec = {**msg, "hash": msg_hash(msg["source"], msg["text"]), "status": "PENDING", "processed_at": now(),
                   "run_id": run_id, "reason": None}
            work["messages"].append(rec)
            changed |= decide(work, msg, raw, run_id, now())
            processed.append(msg["id"])
        derive_message_statuses(work)
        run["messages_processed"] += len(processed)

        # --- resolve + plan
        full = not incremental
        todo, unresolved_keys = dependency_resolver.resolve(changed, full=full)
        todo = [p for p in PLANNERS if p in todo or p in pending] if not full else list(PLANNERS)
        run["unresolved"] = unresolved_keys
        if not todo:
            return self._finish(work, ctx, run_id, started, run)
        facts = Facts(work["facts"])
        active = next((p for p in state["plans"] if p["id"] == state["active_plan_id"]), None)
        sections = {k: copy.deepcopy(active[k]) for k in PLANNERS if active and active.get(k)} if active else {}
        violations, ran = [], []
        for name in todo:
            if ctx.remaining() <= 0:
                ctx.timed_out = True
                ctx.note(name, f"TIMEOUT — stopped after planner {ran[-1] if ran else 'none'}", "TIMEOUT")
                break
            sec, viol = PLANNER_FUNCS[name](facts, ctx, sections)
            ran.append(name)
            violations += viol
            if sec is not None:
                sections[name] = sec
        run["planners"] = ran
        unresolved = [k for k in PLANNERS if sections.get(k, {"unresolved": True}).get("unresolved")]
        if active:  # a change that makes a previously solved area impossible is a conflict, not "incomplete"
            violations += [{"area": k, "message": f"{k}: change makes this impossible ({sections[k].get('reason')})", "fact_ids": []}
                           for k in unresolved if k in ran and not active[k].get("unresolved")]
        if not violations and not unresolved and not ctx.timed_out:
            violations = constraint_engine.validate(sections, facts)

        plan = Plan(next_id(work["plans"], "plan"), now(), run_id, "COMMITTED",
                    fact_snapshot=facts.ids(), constraint_result={"valid": not violations, "violations": violations},
                    unenforced=unenforced(facts), **{k: sections.get(k) for k in PLANNERS})
        if violations:
            return self._reject(state, work, ctx, run_id, started, run, plan, violations, set(processed))
        if unresolved or ctx.timed_out:
            plan.status = "INCOMPLETE"
            work["plans"].append(asdict(plan))
            work["pending_planners"] = sorted(set(unresolved) | (set(todo) - set(ran)), key=PLANNERS.index)
            run["outcome"] = "TIMEOUT" if ctx.timed_out else "INCOMPLETE"
        else:
            work["plans"].append(asdict(plan))
            work["active_plan_id"], work["pending_planners"] = plan.id, []
            run["outcome"] = "COMMITTED"
        run["plan_id"] = plan.id
        return self._finish(work, ctx, run_id, started, run)

    # -- helpers
    def _intake(self, state, incoming):
        """Returns (new messages, DUPLICATE records). Same id+hash is skipped silently."""
        seen = {m["hash"]: m["id"] for m in state["messages"]}
        ids = {m["id"]: m["hash"] for m in state["messages"]}
        new, dups = [], []
        for m in incoming:
            h = msg_hash(m["source"], m["text"])
            if ids.get(m["id"]) == h:
                continue
            if m["id"] in ids and h not in seen:  # same id, different text: keep both, rename the newcomer
                m = {**m, "id": next_id(state["messages"] + new + dups, "MSG")}
            if h in seen:
                dups.append({**m, "id": m["id"] if m["id"] not in ids else next_id(state["messages"] + dups, "MSG"),
                             "hash": h, "status": "DUPLICATE", "processed_at": now(), "run_id": None,
                             "reason": f"Duplicate of {seen[h]}"})
                continue
            seen[h] = ids[m["id"]] = m["id"]
            new.append(m)
        return new, dups

    def _reject(self, state, work, ctx, run_id, started, run, plan, violations, processed):
        """Audit record: the committed state plus offending messages marked REJECTED. Active plan is untouched."""
        bad_facts = {i for v in violations for i in v["fact_ids"]}
        offenders = {f["source_message_id"] for f in work["facts"] if f["id"] in bad_facts} & processed
        if not offenders:  # violation not traceable to one fact: blame every new message that changed something
            offenders = {f["source_message_id"] for f in work["facts"] if f["source_message_id"] in processed}
        reason = "; ".join(v["message"] for v in violations)
        audit = copy.deepcopy(state)
        audit["messages"] += [m for m in work["messages"] if m["status"] == "DUPLICATE" and m["id"] not in {x["id"] for x in state["messages"]}]
        for m in work["messages"]:
            if m["id"] in offenders:
                audit["messages"].append({**m, "status": "REJECTED", "reason": f"Rejected: {reason}"})
        for f in work["facts"]:
            if f["source_message_id"] in offenders:
                audit["facts"].append({**f, "status": "REJECTED", "rejection_reason": reason, "supersedes": None})
        plan.status, plan.rejection_reason = "REJECTED", reason
        audit["plans"].append(asdict(plan))
        ctx.note(violations[0]["area"], f"REJECTED: {reason}", "REJECTED")
        run.update(outcome="REJECTED", plan_id=plan.id, rejected=sorted(offenders))
        return self._finish(audit, ctx, run_id, started, run)

    def _finish(self, st, ctx, run_id, started, run):
        calls = [t for t in ctx.trace if t["call_number"]]
        rec = asdict(RunResult(run_id, ctx.mode, started, now(), round(time.time() - ctx.start, 2),
                               run["messages_processed"], run["planners"], len(calls),
                               sum(t["total_tokens"] for t in calls), run["outcome"], run["plan_id"],
                               run["unresolved"], run.get("rejected", [])))
        st["trace"].extend(ctx.trace)
        st["runs"].append(rec)
        self.sm.save(st)
        return rec


def format_trace(state, run_id=None):
    """Exact spec format: numbered calls, TOTAL TOKENS per run, skipped/timeout notes."""
    out = []
    for run in state["runs"]:
        if run_id and run["id"] != run_id:
            continue
        entries = [t for t in state["trace"] if t["run_id"] == run["id"]]
        out.append(f"=== {run['id']} ({run['type']}) {run['outcome']} ===")
        for t in entries:
            n = t["call_number"]
            if t["status"] in ("SUCCESS", "ERROR"):
                out += [f"[{n}] model={t['model']}  area={t['area']}", f"INPUT:  {t['input']}", f"OUTPUT: {t['output']}",
                        f"TOKENS: prompt={t['prompt_tokens']}  completion={t['completion_tokens']}  total={t['total_tokens']}"]
            elif n:
                out.append(f"[{n}] {t['status']}  area={t['area']}")
            else:
                out.append(t["output"])
        out.append(f"TOTAL TOKENS: {run['total_tokens']}")
    return "\n".join(out)


def format_plan(state, rec=None):
    """Human-readable plan for the terminal: committed plan, or the rejection reason for the last run."""
    plans = {p["id"]: p for p in state["plans"]}
    rec = rec or (state["runs"][-1] if state["runs"] else None)
    plan = plans.get(state["active_plan_id"])
    out = [f"=== PLAN {plan['id']} ===" if plan else "=== NO VALID PLAN YET ==="]
    if rec and rec["outcome"] == "REJECTED":
        out.append(f"LATEST CHANGE REJECTED ({', '.join(rec['rejected']) or 'unknown'}): "
                   f"{plans[rec['plan_id']]['rejection_reason']}")
        out.append("Plan below is unchanged and still valid." if plan else "")
    if plan:
        v, f, j, s, b = (plan[k] for k in ("venue", "food", "judging", "schedule", "budget"))
        out += [f"VENUE:    {v['name']} (capacity {v['capacity']}, Rs {v['price']:,})",
                f"FOOD:     {f['package']} x {f['headcount']} = Rs {f['total_cost']:,}",
                f"JUDGING:  {j['judge_count']} judges, {j['teams']} teams, window {j['window_minutes']} min"
                if "window_minutes" in j else f"JUDGING:  {j['judge_count']} judges, {j['teams']} teams",
                "SCHEDULE: " + " -> ".join(f"{x['time']} {x['label']}" for x in s["blocks"])]
        out += [f"          note: {s['reasons']}"] if s.get("reasons") else []
        costs = {k: x for k, x in b.items() if isinstance(x, (int, float)) and not isinstance(x, bool)}
        out.append("BUDGET:   " + ", ".join(f"{k}={x:,}" for k, x in costs.items()))
        out += [f"NOTE (not enforced): {u['subject'] or u['key']}" for u in plan.get("unenforced", [])]
    bad = [m for m in state["messages"] if m["status"] in ("REJECTED", "DUPLICATE", "SUPERSEDED", "CONFLICTED")]
    out += [f"MESSAGE {m['id']}: {m['status']} - {m.get('reason')}" for m in bad]
    return "\n".join(x for x in out if x)


def export_payload(state):
    """Everything the judges need in one file: final plan, flagged messages and the complete trace."""
    plans = {p["id"]: p for p in state["plans"]}
    return {"plan": plans.get(state["active_plan_id"]), "runs": state["runs"],
            "messages": [{k: m[k] for k in ("id", "source", "channel", "date", "status", "reason")} for m in state["messages"]],
            "trace": state["trace"], "trace_text": format_trace(state)}
