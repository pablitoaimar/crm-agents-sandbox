"""
Records everything that happens in a run.
  runs/<run_id>/trace.jsonl : for machines (1 event per line)
  runs/<run_id>/trace.md    : for humans (read this to see what the agent did)
It also prints to the console.
"""
import json
from datetime import datetime
from pathlib import Path


def _short(obj, n=600):
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + " ...(truncated)"


class Tracer:
    def __init__(self, run_dir: Path):
        self.dir = run_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.jsonl = open(self.dir / "trace.jsonl", "w", encoding="utf-8")
        self.md = open(self.dir / "trace.md", "w", encoding="utf-8")
        self.md.write(f"# Run trace {self.dir.name}\n\n")

    def _event(self, kind, **data):
        data.update({"ts": datetime.now().isoformat(timespec="seconds"), "kind": kind})
        self.jsonl.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
        self.jsonl.flush()

    def _md(self, text):
        self.md.write(text + "\n")
        self.md.flush()

    def stage(self, title, detail=""):
        self._event("stage", title=title, detail=detail)
        print(f"\n=== {title} ===")
        if detail:
            print(detail)
        self._md(f"\n## {title}\n\n{detail}\n")

    def agent_start(self, name, task):
        self._event("agent_start", agent=name, task=task)
        print(f"\n[{name}] task: {_short(task, 300)}")
        self._md(f"### Agent `{name}`\n\n**Task:** {task}\n")

    def model_turn(self, name, step, reply, secs):
        self._event("model_turn", agent=name, step=step, reply=reply, secs=round(secs, 2))
        for b in reply["content"]:
            if b["type"] == "text" and b["text"].strip():
                print(f"[{name}] step {step} THINKS: {_short(b['text'], 400)}")
                self._md(f"**Step {step}, model:** {b['text']}\n")
            elif b["type"] == "tool_use":
                print(f"[{name}] step {step} ASKS -> {b['name']}({_short(b['input'], 300)})")
                inp = b["input"]
                if "sql" in inp:
                    self._md(f"**Step {step}, asks for `{b['name']}`:**\n\n```sql\n{inp['sql'].strip()}\n```\n")
                else:
                    self._md(f"**Step {step}, asks for `{b['name']}`:** `{_short(inp, 1500)}`\n")

    def tool_call(self, name, step, tool, inp, out):
        self._event("tool_result", agent=name, step=step, tool=tool, input=inp, output=out)
        flag = ""
        if isinstance(out, dict) and (out.get("ok") is False or "error" in out):
            flag = "  <-- REJECTED by the code"
        print(f"[{name}] step {step} RESULT {tool}: {_short(out, 300)}{flag}")
        self._md(f"> Result `{tool}`{' (REJECTED)' if flag else ''}: `{_short(out, 1200)}`\n")

    def agent_end(self, name, status, steps):
        self._event("agent_end", agent=name, status=status, steps=steps)
        print(f"[{name}] finished: {status} in {steps} steps")
        self._md(f"**Agent `{name}` result: {status} in {steps} steps.**\n")

    def close(self):
        self.jsonl.close()
        self.md.close()
