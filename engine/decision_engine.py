"""Conflict resolution by source authority then recency. Pure Python, never calls the LLM."""
import re

# (keyword in source name, rank). First match wins; order matters ("Judging coordinator" is a coordinator, not a judge).
AUTHORITY = [("dean", 1), ("financ", 2), ("coordinator", 3), ("caterer", 4), ("hall", 4), ("venue", 4),
             ("vendor", 4), ("student", 5), ("judge", 6)]
DEFAULT_RANK = 5


def authority_rank(source):
    s = source.lower()
    return next((r for k, r in AUTHORITY if k in s), DEFAULT_RANK)


def next_id(items, prefix):
    nums = [int(m.group(1)) for i in items if (m := re.search(r"(\d+)$", i["id"]))]
    return f"{prefix}-{max(nums, default=0) + 1:03d}"


def decide(state, msg, raw_facts, run_id, now):
    """Adds each raw fact to state['facts'] with a lifecycle status. Returns the set of fact keys whose accepted value changed."""
    changed = set()
    rank = authority_rank(msg["source"])
    for rf in raw_facts:
        f = {"id": next_id(state["facts"], "fact"), "key": rf["key"], "subject": rf["subject"], "value": rf["value"],
             "source_message_id": msg["id"], "source_name": msg["source"], "source_date": msg["date"],
             "authority_rank": rank, "status": "ACCEPTED", "supersedes": None, "superseded_by": None,
             "rejection_reason": None, "extracted_at": now}
        old = next((x for x in state["facts"] if x["status"] == "ACCEPTED" and x["key"] == f["key"]
                    and x["subject"] == f["subject"]), None)
        if not rf["approved"]:
            f["status"], f["rejection_reason"] = "REJECTED", "Proposal or quote, not approved by an authorising source"
        elif old:
            if rank < old["authority_rank"] or (rank == old["authority_rank"] and msg["date"] >= old["source_date"]):
                old["status"], old["superseded_by"], f["supersedes"] = "SUPERSEDED", f["id"], old["id"]
                if old["value"] != f["value"]:
                    changed.add(f["key"])
            elif rank > old["authority_rank"]:
                f["status"], f["rejection_reason"] = "REJECTED", f"Lower authority than {old['source_name']}"
            else:
                f["status"], f["superseded_by"] = "SUPERSEDED", old["id"]  # same authority but older
        else:
            changed.add(f["key"])
        state["facts"].append(f)
        state["decisions"].append({"fact_id": f["id"], "decision": f["status"], "run_id": run_id,
                                   "reason": f["rejection_reason"]})
    return changed


def derive_message_statuses(state):
    """Message status follows its facts: any ACCEPTED -> ACCEPTED; none -> IRRELEVANT; all REJECTED -> REJECTED; else SUPERSEDED."""
    for m in state["messages"]:
        if m["status"] in ("DUPLICATE", "REJECTED") and m.get("reason"):
            continue
        fs = [f for f in state["facts"] if f["source_message_id"] == m["id"]]
        if not fs:
            m["status"], m["reason"] = "IRRELEVANT", "No actionable facts extracted"
        elif any(f["status"] == "ACCEPTED" for f in fs):
            m["status"], m["reason"] = "ACCEPTED", None
        elif all(f["status"] == "REJECTED" for f in fs):
            m["status"], m["reason"] = "REJECTED", fs[0]["rejection_reason"]
        else:
            m["status"], m["reason"] = "SUPERSEDED", "Overridden by a newer or higher-authority message"
