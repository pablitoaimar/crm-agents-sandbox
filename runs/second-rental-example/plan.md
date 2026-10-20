# Campaign plan (for approval)

**Segment:** first_rental_30_180d

**Rationale:** Customers with a single rental returned 30-180 days ago. I widened from 90 to 180 days and included people who already have the app, because the no-app 90-day slice gave 340 after exclusions, not enough to test. App adoption is now handled in the content, not in the filter.

**Agent's SQL:**

```sql
SELECT r.customer_id
FROM rentals r
WHERE r.customer_id IN (SELECT customer_id FROM rentals GROUP BY customer_id HAVING COUNT(*) = 1)
  AND julianday(date('2026-10-19')) - julianday(r.return_date) BETWEEN 30 AND 180
```

**Funnel:** {'proposed': 1819, 'after_consent': 1287, 'after_fatigue': 1229}

**Groups:** A=369, B=369, C=369, HOLDOUT=122

## Variants

### A  
*Hypothesis:* Baseline: a plain brand reminder with no incentive or personalisation.

- Subject: Ready for your next trip, {{first_name}}?
- Preheader: Your next car is a few taps away.
- CTA: Plan my next trip

> Hi {{first_name}}, thanks for travelling with us. Wherever you are heading next, we have a car ready at branches across Europe. Pick it up at the airport or in town, and get on the road in minutes.

### B  
*Hypothesis:* Referencing the last city and car class makes the message feel relevant and lifts conversion.

- Subject: {{first_name}}, back to {{last_city}} soon?
- Preheader: Your {{last_vehicle_class}} is ready when you are.
- CTA: Book my next car

> Hi {{first_name}}, last time you picked up a {{last_vehicle_class}} in {{last_city}}. Heading back, or somewhere new? Book in under a minute and pick up right where you left off.

### C  
*Hypothesis:* An app-only incentive drives the second rental and app adoption.

- Subject: 10% off your second trip, in the app
- Preheader: Book your next rental in our app and save.
- CTA: Get the app

> Hi {{first_name}}, your next trip deserves a head start. Book your second rental in our app and save 10%. Manage your booking, skip the counter and unlock your car from your phone.
