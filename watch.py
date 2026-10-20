"""
The WATCHER. This is what makes the agents run on their own.

Each time it runs:
  1. reads triggers/rules.json
  2. for each rule, runs the detection SQL (read-only)
  3. each returned row = one trigger (e.g. a branch with low ratings)
  4. if that trigger already fired within the cooldown, skip it
  5. otherwise run the actions: alert and/or campaign (agent pipeline)
  6. log everything to triggers/watch_log.jsonl

Who calls the watcher? A scheduler. On your PC: Windows Task Scheduler
running "python watch.py" every hour. In a company: Airflow, a cron job on a server,
a workflow in the send platform, or an event on a stream (Kafka).

Usage:
  python watch.py                         # dry-run: shows what it would do, launches nothing
  python watch.py --execute               # launches the campaigns (needs --backend anthropic)
  python watch.py --execute --backend anthropic
  python watch.py --reset-state           # forget cooldowns (to repeat the demo)
"""
import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
import tools  # noqa: E402

RULES = ROOT / "triggers" / "rules.json"
STATE = ROOT / "triggers" / "state.json"
LOG = ROOT / "triggers" / "watch_log.jsonl"
ALERTS = ROOT / "triggers" / "alerts.md"


def load_state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(s):
    STATE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")


def log(event):
    event["ts"] = datetime.now().isoformat(timespec="seconds")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def in_cooldown(state, key, days):
    last = state.get(key)
    if not last:
        return False
    return (date.fromisoformat(tools.TODAY) - date.fromisoformat(last)).days < days


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="actually launch the campaign actions")
    ap.add_argument("--backend", choices=["replay", "anthropic"], default="anthropic")
    ap.add_argument("--yes", action="store_true", help="approve campaigns without asking (not recommended)")
    ap.add_argument("--reset-state", action="store_true")
    args = ap.parse_args()

    if args.reset_state and STATE.exists():
        STATE.unlink()
    if not (ROOT / "data" / "crm.db").exists():
        subprocess.run([sys.executable, str(ROOT / "data" / "build_db.py")], check=True)

    rules = json.loads(RULES.read_text(encoding="utf-8"))["rules"]
    state = load_state()
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"Watcher running in {mode} mode, reference date {tools.TODAY}\n")

    for rule in rules:
        if not rule.get("enabled", True):
            continue
        res = tools.run_sql(None, sql=rule["detect_sql"])
        if "error" in res:
            print(f"[{rule['id']}] ERROR in detection SQL: {res['error']}")
            log({"rule": rule["id"], "event": "detect_error", "error": res["error"]})
            continue
        hits = [dict(zip(res["columns"], row)) for row in res["rows"]]
        print(f"[{rule['id']}] {rule['description']}\n    -> {len(hits)} trigger(s)")
        log({"rule": rule["id"], "event": "checked", "hits": len(hits)})

        for hit in hits:
            key = f"{rule['id']}::{hit[rule['entity_column']]}"
            if in_cooldown(state, key, rule["cooldown_days"]):
                print(f"    {key}: already fired on {state[key]}, in cooldown ({rule['cooldown_days']} days). Skipped.")
                log({"rule": rule["id"], "event": "suppressed_cooldown", "key": key})
                continue

            print(f"    {key}: FIRES  {hit}")
            for action in rule["actions"]:
                if action["type"] == "alert":
                    msg = action["message"].format(**hit)
                    print(f"      ALERT: {msg}")
                    if args.execute:
                        with open(ALERTS, "a", encoding="utf-8") as f:
                            f.write(f"- {tools.TODAY} [{rule['id']}] {msg}\n")
                    log({"rule": rule["id"], "event": "alert", "key": key, "message": msg, "executed": args.execute})

                elif action["type"] == "campaign":
                    objective = action["objective"].format(**hit)
                    cmd = [sys.executable, str(ROOT / "run.py"), "--backend", args.backend,
                           "--objective", objective]
                    if "min_segment_size" in action:
                        cmd += ["--min-size", str(action["min_segment_size"])]
                    if action.get("ab_test") is False:
                        cmd.append("--no-ab")
                    if args.backend == "replay" and "replay_file" in action:
                        cmd += ["--replay-file", str(ROOT / action["replay_file"])]
                    if args.yes:
                        cmd.append("--yes")
                    print(f"      CAMPAIGN: objective -> {objective}")
                    log({"rule": rule["id"], "event": "campaign", "key": key,
                         "objective": objective, "executed": args.execute})
                    if args.execute:
                        subprocess.run(cmd, check=False)
                    else:
                        print("      (dry-run: not launched. Use --execute to launch.)")

            if args.execute:
                state[key] = tools.TODAY
        print()

    if args.execute:
        save_state(state)
    print(f"Log: {LOG}")


if __name__ == "__main__":
    main()
