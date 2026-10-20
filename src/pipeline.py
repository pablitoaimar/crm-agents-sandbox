"""
ORCHESTRATION. Connects the agents into a process with control points.

Note what is LLM and what is code:

  step                         who decides
  --------------------------   --------------------------------------------
  1. segment                   AGENT proposes -> code validates
  2. exclusions                CODE (consent, fatigue) - never the LLM
  3. content                   AGENT proposes -> brand linter validates
  4. A/B plan + holdout        CODE (seeded randomisation)
  5. approval                  HUMAN
  6. send                      CODE (simulated here; in real life, the send platform's API)
  7. evaluation                CODE (statistics), not the LLM

In a more autonomous version, steps 5 and 7 would be automated
step by step for low-risk cases. But you always start like this.
"""
import json
import math
import random
from pathlib import Path

import tools
from agent_loop import run_agent

ROOT = Path(__file__).resolve().parent.parent
HOLDOUT_PCT = 0.10
SEED = 7


def _prompt(name):
    return (ROOT / "agents" / f"{name}.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1 + 2: segmentation
# ---------------------------------------------------------------------------
def step_segment(objective, backend, state, tracer):
    tracer.stage("1. Segmentation (agent)", f"Objective: {objective}")
    ok = run_agent(
        name="segmentation", system=_prompt("segmentation"),
        task=f"Business objective: {objective}\nDefine and submit the segment.",
        tools=tools.toolset(["get_catalog", "run_sql", "submit_segment"]),
        backend=backend, state=state, tracer=tracer,
        done=lambda s: "segment" in s)
    if ok:
        f = state["segment"]["funnel"]
        tracer.stage("2. Mandatory exclusions (code)",
                     f"Proposed by the agent: {f['proposed']} -> with consent: {f['after_consent']} "
                     f"-> without fatigue ({tools.FATIGUE_DAYS} days): {f['after_fatigue']}")
    return ok


# ---------------------------------------------------------------------------
# 3: content
# ---------------------------------------------------------------------------
def step_content(objective, backend, state, tracer):
    tracer.stage("3. Content (agent)")
    seg = state["segment"]
    how_many = ("This campaign has NO A/B test (small segment): write and submit ONE variant only."
                if state.get("ab_test", True) is False else "Write and submit the variants.")
    return run_agent(
        name="content", system=_prompt("content"),
        task=(f"Business objective: {objective}\nApproved segment: {seg['name']}\n"
              f"Segment rationale: {seg['rationale']}\n{how_many}"),
        tools=tools.toolset(["get_segment_profile", "get_brand_rules", "check_copy", "submit_variants"]),
        backend=backend, state=state, tracer=tracer,
        done=lambda s: "variants" in s)


# ---------------------------------------------------------------------------
# 4 + 5: plan and human approval
# ---------------------------------------------------------------------------
def step_plan(state, run_dir, tracer):
    con = tools._ro_conn()
    ids = [r[0] for r in con.execute(state["segment"]["final_sql"]).fetchall()]
    con.close()
    rng = random.Random(SEED)
    rng.shuffle(ids)
    n_hold = int(len(ids) * HOLDOUT_PCT) if state.get("ab_test", True) else 0
    labels = [v["variant"] for v in state["variants"]]
    assignment = {cid: "HOLDOUT" for cid in ids[:n_hold]}
    for i, cid in enumerate(ids[n_hold:]):
        assignment[cid] = labels[i % len(labels)]
    state["assignment"] = assignment

    counts = {}
    for g in assignment.values():
        counts[g] = counts.get(g, 0) + 1

    seg = state["segment"]
    lines = [f"# Campaign plan (for approval)\n",
             f"**Segment:** {seg['name']}\n",
             f"**Rationale:** {seg['rationale']}\n",
             "**Agent's SQL:**\n", f"```sql\n{seg['agent_sql']}\n```\n",
             f"**Funnel:** {seg['funnel']}\n",
             "**Groups:** " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) + "\n",
             "## Variants\n"]
    for v in state["variants"]:
        lines += [f"### {v['variant']}  \n*Hypothesis:* {v['hypothesis']}\n",
                  f"- Subject: {v['subject']}", f"- Preheader: {v['preheader']}",
                  f"- CTA: {v['cta_label']}\n", f"> {v['body']}\n"]
    (run_dir / "plan.md").write_text("\n".join(lines), encoding="utf-8")
    tracer.stage("4. A/B plan + holdout (code)",
                 "Groups: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
                 + f"\nFull plan in {run_dir / 'plan.md'}")


def step_approve(auto_yes, tracer):
    tracer.stage("5. Human approval")
    if auto_yes:
        print("Approved automatically (--yes).")
        return True
    ans = input("Have you read plan.md? Approve the send? [y/N] ").strip().lower()
    return ans in ("s", "sim", "y", "yes")


# ---------------------------------------------------------------------------
# 6: send (SIMULATED)
# ---------------------------------------------------------------------------
def _true_uplift(variant):
    """
    TOY MODEL of customer behaviour. This is not the agent:
    it is the 'world' the agent does not know. It gives the A/B test something to measure.
    """
    text = " ".join([variant["subject"], variant["body"]]).lower()
    lift = 0.10
    if "{{last_city}}" in text or "{{last_vehicle_class}}" in text:
        lift += 0.25
    if "%" in text:
        lift += 0.35
    return lift


def step_send(state, campaign_id, tracer):
    rng = random.Random(SEED + 1)
    con = tools._rw_conn()
    has_app = dict(con.execute("SELECT customer_id, has_app FROM customers").fetchall())
    variants = {v["variant"]: v for v in state["variants"]}
    rows = []
    for cid, g in state["assignment"].items():
        base = 0.045 if has_app[cid] else 0.03          # organic return rate
        if g == "HOLDOUT":
            conv = 1 if rng.random() < base else 0
            rows.append((campaign_id, cid, g, "none", tools.TODAY, 0, 0, conv))
            continue
        p = base * (1 + _true_uplift(variants[g]))
        opened = 1 if rng.random() < 0.34 else 0
        clicked = 1 if opened and rng.random() < 0.22 else 0
        conv = 1 if rng.random() < p else 0
        rows.append((campaign_id, cid, g, "email", tools.TODAY, opened, clicked, conv))
    con.execute("INSERT OR REPLACE INTO campaigns VALUES (?,?,?,?,?)",
                (campaign_id, state["segment"]["name"], "second_rental", tools.TODAY, "sent"))
    con.executemany(
        "INSERT INTO crm_sends (campaign_id, customer_id, variant, channel, sent_at, opened, clicked, converted) "
        "VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    tracer.stage("6. Send (SIMULATED)",
                 f"{len(rows)} rows written to crm_sends with campaign_id={campaign_id}. "
                 "In real life this step would call the send platform's API.")


# ---------------------------------------------------------------------------
# 7: evaluation (statistics, no LLM)
# ---------------------------------------------------------------------------
def _z_test(c1, n1, c2, n2):
    p1, p2 = c1 / n1, c2 / n2
    p = (c1 + c2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) or 1e-9
    z = (p1 - p2) / se
    pval = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return z, pval


def _n_needed(p_base, rel_lift, alpha_z=1.96, power_z=0.84):
    p2 = p_base * (1 + rel_lift)
    pbar = (p_base + p2) / 2
    num = (alpha_z * math.sqrt(2 * pbar * (1 - pbar)) + power_z * math.sqrt(p_base * (1 - p_base) + p2 * (1 - p2))) ** 2
    return math.ceil(num / (p2 - p_base) ** 2)


def step_evaluate(campaign_id, run_dir, tracer):
    con = tools._ro_conn()
    rows = con.execute("""
        SELECT variant, COUNT(*) n, SUM(opened) o, SUM(clicked) k, SUM(converted) c
        FROM crm_sends WHERE campaign_id = ? GROUP BY variant ORDER BY variant""", (campaign_id,)).fetchall()
    con.close()
    stats = {r[0]: {"n": r[1], "opened": r[2], "clicked": r[3], "conv": r[4]} for r in rows}
    if "HOLDOUT" not in stats:
        out = ["# Results (no A/B)\n", "| group | n | opens | clicks | conversions |", "|---|---|---|---|---|"]
        out += [f"| {g} | {s['n']} | {s['opened']} | {s['clicked']} | {s['conv']} |" for g, s in stats.items()]
        out += ["", "Small segment: no holdout and no statistical significance. "
                "The value of this campaign is measured at service level (did the branch fix the problem? did ratings recover?), "
                "not on the copy.", "\n*Simulated send.*"]
        report = "\n".join(out)
        (run_dir / "results.md").write_text(report, encoding="utf-8")
        tracer.stage("7. Evaluation (code)", report)
        return
    hold = stats.pop("HOLDOUT")
    p_hold = hold["conv"] / hold["n"]

    out = ["# Results\n",
           "| group | n | open % | click % | conversion % | lift vs holdout | p-value |",
           "|---|---|---|---|---|---|---|",
           f"| HOLDOUT | {hold['n']} | - | - | {p_hold*100:.2f} | - | - |"]
    best = None
    for g, s in stats.items():
        p = s["conv"] / s["n"]
        _, pv = _z_test(s["conv"], s["n"], hold["conv"], hold["n"])
        lift = (p / p_hold - 1) * 100 if p_hold else float("nan")
        out.append(f"| {g} | {s['n']} | {s['opened']/s['n']*100:.1f} | {s['clicked']/s['n']*100:.1f} | "
                   f"{p*100:.2f} | {lift:+.0f}% | {pv:.3f} |")
        if best is None or p > best[1]:
            best = (g, p, pv)

    n_arm = min(s["n"] for s in stats.values())
    need = _n_needed(p_hold, 0.30) if 0 < p_hold < 1 else float("inf")
    out += ["", f"**Best variant:** {best[0]} (p-value vs holdout = {best[2]:.3f}).",
            "",
            f"**Statistical power:** to detect a 30% relative lift on a base rate of {p_hold*100:.1f}% "
            f"you would need ~{need} customers per group. This test has ~{n_arm} per group.",
            ""]
    if best[2] < 0.05:
        out.append("Conclusion: statistically significant difference. Candidate to become the new baseline.")
    else:
        out.append("Conclusion: **inconclusive**. Do not declare a winner. Options: accumulate more sends "
                   "(continuous test), fewer variants, or a goal with a higher base rate (e.g. clicks).")
    out.append("\n*These results come from a simulated send (src/pipeline.py -> _true_uplift).*")
    report = "\n".join(out)
    (run_dir / "results.md").write_text(report, encoding="utf-8")
    tracer.stage("7. Evaluation (code, statistics)", report)
