"""
The agents' TOOLS.

An agent does not "do" anything by itself: it can only ask to call these
functions. Each function is normal code, deterministic and testable. This is
where the guardrails live: the agent can propose any SQL it likes, but this
layer decides whether the SQL is acceptable.

Each tool has two parts:
  1. the Python function that runs
  2. the "schema" (name, description, parameters) that is sent to the model
     so it knows the tool exists and how to call it
"""
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "crm.db"
CATALOG_PATH = ROOT / "catalog" / "data_catalog.md"
BRAND_PATH = ROOT / "catalog" / "brand_rules.json"

TODAY = "2026-10-19"
MIN_SEGMENT_SIZE = 600
FATIGUE_DAYS = 7
MAX_ROWS_RETURNED = 30


# ---------------------------------------------------------------------------
# Read-only connection: the agent can NEVER write to the database.
# ---------------------------------------------------------------------------
def _ro_conn():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def _rw_conn():
    return sqlite3.connect(DB_PATH)


_WRITE_PATTERN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|pragma|replace|vacuum)\b", re.I)


def _check_select_only(sql: str):
    s = sql.strip().rstrip(";")
    if ";" in s:
        return "Only one SQL statement per call is allowed."
    if not re.match(r"^\s*(select|with)\b", s, re.I):
        return "Only SELECT or WITH queries are allowed."
    if _WRITE_PATTERN.search(s):
        return "The SQL contains a write keyword (INSERT/UPDATE/DROP...). Not allowed."
    return None


# ---------------------------------------------------------------------------
# Shared tools
# ---------------------------------------------------------------------------
def get_catalog(_state, **_):
    return CATALOG_PATH.read_text(encoding="utf-8")


def run_sql(_state, sql: str, **_):
    err = _check_select_only(sql)
    if err:
        return {"error": err}
    try:
        con = _ro_conn()
        cur = con.execute(sql.strip().rstrip(";"))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(MAX_ROWS_RETURNED + 1)
        con.close()
    except sqlite3.Error as e:
        return {"error": f"SQLite error: {e}"}
    truncated = len(rows) > MAX_ROWS_RETURNED
    return {"columns": cols, "rows": rows[:MAX_ROWS_RETURNED], "truncated": truncated}


# ---------------------------------------------------------------------------
# SEGMENTATION agent
# ---------------------------------------------------------------------------
def submit_segment(state, name: str, sql: str, rationale: str, **_):
    """
    The segmentation agent's 'contract'. It only finishes when this returns ok.
    Checks (all in code):
      - SELECT only
      - returns exactly the customer_id column
      - no duplicates
      - after the mandatory exclusions (consent + fatigue) it has >= 600
    """
    err = _check_select_only(sql)
    if err:
        return {"ok": False, "error": err}
    core = sql.strip().rstrip(";")
    con = _ro_conn()
    try:
        cur = con.execute(f"SELECT * FROM ({core}) LIMIT 1")
        cols = [d[0] for d in cur.description]
    except sqlite3.Error as e:
        con.close()
        return {"ok": False, "error": f"SQLite error: {e}"}
    if cols != ["customer_id"]:
        con.close()
        return {"ok": False, "error": f"The segment must return only the customer_id column. It returned: {cols}"}

    total, distinct = con.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT customer_id) FROM ({core})").fetchone()
    if total != distinct:
        con.close()
        return {"ok": False,
                "error": f"Duplicate customer_id: {total} rows but {distinct} distinct customers. "
                         "Probably a JOIN to rentals without aggregating. Use DISTINCT or GROUP BY."}

    # Mandatory exclusions: the agent does not write them, the code always applies them.
    final_sql = f"""
        SELECT s.customer_id
        FROM ({core}) s
        JOIN customers c ON c.customer_id = s.customer_id
        WHERE c.email_consent = 1
          AND s.customer_id NOT IN (
              SELECT customer_id FROM crm_sends
              WHERE julianday('{TODAY}') - julianday(sent_at) < {FATIGUE_DAYS})
    """
    after_consent = con.execute(
        f"SELECT COUNT(*) FROM ({core}) s JOIN customers c USING(customer_id) "
        f"WHERE c.email_consent = 1").fetchone()[0]
    final = con.execute(f"SELECT COUNT(*) FROM ({final_sql})").fetchone()[0]
    con.close()

    funnel = {"proposed": distinct, "after_consent": after_consent, "after_fatigue": final}
    min_size = state.get("min_size", MIN_SEGMENT_SIZE)
    if final < min_size:
        return {"ok": False, "funnel": funnel,
                "error": f"After exclusions {final} customers remain; the minimum is {min_size}. Widen the criteria."}

    state["segment"] = {"name": name, "agent_sql": core, "final_sql": final_sql,
                        "rationale": rationale, "funnel": funnel}
    return {"ok": True, "funnel": funnel, "message": "Segment accepted."}


# ---------------------------------------------------------------------------
# CONTENT agent
# ---------------------------------------------------------------------------
def get_segment_profile(state, **_):
    """Descriptive profile of the approved segment. Computed in SQL, not by the LLM."""
    seg = state.get("segment")
    if not seg:
        return {"error": "There is no approved segment."}
    con = _ro_conn()
    base = f"WITH seg AS ({seg['final_sql']})"

    def q(sql):
        return con.execute(base + sql).fetchall()

    size = q(" SELECT COUNT(*) FROM seg")[0][0]
    profile = {
        "size": size,
        "has_app_pct": round(q(" SELECT AVG(has_app)*100 FROM seg JOIN customers USING(customer_id)")[0][0], 1),
        "country_mix": q(" SELECT country, COUNT(*) n FROM seg JOIN customers USING(customer_id) GROUP BY 1 ORDER BY 2 DESC"),
        "last_vehicle_class": q(""" , last AS (
              SELECT r.customer_id, r.vehicle_class, r.branch_type,
                     ROW_NUMBER() OVER (PARTITION BY r.customer_id ORDER BY r.pickup_date DESC) rn
              FROM rentals r JOIN seg USING(customer_id))
            SELECT vehicle_class, COUNT(*) FROM last WHERE rn=1 GROUP BY 1 ORDER BY 2 DESC"""),
        "airport_share_pct": round(q(""" , last AS (
              SELECT r.customer_id, r.branch_type,
                     ROW_NUMBER() OVER (PARTITION BY r.customer_id ORDER BY r.pickup_date DESC) rn
              FROM rentals r JOIN seg USING(customer_id))
            SELECT AVG(branch_type='airport')*100 FROM last WHERE rn=1""")[0][0], 1),
        "booking_channel": q(" SELECT booking_channel, COUNT(*) FROM rentals JOIN seg USING(customer_id) GROUP BY 1 ORDER BY 2 DESC"),
    }
    con.close()
    return profile


def get_brand_rules(_state, **_):
    return json.loads(BRAND_PATH.read_text(encoding="utf-8"))


def _lint_variant(v, rules):
    problems = []
    for f in rules["required_fields"]:
        if not str(v.get(f, "")).strip():
            problems.append(f"missing field: {f}")
    subject, pre, body = v.get("subject", ""), v.get("preheader", ""), v.get("body", "")
    if len(subject) > rules["max_subject_chars"]:
        problems.append(f"subject has {len(subject)} characters (max {rules['max_subject_chars']})")
    if len(pre) > rules["max_preheader_chars"]:
        problems.append(f"preheader has {len(pre)} characters (max {rules['max_preheader_chars']})")
    if len(body.split()) > rules["max_body_words"]:
        problems.append(f"body has {len(body.split())} words (max {rules['max_body_words']})")
    text = " ".join([subject, pre, body, v.get("cta_label", "")]).lower()
    for term in rules["forbidden_terms"]:
        if term.lower() in text:
            problems.append(f"forbidden term: '{term}'")
    for tok in re.findall(r"\{\{[^}]+\}\}", " ".join([subject, pre, body])):
        if tok not in rules["allowed_tokens"]:
            problems.append(f"unknown personalisation token: {tok}")
    for pct in re.findall(r"(\d+)\s*%", text):
        if int(pct) > rules["max_discount_pct"]:
            problems.append(f"discount of {pct}% above the maximum of {rules['max_discount_pct']}%")
    return problems


def check_copy(_state, variant: dict, **_):
    rules = get_brand_rules(None)
    problems = _lint_variant(variant, rules)
    return {"ok": not problems, "problems": problems}


def submit_variants(state, variants: list, **_):
    rules = get_brand_rules(None)
    if state.get("ab_test", True) is False:
        if len(variants) != 1:
            return {"ok": False, "error": "This campaign has no A/B test (small segment). Submit exactly 1 variant."}
    elif not (rules["min_variants"] <= len(variants) <= rules["max_variants"]):
        return {"ok": False, "error": f"Between {rules['min_variants']} and {rules['max_variants']} variants are required."}
    report = {v.get("variant", f"#{i}"): _lint_variant(v, rules) for i, v in enumerate(variants)}
    failing = {k: p for k, p in report.items() if p}
    if failing:
        return {"ok": False, "error": "Some variants fail the brand rules.", "problems": failing}
    state["variants"] = variants
    return {"ok": True, "message": f"{len(variants)} variants accepted."}


# ---------------------------------------------------------------------------
# Schemas sent to the model
# ---------------------------------------------------------------------------
TOOLS = {
    "get_catalog": {
        "fn": get_catalog,
        "schema": {"name": "get_catalog",
                   "description": "Returns the data catalogue (tables, columns, rules). Read this before writing SQL.",
                   "input_schema": {"type": "object", "properties": {}}},
    },
    "run_sql": {
        "fn": run_sql,
        "schema": {"name": "run_sql",
                   "description": "Runs a read-only SELECT on SQLite and returns up to 30 rows. Use it to explore and count.",
                   "input_schema": {"type": "object",
                                    "properties": {"sql": {"type": "string"}},
                                    "required": ["sql"]}},
    },
    "submit_segment": {
        "fn": submit_segment,
        "schema": {"name": "submit_segment",
                   "description": ("Submits the final segment definition. The SQL must return only customer_id, with no duplicates. "
                                   "The system applies consent and fatigue and checks the minimum size. "
                                   "If it returns ok=false, fix it and submit again."),
                   "input_schema": {"type": "object",
                                    "properties": {"name": {"type": "string"},
                                                   "sql": {"type": "string"},
                                                   "rationale": {"type": "string",
                                                                 "description": "Why this criterion serves the objective, in 2-3 sentences."}},
                                    "required": ["name", "sql", "rationale"]}},
    },
    "get_segment_profile": {
        "fn": get_segment_profile,
        "schema": {"name": "get_segment_profile",
                   "description": "Profile of the approved segment: size, % with app, countries, last vehicle class, % airport.",
                   "input_schema": {"type": "object", "properties": {}}},
    },
    "get_brand_rules": {
        "fn": get_brand_rules,
        "schema": {"name": "get_brand_rules",
                   "description": "Brand and compliance rules for the copy.",
                   "input_schema": {"type": "object", "properties": {}}},
    },
    "check_copy": {
        "fn": check_copy,
        "schema": {"name": "check_copy",
                   "description": "Checks ONE variant against the brand rules before submitting.",
                   "input_schema": {"type": "object",
                                    "properties": {"variant": {"type": "object"}},
                                    "required": ["variant"]}},
    },
    "submit_variants": {
        "fn": submit_variants,
        "schema": {"name": "submit_variants",
                   "description": ("Submits 2-3 final variants. Each one: variant (A/B/C), hypothesis, subject, preheader, "
                                   "body, cta_label. Allowed tokens: {{first_name}}, {{last_city}}, {{last_vehicle_class}}."),
                   "input_schema": {"type": "object",
                                    "properties": {"variants": {"type": "array", "items": {"type": "object"}}},
                                    "required": ["variants"]}},
    },
}


def toolset(names):
    return {n: TOOLS[n] for n in names}
