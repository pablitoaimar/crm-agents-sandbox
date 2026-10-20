"""
Packs one or more run folders (runs/<name>/) into docs/data/runs.js for the run viewer.

The viewer (docs/index.html) reads trace.jsonl, the event log every run writes.
This script only cleans and bundles it:
  - removes absolute local paths (C:\\Users\\..., /home/...)
  - shortens very long tool outputs (e.g. the full data catalogue)

The output is JSON wrapped in "window.RUNS = ...;" so the page works when you
open it by double-clicking (browsers block fetch() of local .json files).

Usage (from the repo root, standard library only):
  python docs/build_run_json.py                      # the two committed examples
  python docs/build_run_json.py runs/<your-run> ...  # any run folders
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / "runs.js"
DEFAULT_RUNS = ["runs/second-rental-example", "runs/faro-service-recovery-example"]
MAX_STR = 1500

# Everything from a drive letter or /home|/Users up to (not including) "runs/".
_ABS_TO_RUNS = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:home|Users)/)[^\n\"]*?[\\/](?=runs[\\/])")
_ABS_OTHER = re.compile(r"(?:[A-Za-z]:\\Users\\|/(?:home|Users)/)[^\s\"\\/]+")


def _clean(value):
    if isinstance(value, str):
        value = _ABS_TO_RUNS.sub("", value)
        value = _ABS_OTHER.sub("~", value)
        if len(value) > MAX_STR:
            value = value[:MAX_STR] + f"\n... ({len(value) - MAX_STR} more characters cut for the viewer)"
        return value
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    return value


def load_run(folder: Path):
    trace = folder / "trace.jsonl"
    if not trace.exists():
        raise SystemExit(f"No trace.jsonl in {folder}")
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {"name": folder.name, "events": _clean(events)}


def main():
    folders = [ROOT / a for a in (sys.argv[1:] or DEFAULT_RUNS)]
    runs = [load_run(f) for f in folders]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("window.RUNS = " + json.dumps(runs, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    for r in runs:
        print(f"{r['name']}: {len(r['events'])} events")
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
