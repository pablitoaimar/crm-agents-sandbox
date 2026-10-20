"""
The agent's "brain". Two backends with the same interface:

  AnthropicBackend : calls the real model (needs ANTHROPIC_API_KEY)
  ReplayBackend    : returns pre-recorded replies from a JSON file.
                     Lets you see the full flow with no key and no cost.
                     The tools run FOR REAL; only the model's "decisions"
                     are recorded.

Both return the same format:
  {"stop_reason": "tool_use" | "end_turn",
   "content": [ {"type": "text", "text": ...},
                {"type": "tool_use", "id": ..., "name": ..., "input": {...}} ]}
"""
import json
import os
from pathlib import Path


class AnthropicBackend:
    def __init__(self, model=None):
        try:
            import anthropic  # pip install anthropic
        except ImportError as e:
            raise SystemExit("Missing package: pip install anthropic") from e
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("Set the ANTHROPIC_API_KEY variable (console.anthropic.com).")
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("CRM_AGENT_MODEL", "claude-sonnet-5-5")

    def respond(self, agent_name, system, messages, tools):
        resp = self.client.messages.create(
            model=self.model, max_tokens=4000, system=system,
            messages=messages, tools=tools)
        return {"stop_reason": resp.stop_reason,
                "content": [b.model_dump(exclude_none=True) for b in resp.content]}


class ReplayBackend:
    def __init__(self, script_path):
        data = json.loads(Path(script_path).read_text(encoding="utf-8"))
        self.turns = {k: list(v) for k, v in data["agents"].items()}

    def respond(self, agent_name, system, messages, tools):
        queue = self.turns.get(agent_name)
        if not queue:
            raise RuntimeError(f"Replay has no more replies for agent '{agent_name}'.")
        turn = queue.pop(0)
        content = []
        for i, block in enumerate(turn):
            if "tool" in block:
                content.append({"type": "tool_use", "id": f"replay_{agent_name}_{len(queue)}_{i}",
                                "name": block["tool"], "input": block.get("input", {})})
            else:
                content.append({"type": "text", "text": block["text"]})
        stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
        return {"stop_reason": stop, "content": content}
