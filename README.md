# Training-Log Agent

A WhatsApp agent for a 20-athlete powerlifting team. Athletes text their sessions
in plain English. The agent parses them into structured data, tracks training,
sleep, readiness, soreness, stress, bodyweight and nutrition, then returns a
deterministic verdict or next-session plan.

Athletes can also configure a local morning check-in time. The service sends a
proactive WhatsApp sleep prompt, proposes a bounded nap window when recovery is
low, asks for a post-nap readiness update, and recalculates the day's planned
lift without ever exceeding the original base load.

The same morning flow can build a food-access plan around training. It uses only
the athlete's recorded diet style, allergies, cooking access and available
foods. Supplements are scheduled only when an exact dose and approval source
have been recorded; the model cannot recommend one or invent a dose.

```
athlete                                                        agent
   │
   │  "squat 3x5 at 140 today, felt way harder than tuesday, rpe 9"
   ├──────────────────────────────────────────────────────────────▶
   │                                                    ✅ Logged: Squat 3x5 @ 140 kg RPE 9
   │                                                    *Squat — Stalled*
   │                                                    Flat at 140 kg for 2 sessions with
   │                                                    RPE climbing — same bar, more effort.
   ◀──────────────────────────────────────────────────────────────┤
```

---

## The architecture

Three layers, and the split is the whole point.

```
   WhatsApp ──▶ Twilio ──▶ POST /webhook/whatsapp
                                   │
   ┌───────────────────────────────┼───────────────────────────────┐
   │                               ▼                               │
   │  LAYER 1   app/agent/      Gemini Flash, function calling.    │
   │  parse     ───────────     Messy English ──▶ arguments        │
   │                            matching a schema. Validated and   │
   │                            range-checked before storage.      │
   │                                   │                           │
   │                                   ▼                           │
   │  LAYER 2   app/storage/    SQLite. One file, one table.       │
   │  store     ────────────    athlete, lift, sets, reps, weight, │
   │                            RPE, date, phase, injury flag.     │
   │                                   │                           │
   │                                   ▼                           │
   │  LAYER 3   app/decision/   Plain Python. Compares against     │
   │  decide    ─────────────   this athlete's history and returns │
   │                            the verdict. No model. No API call.│
   │                            No randomness.                     │
   └───────────────────────────────┼───────────────────────────────┘
                                   ▼
                        templated reply ──▶ WhatsApp
```

**Why the split:** messy input needs a model, but the output is advice real
athletes act on, so it must be identical on every run and provable. A language
model is the right tool for reading "ground out the last two at one forty" and
the wrong tool for deciding whether someone should strip 15% off their squat.

The model never sees the reply text. It cannot write one. Its entire vocabulary
is thirteen function schemas in [`app/agent/schemas.py`](app/agent/schemas.py), and
anything it returns outside them is thrown away before it reaches the database.

The same boundary now covers coaching. [`app/programming/`](app/programming/)
selects one of five programming strategies from explicit profile facts, while
[`app/decision/readiness.py`](app/decision/readiness.py) and
[`app/decision/prescribe.py`](app/decision/prescribe.py) connect same-day
recovery data to the next session. The model extracts facts; it never chooses a
method, calculates a readiness score, invents a working max, or phrases advice.

See [programming methodologies](docs/programming-methodologies.md) and
[readiness and nutrition](docs/readiness-and-nutrition.md) for the research,
policy cutoffs, and safety boundaries.
The proactive workflow and nap rules are documented in
[sleep and nap scheduling](docs/sleep-and-naps.md).
Food access, meal timing and supplement boundaries are in
[nutrition planning](docs/nutrition-planning.md).

---

## The rules

Every one of these lives in [`app/decision/rules.py`](app/decision/rules.py) as
plain Python, and every one has a test in
[`tests/test_rules.py`](tests/test_rules.py).

| Condition | Verdict |
|---|---|
| Top set up vs. last session | `PROGRESSING` |
| Top set down vs. last session | `REGRESSED` — a backoff, not a stall |
| Flat for 3+ sessions | `STALLED` |
| Flat for 2+ sessions **with RPE climbing** | `STALLED` — one session earlier |
| Flat during a **cut** | `HOLDING` — not a stall |
| 2nd stall episode on the same lift | `DELOAD` to 85%, rounded to 2.5 kg |
| Open **injury flag** | verdict still tracked, all load advice suppressed |

Two of these are worth saying out loud.

**RPE.** Same weight, same reps, at RPE 7 then 8 then 9 is not a plateau — it is
a slide. The bar says nothing changed; the athlete says it got harder. The
numbers alone miss it, so the rule triggers a session early when effort is
climbing.

**Phase.** Flat weight in a cut is holding, not stalling. Same data, different
meaning. Without the phase flag the agent would tell every athlete on a cut that
they had failed, which is the opposite of true.

---

## Where the numbers come from

Validation bounds are derived from real competition results, not invented.
[`reference/openpowerlifting_top_lifters.csv`](reference/openpowerlifting_top_lifters.csv)
holds the top ~115 lifters of all time by Dots (Raw+Wraps) from
[openpowerlifting.org](https://www.openpowerlifting.org/); the constants live in
[`app/reference.py`](app/reference.py) and
[`tests/test_reference.py`](tests/test_reference.py) recomputes every one of them
from that file on each run, so a constant cannot quietly drift away from its
evidence.

| Derived from the data | Value |
|---|---|
| Heaviest squat in the sample | 500.0 kg |
| Heaviest bench | 292.6 kg |
| Heaviest deadlift | 492.5 kg |
| bench ÷ squat, elite range | 0.38 – 0.76 |
| deadlift ÷ squat, elite range | 0.79 – 1.41 |

**Why this matters.** The validator's job is not to reject impossible lifts —
nobody texts their coach a 900 kg bench. Its job is to catch **parse errors**:
"one forty" landing as 14, a rep count read as a weight, pounds read as kilos. A
single global 600 kg cap catches almost none of them, because it sits far above
every real lift for every movement. Per-lift ceilings are twice as tight on the
bench, and three checks now run in increasing order of how much they know about
the athlete:

1. **Ceiling** — above anything ever lifted. Rejected before storage.
2. **Ratio** — against the athlete's own best squat. A 180 kg bench from someone
   who squats 140 is almost always two numbers swapped in one message.
3. **History** — against their own last session. The sharpest of the three,
   because 140 kg is suspicious for a 100 kg squatter and routine for a 200 kg
   one, and no global constant can tell those apart.

Checks 2 and 3 **never reject**. The row is stored, a flag is attached, and the
reply asks. Dropping a real session to guard against a possible typo is the worse
failure: the athlete loses data they cannot recover and stops trusting the log,
whereas a wrong number they were asked about is fixed in one message.

A test runs all 115 real lifters through the ratio and ceiling checks and asserts
that not one of them is flagged — the bands are validated against the population
they were drawn from.

**What this data cannot tell you.** OpenPowerlifting is *meet* data: single
maximal attempts on a platform, months apart. It bounds what is physically
possible and how the three lifts relate. It contains no training sessions at all,
so it says nothing about week-to-week progression, what a stall looks like, or
whether 85% is the right deload. Those are coaching policy, and they sit in one
named block at the top of `rules.py` labelled as such — not dressed up as
empirical findings.

---

## Design decisions, and what each one costs

**Gemini free tier.** No card, no expiry, and Flash is plenty for parsing — the
task is extraction, not reasoning. *Trade-off:* Google may train on free-tier
inputs, so this moves to a paid tier before other athletes' data goes through it.

**SQLite.** Small, structured, single-writer data. One file you can copy, diff
and open in any client. *Trade-off:* Postgres solves concurrency problems this
project does not have, at the cost of a server to run and a connection string to
keep secret. Twenty athletes is not a scale problem.

**One table.** Every row is one observation about one athlete at one moment. Sets
carry a lift, status updates don't. Current phase and injury state are *derived*
by reading the latest row, never stored separately, so they can't drift out of
sync with the log.

**Injury as a flag, not advice.** A logged injury suppresses every progression
suggestion and says see a physio. The agent tracks and withholds. It never
advises on an injury, because the failure mode of getting that wrong is somebody
getting hurt.

**Phone number as identity.** No sign-up, no passwords. An athlete who changes
handset keeps their history as long as they keep their number.

**`.env` + `.gitignore`.** The key never reaches GitHub.

---

## Running it

### 1. Install

```bash
git clone <this repo> && cd power-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

### 2. Try it with no keys at all

There is a regex stand-in for the model so the storage and decision layers can be
exercised offline. It is **not** the product — it handles only the tidy
phrasings a regex can handle, which is exactly why Layer 1 uses a model.

```bash
python chat.py --demo --offline --db :memory:   # replays a scripted stall → deload
python chat.py --offline                        # interactive
```

### 3. Add a Gemini key

Free, no card: <https://aistudio.google.com/apikey>. Put it in `.env` as
`GEMINI_API_KEY`, then check the parsing layer against deliberately messy input:

```bash
python scripts/check_gemini.py
```

It prints, for each sentence, the raw tool call the model returned and what the
validator made of it — including the ones it rejects.

To pick a model rather than guess at one, score several against the same cases:

```bash
export GROQ_API_KEY=...            # any subset; free keys, no card
export GITHUB_MODELS_TOKEN=...
python scripts/bench_providers.py
```

Seven labelled cases — a spelled-out weight, pounds, a relative date, an injury
mentioned in passing, two lifts in one message, and one message with no weight in
it at all. That last case is the one that decides it: a model that invents a
number for *"did some squats"* will quietly corrupt an athlete's history, and no
amount of downstream validation can recover a plausible-looking wrong weight.

Swapping providers is a one-line change — see
[`app/agent/providers.py`](app/agent/providers.py), where the OpenAI-format tool
definitions are *derived* from the same declarations Gemini gets, so the two
cannot drift.

Then:

```bash
python chat.py
```

Now the messy half works — "squats felt awful today, ground out the last two at
one forty" parses, and so does "tweaked my left shoulder on the last set", which
logs the set *and* raises the injury flag.

### 4. Connect WhatsApp (Twilio sandbox)

1. Sign up at <https://console.twilio.com> (free trial, no WhatsApp Business
   verification needed for the sandbox).
2. **Messaging → Try it out → Send a WhatsApp message.** Join the sandbox by
   texting the given `join <two-words>` code to the sandbox number.
3. Expose the app. Locally:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ngrok http 8000
   ```
4. In the sandbox settings, set **"When a message comes in"** to
   `https://<your-host>/webhook/whatsapp`, method `POST`.
5. Copy `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and your public URL into
   `.env`. Set `PUBLIC_BASE_URL` to exactly the URL you pasted into Twilio —
   behind a proxy the app sees a different host than the one Twilio signed, and
   the signature check will fail on a mismatch.

Text the sandbox number. It replies.

### 5. Deploy

`render.yaml` is included — connect the repo on [Render](https://render.com), add
the four environment variables, and point Twilio at
`https://<service>.onrender.com/webhook/whatsapp`. A `Dockerfile` is there for
anywhere else.

---

## Tests

```bash
pytest -q          # 217 tests, no network
```

The decision layer is the part athletes act on, so it is tested exhaustively —
every rule, every boundary, and a determinism test that runs the same log fifty
times and asserts the same object comes back. The model is stubbed in every test;
the suite never makes a network call.

---

## Security

- The API key lives in `.env`, which is gitignored. Nothing secret is committed.
- The webhook is a public URL that writes to a database, so every request is
  checked against Twilio's HMAC signature before it is processed
  ([`app/channels/whatsapp.py`](app/channels/whatsapp.py)). Unsigned requests get
  a 403.
- Athlete data is keyed by phone number and never crosses between athletes; the
  isolation is tested.

---

## Where this goes next

The layers stack, and each one is worthless unless the one below it is
trustworthy:

```
  parse + detect   ← built
        │
  prescribe        built for linear/RPE methods; other methods wait for
                    verified training-max, block, or variation inputs
        │
  push daily       the agent messages first, instead of waiting
                    morning sleep check-ins are built; meal/supplement schedules remain
        │
  autoregulate     built: same-day readiness may only hold or reduce load
        │
  injury flags     graded return-to-load protocols, physio in the loop
        │
  nutrition        food-access timing built; targets still need athlete/pro approval
```

You cannot autoregulate on data you cannot parse reliably, and you cannot
prescribe from a history you do not trust. Nutrition, sleep and supplements sit
last deliberately: highest harm when wrong, hardest to verify, and needing a
dietitian or physio in the loop rather than a rule in a Python file.

---

## FAQ

**Why SQLite?** Small structured data, zero setup, single file. Postgres buys
concurrency this project doesn't need and costs a server to run.

**What's a tool call?** The model returns structured arguments matching a schema
you defined, instead of prose. `{"lift": "squat", "sets": 3, "reps": 5,
"weight": 140, "rpe": 9}` can be type-checked, range-checked and rejected before
it reaches storage. A sentence cannot.

**Why is the deload rule Python and not the model?** Because it must be
deterministic and provable. Athletes act on it. The same log has to give the same
answer today that it gave last week, and every line of the reply has to trace to
a branch in `rules.py` and a row in the database.

---

## Layout

```
app/
  agent/       Layer 1 — schemas, the Gemini call, an offline stub
  storage/     Layer 2 — SQLite schema, queries, lift-name normalisation
  decision/    Layer 3 — verdicts, readiness, prescriptions, reply templates
  programming/ Pure Python — five methods, selector, session structure
  channels/    Twilio/WhatsApp transport: identity, signatures, chunking
  router.py    the seam: parse → store → decide → reply
  main.py      FastAPI service
chat.py        terminal harness, no phone required
reference/     OpenPowerlifting sample the validation bounds derive from
docs/          programming, readiness and nutrition evidence/policy boundaries
scripts/       check_gemini.py — prove Layer 1 against messy input
               bench_providers.py — score models against labelled cases
tests/         217 tests, no network
```
