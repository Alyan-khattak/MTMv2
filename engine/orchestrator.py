"""Single entry point for CLI and API: ingest messages -> read -> decide -> resolve -> plan -> validate -> commit."""
import copy
import hashlib
import json
import os
import re
import time
from dataclasses import asdict
from datetime import datetime

from agents.reading_agent import GroqClient, read_message
from engine import constraint_engine, dependency_resolver
from engine.decision_engine import decide, derive_message_statuses, next_id
from models.schemas import PLANNERS, Facts, Plan, RunResult, TraceEntry, model_name
from planners import budget_planner, food_planner, judging_planner, schedule_planner, venue_planner
from state.state_manager import StateManager

PLANNER_FUNCS = {"venue": venue_planner.plan, "food": food_planner.plan, "judging": judging_planner.plan,
                 "schedule": schedule_planner.plan, "budget": budget_planner.plan}
HEADER = re.compile(r"^(\S+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*$")


def now():
    return datetime.now().isoformat(timespec="seconds")


def parse_messages(text):
    """Blocks of `ID | source | channel | date` followed by body lines."""
    out = []
    for line in text.splitlines():
        m = HEADER.match(line.strip())
        if m:
            out.append({"id": m[1], "source": m[2], "channel": m[3], "date": m[4], "text": ""})
        elif out and line.strip():
            out[-1]["text"] = (out[-1]["text"] + " " + line.strip()).strip()
    return [m for m in out if m["text"]]


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
            self._add(area, inp, "TIMEOUT", "TIMEOUT")
            return None
        if self.max_calls is not None and self.real_calls >= self.max_calls:
            self.exhausted = True
            self._add(area, inp, "BUDGET_EXHAUSTED", "BUDGET_EXHAUSTED")
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
        for msg in sorted(new, key=lambda m: m["date"]):
            raw = read_message(ctx, msg)
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
        if not violations and not unresolved and not ctx.timed_out:
            violations = constraint_engine.validate(sections, facts)

        plan = Plan(next_id(work["plans"], "plan"), now(), run_id, "COMMITTED",
                    fact_snapshot=facts.ids(), constraint_result={"valid": not violations, "violations": violations},
                    **{k: sections.get(k) for k in PLANNERS})
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
        ctx.note("budget", f"REJECTED: {reason}", "REJECTED")
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
