# Data catalogue (CRM sandbox)

This file is what the agents read to know which data exists.
In a real CRM team this is the "CRM data catalogue". The better the descriptions here, the better the SQL the agent writes.

Engine: **SQLite**. Dates are text `YYYY-MM-DD`. Use `date('2026-10-19')` as "today" (the data is synthetic and frozen on that date).

## customers (1 row per customer)
| column | type | meaning |
|---|---|---|
| customer_id | int | key |
| first_name | text | first name, used for personalisation |
| signup_date | text | sign-up date |
| country | text | PT, DE, ES, FR, UK |
| preferred_lang | text | pt, de, es, fr, en |
| age_band | text | 18-24, 25-34, 35-49, 50-64, 65+ |
| loyalty_tier | text | none, gold, platinum |
| has_app | int | 1 = has the app installed and logged in |
| email_consent | int | 1 = accepted marketing email. **Required for email.** |
| push_consent | int | 1 = accepted push. **Required for push.** |

## rentals (1 row per rental)
| column | type | meaning |
|---|---|---|
| rental_id | int | key |
| customer_id | int | FK to customers |
| pickup_date / return_date | text | start and end of the rental |
| branch_city | text | city of the pickup branch |
| branch_type | text | airport, city |
| vehicle_class | text | economy, compact, suv, premium, van |
| booking_channel | text | web, app, partner |
| revenue_eur | real | rental revenue |

Notes:
- "First-rental customer" = exactly 1 row in `rentals`.
- A customer can have 0 rentals (signed up and never rented).

## app_events
| column | type | meaning |
|---|---|---|
| customer_id | int | FK |
| event_date | text | event date |
| event_type | text | install, login, search, booking_start |

## rental_ratings (post-rental rating, last 60 days)
| column | type | meaning |
|---|---|---|
| rental_id | int | FK to rentals |
| customer_id | int | FK to customers |
| rated_at | text | rating date |
| score | int | 1 to 5. Low rating = score <= 2 |
| topic | text | car_condition, waiting_time, price, staff, pickup_process |

## crm_sends (communication history)
| column | type | meaning |
|---|---|---|
| campaign_id | text | campaign |
| customer_id | int | recipient |
| variant | text | A, B, C... or HOLDOUT (control group that received nothing) |
| channel | text | email, push |
| sent_at | text | send date |
| opened / clicked / converted | int | 0/1. converted = booking within the next 14 days |

## Business rules (applied by the code, not by the agent)
- No consent, no send. The pipeline automatically removes anyone without `email_consent = 1`.
- Fatigue: anyone who received a communication in the last 7 days is removed.
- A segment must return **one `customer_id` column, with no duplicates**.
- Minimum size for A/B: 600 customers after exclusions.
