"""CLI: python main.py run --messages <file>. Full vs incremental is detected from saved state."""
import argparse
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv(".env")

from engine.predict import predict  # noqa: E402
from state.state_manager import StateManager  # noqa: E402
from engine.orchestrator import Orchestrator, export_payload, format_plan, format_trace, parse_messages, report_text  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="main.py")
    ap.add_argument("command", choices=["run", "predict"])
    ap.add_argument("--messages")
    args = ap.parse_args(argv)
    if args.command == "predict":  # the slip the volunteer asks for before a change message
        return print(predict()["text"])
    if not args.messages:
        sys.exit("Error: --messages is required")
    try:
        msgs = parse_messages(open(args.messages, encoding="utf-8").read())
        h = os.getenv("HACKATHON")  # optional: run a hackathon made in the web UI
        orch = Orchestrator(StateManager(f"hackathons/{h}/state.json") if h else None)
        rec = orch.run(msgs)
    except (OSError, RuntimeError, ValueError) as e:
        sys.exit(f"Error: {e}")
    state = orch.sm.load()
    if rec is None:
        print("No new messages. Plan unchanged.\n\n" + format_plan(state))
        return
    print(format_trace(state, rec["id"]))
    print("\n" + format_plan(state, rec))
    out = os.getenv("OUTPUT_FILE", "final_output.json")  # final plan + full trace of every run, for submission
    with open(out, "w", encoding="utf-8") as f:
        json.dump(export_payload(state), f, indent=2, ensure_ascii=False)
    txt = os.getenv("OUTPUT_TXT", "final_output.txt")  # the readable file: plan + one line per model call
    with open(txt, "w", encoding="utf-8") as f:
        f.write(report_text(state) + "\n")
    print(f"\nSaved plan + full trace to {out} and {txt}")
    print(f"\nOutcome: {rec['outcome']}  planners={rec['planners_run']}  time={rec['duration_seconds']}s")


if __name__ == "__main__":
    main()
