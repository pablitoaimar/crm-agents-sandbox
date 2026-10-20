"""
THE AGENT LOOP. This is the "agent" itself, and it is small.

    1. send to the model: instructions + objective + list of tools
    2. the model replies with text and/or tool requests
    3. the code runs the requested tools and returns the results
    4. repeat until the model stops OR the success condition is met
       OR the steps run out (safety limit)

Everything is recorded in the trace for auditing.
"""
import json
import time

from tracer import Tracer


def run_agent(*, name, system, task, tools, backend, state, done, tracer: Tracer, max_steps=12):
    """
    name    : agent name (for the trace and for replay)
    system  : the agent's standing instructions (its "job description")
    task    : the concrete request for this run
    tools   : dict {name: {"fn", "schema"}}
    state   : shared dict where tools store accepted results
    done    : function(state) -> True when the agent's goal is met
    """
    messages = [{"role": "user", "content": task}]
    schemas = [t["schema"] for t in tools.values()]
    tracer.agent_start(name, task)

    for step in range(1, max_steps + 1):
        t0 = time.time()
        reply = backend.respond(name, system, messages, schemas)
        tracer.model_turn(name, step, reply, time.time() - t0)
        messages.append({"role": "assistant", "content": reply["content"]})

        tool_calls = [b for b in reply["content"] if b["type"] == "tool_use"]
        if not tool_calls:
            break

        results = []
        for call in tool_calls:
            tool = tools.get(call["name"])
            if tool is None:
                out = {"error": f"Unknown tool: {call['name']}"}
            else:
                try:
                    out = tool["fn"](state, **call["input"])
                except Exception as e:  # a tool error goes back to the model, it does not crash the pipeline
                    out = {"error": f"{type(e).__name__}: {e}"}
            tracer.tool_call(name, step, call["name"], call["input"], out)
            results.append({"type": "tool_result", "tool_use_id": call["id"],
                            "content": json.dumps(out, ensure_ascii=False, default=str)[:8000]})
        messages.append({"role": "user", "content": results})

        if done(state):
            tracer.agent_end(name, "ok", step)
            return True

    ok = done(state)
    tracer.agent_end(name, "ok" if ok else "FAILED", step)
    return ok
