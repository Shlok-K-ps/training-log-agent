# Readiness, sleep, and nutrition

The daily check-in connects recovery context to training without turning the
language model into a coach. Athletes may report sleep duration and quality,
readiness, soreness, stress, bodyweight, protein, calories, and adherence to an
existing nutrition plan. The model extracts only explicit values; Python stores,
scores, and formats them.

## Evidence-backed guardrails

- The [American Academy of Sleep Medicine and Sleep Research Society consensus](https://www.aasm.org/resources/pdf/adultsleepdurationconsensus.pdf)
  recommends at least seven hours of sleep per night for healthy adults. The
  system uses seven hours as a visible recovery flag, not as a diagnosis.
- The [IOC REDs consensus](https://pubmed.ncbi.nlm.nih.gov/37752011/) describes
  the health and performance risks of problematic low energy availability and
  recognizes longitudinal performance tracking and subjective readiness as
  useful field information. The system therefore tracks trends but does not
  infer energy availability from a single calorie entry.
- The [ISSN protein position stand](https://link.springer.com/article/10.1186/s12970-017-0177-8)
  gives a general range of 1.4–2.0 g/kg/day for most exercising people. The
  check-in reports where an entered value sits relative to that broad range; it
  does not prescribe a diet or assess medical suitability.
- Reviews of [autoregulation](https://pubmed.ncbi.nlm.nih.gov/32813181/) describe
  it as a feedback process based on measured performance or perceived capacity.
  The implementation uses the check-in only to hold, reduce, or suppress load.

## Product policy—not clinical evidence

The 100-point readiness score and its penalties are an explicit, coach-tunable
policy. They are not a validated medical questionnaire. The current bands are:

| Score / condition | Result |
|---|---|
| 75–100 | Hold planned load at 100% |
| 60–74 | Reduce to 97.5% |
| 45–59 | Reduce to 95% |
| Under 45, sleep under 4h, readiness ≤2, or soreness ≥9 | Suppress the load-bearing prescription |

Three invariants matter more than the exact cutoffs:

1. Readiness can never increase load.
2. Only a same-day check-in can modify today's prescription.
3. An open injury flag overrides everything and suppresses programming.

## Nutrition boundary

Calories, protein, bodyweight and adherence are tracked together so trends can
later be reviewed by the athlete, coach, or dietitian. The system does not set a
calorie deficit, diagnose REDs, recommend supplements, or create medical diets.
Those require athlete-specific context and qualified oversight. A calorie entry
without an agreed target is recorded but not judged.
