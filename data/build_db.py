"""
Builds a SQLite database with SYNTHETIC data for a car rental company.
None of this is real. It gives the agents something to work on.

Usage:   python data/build_db.py
Creates: data/crm.db
"""
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

SEED = 42
TODAY = date(2026, 10, 19)  # "today" for the simulation
N_CUSTOMERS = 15000

DB_PATH = Path(__file__).parent / "crm.db"

CITIES = {
    # city: (country, weight)
    "Lisbon": ("PT", 14), "Porto": ("PT", 7), "Faro": ("PT", 6),
    "Munich": ("DE", 12), "Berlin": ("DE", 9), "Frankfurt": ("DE", 7),
    "Madrid": ("ES", 9), "Barcelona": ("ES", 9), "Malaga": ("ES", 5),
    "Paris": ("FR", 8), "Nice": ("FR", 4),
    "London": ("UK", 10),
}
VEHICLE = {"economy": 30, "compact": 28, "suv": 20, "premium": 14, "van": 8}
PRICE = {"economy": 38, "compact": 49, "suv": 72, "premium": 115, "van": 85}
LANG = {"PT": "pt", "DE": "de", "ES": "es", "FR": "fr", "UK": "en"}

SCHEMA = """
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS rentals;
DROP TABLE IF EXISTS app_events;
DROP TABLE IF EXISTS campaigns;
DROP TABLE IF EXISTS crm_sends;
DROP TABLE IF EXISTS rental_ratings;

CREATE TABLE rental_ratings (
    rental_id       INTEGER REFERENCES rentals(rental_id),
    customer_id     INTEGER REFERENCES customers(customer_id),
    rated_at        TEXT,
    score           INTEGER,   -- 1 to 5
    topic           TEXT       -- car_condition, waiting_time, price, staff, pickup_process
);

CREATE TABLE customers (
    customer_id     INTEGER PRIMARY KEY,
    first_name      TEXT,
    signup_date     TEXT,      -- YYYY-MM-DD
    country         TEXT,      -- PT, DE, ES, FR, UK
    preferred_lang  TEXT,      -- pt, de, es, fr, en
    age_band        TEXT,      -- 18-24, 25-34, 35-49, 50-64, 65+
    loyalty_tier    TEXT,      -- none, gold, platinum
    has_app         INTEGER,   -- 1 = app installed and logged in
    email_consent   INTEGER,   -- 1 = may receive marketing email
    push_consent    INTEGER    -- 1 = may receive push
);

CREATE TABLE rentals (
    rental_id       INTEGER PRIMARY KEY,
    customer_id     INTEGER REFERENCES customers(customer_id),
    pickup_date     TEXT,
    return_date     TEXT,
    branch_city     TEXT,
    branch_type     TEXT,      -- airport, city
    vehicle_class   TEXT,      -- economy, compact, suv, premium, van
    booking_channel TEXT,      -- web, app, partner
    revenue_eur     REAL
);

CREATE TABLE app_events (
    customer_id     INTEGER REFERENCES customers(customer_id),
    event_date      TEXT,
    event_type      TEXT       -- install, login, search, booking_start
);

CREATE TABLE campaigns (
    campaign_id     TEXT PRIMARY KEY,
    name            TEXT,
    objective       TEXT,
    created_at      TEXT,
    status          TEXT       -- draft, approved, sent, evaluated
);

CREATE TABLE crm_sends (
    send_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id     TEXT,
    customer_id     INTEGER,
    variant         TEXT,      -- A, B, C ... or HOLDOUT
    channel         TEXT,      -- email, push
    sent_at         TEXT,
    opened          INTEGER,
    clicked         INTEGER,
    converted       INTEGER    -- booked within the next 14 days
);

CREATE INDEX ix_rentals_customer ON rentals(customer_id);
CREATE INDEX ix_sends_customer   ON crm_sends(customer_id, sent_at);
CREATE INDEX ix_app_customer     ON app_events(customer_id);
"""

FIRST_NAMES = {
    "pt": ["Joao", "Ana", "Rui", "Ines", "Miguel", "Sofia", "Pedro", "Marta"],
    "de": ["Lukas", "Anna", "Jonas", "Lea", "Felix", "Mia", "Paul", "Laura"],
    "es": ["Pablo", "Lucia", "Javier", "Carmen", "Diego", "Elena", "Sergio", "Marta"],
    "fr": ["Louis", "Chloe", "Hugo", "Camille", "Lucas", "Manon", "Theo", "Julie"],
    "en": ["James", "Emily", "Oliver", "Sophie", "Harry", "Grace", "Jack", "Amelia"],
}


def wpick(rng, d):
    keys = list(d)
    weights = [d[k] if not isinstance(d[k], tuple) else d[k][1] for k in keys]
    return rng.choices(keys, weights=weights)[0]


def main():
    rng = random.Random(SEED)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)

    customers, rentals, events, sends = [], [], [], []
    rental_id = 1

    for cid in range(1, N_CUSTOMERS + 1):
        home_city = wpick(rng, CITIES)
        country = CITIES[home_city][0]
        lang = LANG[country]
        signup = TODAY - timedelta(days=rng.randint(20, 3 * 365))
        has_app = 1 if rng.random() < 0.38 else 0
        tier = rng.choices(["none", "gold", "platinum"], [80, 16, 4])[0]
        customers.append((
            cid, rng.choice(FIRST_NAMES[lang]), signup.isoformat(), country, lang,
            rng.choices(["18-24", "25-34", "35-49", "50-64", "65+"], [10, 30, 32, 20, 8])[0],
            tier, has_app,
            1 if rng.random() < 0.72 else 0,
            1 if (has_app and rng.random() < 0.55) else 0,
        ))

        # number of rentals: many customers rent only once
        n_rent = rng.choices([0, 1, 2, 3, 5, 8], [6, 46, 20, 13, 10, 5])[0]
        if tier != "none":
            n_rent = max(n_rent, 3)
        days_available = (TODAY - signup).days
        for _ in range(n_rent):
            start = signup + timedelta(days=rng.randint(0, max(days_available - 3, 1)))
            length = rng.choice([1, 2, 3, 3, 4, 5, 7, 7, 10, 14])
            vclass = wpick(rng, VEHICLE)
            # often travels outside the home city
            city = home_city if rng.random() < 0.45 else wpick(rng, CITIES)
            btype = "airport" if rng.random() < 0.6 else "city"
            channel = rng.choices(["web", "app", "partner"], [55, 30 if has_app else 2, 15])[0]
            revenue = round(PRICE[vclass] * length * rng.uniform(0.8, 1.25), 2)
            rentals.append((rental_id, cid, start.isoformat(),
                            (start + timedelta(days=length)).isoformat(),
                            city, btype, vclass, channel, revenue))
            rental_id += 1

        if has_app:
            inst = signup + timedelta(days=rng.randint(0, 60))
            if inst <= TODAY:
                events.append((cid, inst.isoformat(), "install"))
                for _ in range(rng.randint(0, 12)):
                    d = inst + timedelta(days=rng.randint(0, max((TODAY - inst).days, 1)))
                    events.append((cid, d.isoformat(), rng.choice(["login", "login", "search", "booking_start"])))

    # CRM send history for the last 30 days (for the fatigue rule)
    con.execute("INSERT INTO campaigns VALUES ('CMP-2026-091','Autumn city breaks','engagement','2026-10-01','sent')")
    con.execute("INSERT INTO campaigns VALUES ('CMP-2026-094','Gold upgrade reminder','loyalty','2026-10-08','sent')")
    for c in customers:
        cid, email_consent = c[0], c[8]
        if email_consent and rng.random() < 0.25:
            sent = TODAY - timedelta(days=rng.randint(1, 30))
            camp = "CMP-2026-091" if sent < date(2026, 10, 8) else "CMP-2026-094"
            opened = 1 if rng.random() < 0.32 else 0
            clicked = 1 if opened and rng.random() < 0.18 else 0
            converted = 1 if clicked and rng.random() < 0.2 else 0
            sends.append((camp, cid, "A", "email", sent.isoformat(), opened, clicked, converted))

    con.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?,?)", customers)
    con.executemany("INSERT INTO rentals VALUES (?,?,?,?,?,?,?,?,?)", rentals)
    con.executemany("INSERT INTO app_events VALUES (?,?,?)", events)
    con.executemany(
        "INSERT INTO crm_sends (campaign_id, customer_id, variant, channel, sent_at, opened, clicked, converted) "
        "VALUES (?,?,?,?,?,?,?,?)", sends)
    # post-rental ratings (last 60 days). Incident planted on purpose:
    # Faro airport, last 7 days, many low ratings because of waiting time.
    ratings = []
    normal_w = [4, 6, 15, 35, 40]
    incident_w = [32, 26, 18, 14, 10]
    topics = ["car_condition", "waiting_time", "price", "staff", "pickup_process"]
    for r in rentals:
        rid, cid, _, ret, city, btype = r[0], r[1], r[2], r[3], r[4], r[5]
        ret_d = date.fromisoformat(ret)
        age = (TODAY - ret_d).days
        if not (0 <= age <= 60) or rng.random() > 0.6:
            continue
        incident = city == "Faro" and btype == "airport" and age <= 7
        score = rng.choices([1, 2, 3, 4, 5], incident_w if incident else normal_w)[0]
        topic = "waiting_time" if incident and score <= 2 and rng.random() < 0.8 else rng.choice(topics)
        ratings.append((rid, cid, (ret_d + timedelta(days=rng.randint(0, 2))).isoformat(), score, topic))
    con.executemany("INSERT INTO rental_ratings VALUES (?,?,?,?,?)", ratings)
    con.commit()

    for t in ["customers", "rentals", "app_events", "crm_sends", "rental_ratings"]:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"{t:<12} {n:>7} rows")
    con.close()
    print(f"OK -> {DB_PATH}")


if __name__ == "__main__":
    main()
