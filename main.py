"""CLI: python main.py run --messages <file>. Full vs incremental is detected from saved state."""
import argparse
import sys

from dotenv import load_dotenv

load_dotenv(".env")

from engine.orchestrator import Orchestrator, format_trace, parse_messages  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="main.py")
    ap.add_argument("command", choices=["run"])
    ap.add_argument("--messages", required=True)
    args = ap.parse_args(argv)
    try:
        msgs = parse_messages(open(args.messages, encoding="utf-8").read())
        orch = Orchestrator()
        rec = orch.run(msgs)
    except (OSError, RuntimeError) as e:
        sys.exit(f"Error: {e}")
    if rec is None:
        print("No new messages. Plan unchanged.")
        return
    print(format_trace(orch.sm.load(), rec["id"]))
    print(f"\nOutcome: {rec['outcome']}  planners={rec['planners_run']}  time={rec['duration_seconds']}s")


if __name__ == "__main__":
    main()
