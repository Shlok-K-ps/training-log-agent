# Programming methodologies

These are five representative, widely used systems, not a universal ranking.
Together they cover the main decisions a workout assistant must model: how often
load can rise, whether work is organized in waves or blocks, whether daily
effort changes the load, and whether exercise variations rotate.

| Strategy | Best fit | Structure retained | Required before exact loads |
|---|---|---|---|
| Novice linear progression | Novices recovering between sessions | A/B sessions; increase after completed work | Last successful load, completed reps, increment |
| 5/3/1-style training-max progression | Simple, conservative long-term progress | Multi-week waves around a submaximal training max | Coach-approved training max and cycle week |
| Block periodization | Intermediate/advanced lifters with a dated meet | Accumulation → intensification → realization → deload | Meet date, current block, verified baseline |
| RPE autoregulation | Experienced lifters with consistent effort data | RPE-capped top work and fatigue-managed back-offs | Target reps/RPE and reliable recent RPE history |
| Conjugate | Advanced four-day lifters with coached variations | Max, dynamic, and repeated effort with planned rotation | Day slot, approved variations, equipment |

## Deterministic selection policy

An explicit athlete or coach choice wins. Otherwise, the pure-Python selector
uses this order:

1. An open injury flag suppresses programming.
2. A novice gets linear progression.
3. A non-novice with a meet inside 16 weeks gets block periodization.
4. An advanced four-day lifter with specialty equipment gets conjugate.
5. A lifter with RPE on at least 60% of recent work gets RPE autoregulation.
6. Everyone else gets conservative training-max progression as the fallback.

The 16-week and 60% cutoffs are product/coaching policy, not conclusions from
the sources. They are named and tested so a coach can change them deliberately.

## Sources

- [Starting Strength novice program](https://startingstrength.com/get-started/programs)
- [Jim Wendler's beginner 5/3/1 guidance](https://www.jimwendler.com/blogs/jimwendler-com/101065094-5-3-1-for-a-beginner)
- [Juggernaut Training Systems' periodization definitions](https://www.jtsstrength.com/the-terms-of-the-deal/)
- [Reactive Training Systems manual](https://store.reactivetrainingsystems.com/products/rts-manual-digital)
- [Westside Barbell's conjugate overview](https://www.westside-barbell.com/pages/conjugate-method)
- [2022 periodization systematic review](https://pubmed.ncbi.nlm.nih.gov/35044672/)
- [2025 autoregulation systematic review](https://pubmed.ncbi.nlm.nih.gov/40791980/)

These sources support the broad structures, not a claim that one method is
universally best.

## Boundaries

- The model may extract experience, schedule, meet date, equipment, and RPE. It
  does not select the method or phrase a session.
- A random logged top set is never silently promoted to a 1RM or training max.
- OpenPowerlifting meet data remains plausibility evidence only.
- Injury flags suppress programming; no rehab protocol is generated.
- `app/programming/` has no model, database, clock, or network dependency.

The implementation chooses a method and returns a deterministic session
structure. Exact loads are gated on capturing and validating the required
inputs listed above.
