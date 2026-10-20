# Results

| group | n | open % | click % | conversion % | lift vs holdout | p-value |
|---|---|---|---|---|---|---|
| HOLDOUT | 122 | - | - | 4.92 | - | - |
| A | 369 | 31.4 | 7.3 | 4.61 | -6% | 0.888 |
| B | 369 | 33.9 | 5.7 | 5.42 | +10% | 0.830 |
| C | 369 | 32.0 | 5.1 | 4.61 | -6% | 0.888 |

**Best variant:** B (p-value vs holdout = 0.830).

**Statistical power:** to detect a 30% relative lift on a base rate of 4.9% you would need ~3843 customers per group. This test has ~369 per group.

Conclusion: **inconclusive**. Do not declare a winner. Options: accumulate more sends (continuous test), fewer variants, or a goal with a higher base rate (e.g. clicks).

*These results come from a simulated send (src/pipeline.py -> _true_uplift).*