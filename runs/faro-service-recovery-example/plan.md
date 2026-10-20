# Campaign plan (for approval)

**Segment:** faro_airport_low_rating_7d

**Rationale:** Customers who rated a rental at Faro airport 1 or 2 in the last 7 days. Small by nature: this is a recovery action, not a growth one, so I did not widen the criteria.

**Agent's SQL:**

```sql
SELECT DISTINCT rr.customer_id
FROM rental_ratings rr
JOIN rentals r ON r.rental_id = rr.rental_id
WHERE r.branch_city = 'Faro' AND r.branch_type = 'airport'
  AND rr.score <= 2
  AND julianday(date('2026-10-19')) - julianday(rr.rated_at) <= 7
```

**Funnel:** {'proposed': 10, 'after_consent': 7, 'after_fatigue': 6}

**Groups:** A=6

## Variants

### A  
*Hypothesis:* A specific apology naming the problem rebuilds trust better than a generic one.

- Subject: We kept you waiting in Faro. We are sorry.
- Preheader: Here is what we changed, and a small thank-you.
- CTA: See my offer

> Hi {{first_name}}, your last pickup at Faro airport took far longer than it should have. We have added staff at the counter for the coming weeks, and you can now skip the queue by checking in through the app. As a thank-you for your patience, 10% of your next rental is on us.
