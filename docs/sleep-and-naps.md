# Proactive sleep check-ins and nap scheduling

Athletes can configure their IANA timezone, morning check-in time, usual
training time, bedtime, and acceptable nap window through WhatsApp. When
`ENABLE_MORNING_SCHEDULER=true`, the service checks every minute and sends one
morning prompt during a two-hour catch-up window. A delivery ledger prevents a
restart or second process from sending the same athlete the prompt twice that
day.

Example configuration message:

> Timezone Asia/Kolkata. Morning check-in at 07:30, train at 18:30, bedtime
> 22:30, nap window 13:00–15:00.

The morning reply records sleep hours and quality, readiness, soreness, stress,
and today's planned lift/time. A deterministic rule may then offer:

- no nap when sleep is at least seven hours and readiness is not low;
- a 30-minute opportunity after moderate sleep loss;
- a 45-minute opportunity below six hours;
- no exact start time when the configured window cannot leave at least one hour
  between waking and training.

These durations and cutoffs are visible product policy, not medical rules. The
broad rationale comes from athlete-napping reviews, including:

- https://pubmed.ncbi.nlm.nih.gov/36690376/
- https://pubmed.ncbi.nlm.nih.gov/34559915/
- https://aasm.org/resources/pdf/pressroom/adult-sleep-duration-consensus.pdf

After a completed nap, the athlete reports minutes actually slept and an
explicit readiness score. The stored post-nap row carries forward the original
night's sleep, so the nap cannot erase a severe sleep flag. If today's lift was
provided in the morning, the router automatically recalculates its prescription.

Safety invariants:

1. Planning a nap never counts as completing it.
2. A nap never directly adds readiness points.
3. Original sleep hours remain in the same-day calculation.
4. The adjusted load never exceeds the deterministic base prescription.
5. An open injury flag and severe recovery flags still suppress load advice.
6. Repeated sleep problems require qualified support; the feature does not
   diagnose or treat a sleep disorder.

The scheduler runs inside the web service for this small deployment. A larger
multi-instance product should move scheduled delivery to a durable job queue
while retaining the database idempotency key.
