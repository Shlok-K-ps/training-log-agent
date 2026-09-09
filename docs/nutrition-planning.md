# Food-access nutrition and supplement scheduling

The WhatsApp parser can capture an athlete's declared diet style, allergies,
cooking access, foods they can regularly obtain, meals per day, and existing
protein or calorie targets. The deterministic planner then chooses only from
those foods and places meals around the recorded training time.

Example setup:

> Vegetarian. I can get rice, dal, paneer and bananas. I have basic cooking
> access, eat four times per day, and my dietitian set 150 g protein.

Example supplement setup:

> Creatine 5 g after training, approved by my coach, batch-tested product.

The resulting morning WhatsApp plan includes ordinary meals, a pre-training
meal two hours before the session, a post-training meal one hour afterward, and
timing for already-approved supplements. It does not calculate portions or
invent targets.

Safety boundaries:

1. Meal choices must come from the athlete's recorded food access.
2. Diet-style conflicts and recorded allergens are excluded.
3. `cooking_access=none` removes foods that require preparation.
4. A training-day plan needs at least one compatible protein and carbohydrate
   option; otherwise the assistant asks for more available foods.
5. Calorie and protein targets are recorded only when explicitly supplied.
6. A supplement requires an exact athlete-reported dose and timing.
7. A supplement without a named approval source may be stored but is not put on
   the schedule.
8. The system never diagnoses a deficiency, prescribes a medical diet, or
   recommends starting a supplement.
9. Products recorded as not batch-tested produce an anti-doping warning.

Supporting references:

- NIH exercise and athletic-performance supplement fact sheet:
  https://ods.od.nih.gov/factsheets/ExerciseAndAthleticPerformance-HealthProfessional/
- 2026 WADA Prohibited List:
  https://www.wada-ama.org/sites/default/files/2025-09/2026list_en_final_clean_september_2025.pdf
- Sport Integrity Australia supplement risk guidance:
  https://www.sportintegrity.gov.au/what-we-do/anti-doping/substances/supplements-sport
- ISSN protein position stand:
  https://link.springer.com/article/10.1186/s12970-017-0177-8

The food catalog is intentionally small and explicit. Unsupported foods are not
silently classified by the language model. Expanding the catalog should add
tests for diet compatibility, allergen handling, cooking access and meal role.
