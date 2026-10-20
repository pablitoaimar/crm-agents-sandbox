"""
Entry point.

  python run.py                         # demo with the replay backend (no key)
  python run.py --yes                   # same, without asking for approval
  python run.py --backend anthropic --objective "..."   # real model
  python run.py --reset-db              # rebuild the database first

Each run creates runs/<date_time>/ with:
  trace.md     what each agent thought, asked for and received
  trace.jsonl  the same, in machine format
  plan.md      the plan that went to approval
  results.md   test results
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import pipeline  # noqa: E402
from llm import AnthropicBackend, ReplayBackend  # noqa: E402
from tracer import Tracer  # noqa: E402

DEFAULT_OBJECTIVE = (
    "Turn first-rental customers into a second rental. "
    "Focus on people who returned the car 1 to 3 months ago; we also want to push app adoption."
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["replay", "anthropic"], default="replay")
    ap.add_argument("--replay-file", default=str(ROOT / "replay" / "second_rental.json"))
    ap.add_argument("--objective", default=DEFAULT_OBJECTIVE)
    ap.add_argument("--yes", action="store_true", help="approve automatically")
    ap.add_argument("--reset-db", action="store_true")
    ap.add_argument("--min-size", type=int, default=None,
                    help="minimum segment size (default 600, for A/B)")
    ap.add_argument("--no-ab", action="store_true",
                    help="campaign without an A/B test (1 variant, no holdout), for small segments")
    args = ap.parse_args()

    db = ROOT / "data" / "crm.db"
    if args.reset_db or not db.exists():
        subprocess.run([sys.executable, str(ROOT / "data" / "build_db.py")], check=True)

    backend = AnthropicBackend() if args.backend == "anthropic" else ReplayBackend(args.replay_file)
    if args.backend == "replay" and args.objective != DEFAULT_OBJECTIVE and "second_rental" in args.replay_file:
        print("Warning: in replay mode the replies are recorded for the default objective.")

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]  # ms: avoids collisions when the watcher launches 2 in a row
    run_dir = ROOT / "runs" / run_id
    tracer = Tracer(run_dir)
    campaign_id = f"CMP-AGT-{run_id}"
    state = {}
    if args.min_size is not None:
        state["min_size"] = args.min_size
    if args.no_ab:
        state["ab_test"] = False

    try:
        if not pipeline.step_segment(args.objective, backend, state, tracer):
            print("\nSegmentation failed. If you already ran the demo today, the fatigue rule excludes "
                  "whoever received the previous send: run with --reset-db.")
            return
        if not pipeline.step_content(args.objective, backend, state, tracer):
            print("\nContent failed.")
            return
        pipeline.step_plan(state, run_dir, tracer)
        if not pipeline.step_approve(args.yes, tracer):
            print("Not approved. Nothing was sent.")
            return
        pipeline.step_send(state, campaign_id, tracer)
        pipeline.step_evaluate(campaign_id, run_dir, tracer)
    finally:
        tracer.close()
        print(f"\nFiles for this run: {run_dir}")


if __name__ == "__main__":
    main()
