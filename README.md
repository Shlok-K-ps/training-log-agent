# Power AI — Training-Log Agent

GitHub: <https://github.com/Shlok-K-ps/training-log-agent>  
Live: <https://training-log-agent.onrender.com/>

**A deterministic powerlifting coaching agent for one coach and twenty athletes.**

A powerlifting coach's real job is not writing programs. It is reading twenty
WhatsApp messages a day, remembering who is hurt, noticing who has gone quiet,
and catching the lifter who has been stuck at the same weight for a month. That
work scales linearly with the roster, and it is the first thing to slip when the
coach gets busy — which is exactly when an athlete most needs someone to notice.

This agent absorbs that work. Athletes text their sessions in plain English from
the app they already have open. The agent parses them into structured data,
tracks training, sleep, readiness, soreness, stress, bodyweight and nutrition,
and prepares a deterministic verdict — progressing, stalled, deload — computed
the same way every time. The coach approves the resulting guidance from one
daily WhatsApp desk instead of reconstructing context across twenty chats.

## What the coach stops doing by hand

| Done by hand | Done by the agent |
|---|---|
| Reading every message and copying numbers into a spreadsheet | The athlete texts; the message is parsed, validated and stored |
| Remembering who is hurt | An injury flag suppresses every load suggestion until a named person clears it |
| Spotting a stall buried in weeks of logs | Stall episodes are recomputed on every message |
| Chasing athletes for sleep and readiness | The agent sends the morning check-in itself, in each athlete's timezone |
| Finding a slot around someone's timetable | The agent reads their calendar and real travel time and proposes options |
| Booking the session | `confirm CODE` writes it to an app-owned calendar, idempotently |

Nothing here replaces the coach's judgement. It removes the clerical work that
stands between the coach and the two or three athletes who actually need
attention today.

## Who is allowed to decide what

| | Athlete | Agent | Coach |
|---|---|---|---|
| Report a session, pain, sleep, food | ✅ | — | — |
| Parse a message into structured data | — | ✅ | — |
| Judge progressing / stalled / deload | — | ✅ deterministic | — |
| Open an injury flag | ✅ | ✅ | ✅ |
| **Close an injury flag** | ❌ | ❌ | ✅ only |
| Approve a supplement regimen | ❌ | ❌ | ✅ only |
| Set a calorie or protein target | reports one | ❌ | reviews it |

The two ❌ rows are enforced in code, not in a prompt. See
[`app/decision/guardian.py`](app/decision/guardian.py).

---

Athletes receive an immediate receipt; coaching guidance waits for the coach:

```
athlete                                                        agent
   │
   │  "squat 3x5 at 140 today, felt way harder than tuesday, rpe 9"
   ├──────────────────────────────────────────────────────────────▶
   │                                                    Got it — I’ve logged your update and
   │                                                    sent it to your coach for review.
   ◀──────────────────────────────────────────────────────────────┤
                          agent draft ──▶ coach approves ──▶ WhatsApp
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
   │  LAYER 2   app/storage/    SQLite. One coaching timeline,    │
   │  store     ────────────    plus encrypted integration state  │
   │                            and approved slot proposals.      │
   │                                   │                           │
   │                                   ▼                           │
   │  LAYER 3   app/decision/   Plain Python. Compares against     │
   │  decide    ─────────────   this athlete's history and returns │
   │                            the verdict. No model. No API call.│
   │                            No randomness.                     │
   └───────────────────────────────┼───────────────────────────────┘
                                   ▼
                        deterministic draft ──▶ coach ──▶ WhatsApp
```

**Why the split:** messy input needs a model, but the output is advice real
athletes act on, so it must be identical on every run and provable. A language
model is the right tool for reading "ground out the last two at one forty" and
the wrong tool for deciding whether someone should strip 15% off their squat.

The model never sees the reply text. It cannot write one. Its entire vocabulary
is twenty function schemas in [`app/agent/schemas.py`](app/agent/schemas.py), and
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
Calendar permissions, travel logic and the approval boundary are in
[calendar and location planning](docs/calendar-and-location-planning.md).

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
holds the top ~300 lifters of all time by Dots (Raw+Wraps) from
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
| bench ÷ squat, elite range | 0.36 – 0.82 |
| deadlift ÷ squat, elite range | 0.48 – 1.41 |

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

A test runs all 300 real lifters through the ratio and ceiling checks and asserts
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

**Gemini during development only.** Flash is used for extraction, not coaching.
Athlete messages can contain health, nutrition and training data, so production
must use a data-processing arrangement suitable for that data. Do not launch a
team on a consumer/free-tier model account. Exact `my home/gym/office is ...`
commands, OAuth commands and confirmation codes are parsed locally and never
sent to the model.

**SQLite.** Small, structured, single-writer data. One file you can copy, diff
and open in any client. *Trade-off:* Postgres solves concurrency problems this
project does not have, at the cost of a server to run and a connection string to
keep secret. Twenty athletes is not a scale problem.

**One coaching timeline.** Every `entries` row is one observation about one
athlete at one moment. Sets carry a lift, status updates don't. Current phase and
injury state are *derived* from the latest fact. OAuth tokens, saved places and
calendar proposals live in supporting tables because they are operational state,
not coaching observations.

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
   Outgoing API messages automatically request delivery updates at
   `https://<your-host>/webhook/whatsapp/status` when `PUBLIC_BASE_URL` is set.
5. Copy `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and your public URL into
   `.env`. Set `PUBLIC_BASE_URL` to exactly the URL you pasted into Twilio —
   behind a proxy the app sees a different host than the one Twilio signed, and
   the signature check will fail on a mismatch.

Text the sandbox number. It acknowledges the log immediately; the coaching
response appears in the coach's WhatsApp Desk for approval.

### 5. Deploy

`render.yaml` is set up for Render's **free** plan. Connect the repo as a
Blueprint, fill in the secrets Render asks for, and the coach console is live at
`https://<your-service>.onrender.com/coach?token=<COACH_ACCESS_TOKEN>` — Render
generates that token; read it from the dashboard.

Two free-plan limits, neither of which affects the rules or the console itself:

- **No persistent disk.** Training history lives on a temporary filesystem and
  is lost on every deploy and restart. Fine for a demo; not fine for real
  athletes. Move to a paid instance type and uncomment the `disk:` block to fix.
- **The service sleeps** after 15 minutes without traffic. Proactive morning
  check-ins cannot fire while it is asleep, so they are unreliable until the
  service is always on.

Netlify, Vercel and similar static/serverless hosts cannot run this service:
it is a long-lived Python process with a background scheduler, not a set of
files plus short-lived functions. A `Dockerfile` is included for other hosts.

### 6. Connect Google Calendar and travel time

Enable Google Calendar API and Routes API in a Google Cloud project, create a
web OAuth client, and register this callback:

`https://<service>.onrender.com/integrations/google/calendar/callback`

Add `GOOGLE_CALENDAR_CLIENT_ID`, `GOOGLE_CALENDAR_CLIENT_SECRET`,
`GOOGLE_MAPS_API_KEY`, `OAUTH_STATE_SECRET`, and
`CALENDAR_TOKEN_ENCRYPTION_KEY` from `.env.example`. Then use WhatsApp:

```text
connect my calendar
my gym is 123 High Street
my home is 456 Park Road
schedule my squat today
confirm A1B2C3
```

The OAuth connection grants read-only event access and write access only to a
calendar created by this app. Public apps may need Google's sensitive-scope
verification; read the calendar planning document before launch.

To enable a supplement reminder, a team operator must separately add the exact
name, dose, unit, timing, approver and verified-batch status to
`TEAM_APPROVED_SUPPLEMENT_REGIMENS`. Athlete-entered approval fields remain in
the log but do not grant scheduling authority.

---

## Tests

```bash
pytest -q          # 341 tests, no network
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
- Calendar tokens and saved places are encrypted at rest. Event titles, descriptions, attendees
  and meeting content are not persisted or sent to the model.
- Saved-place writes fail closed when the encryption key is absent. Canonical
  home, gym and office commands are parsed locally, before the model boundary.
- Athlete training, recovery and nutrition messages may reach the configured
  parsing provider. A suitable production data-processing agreement is a launch
  requirement, not an optional hardening task.
- Calendar writes go only to an app-created calendar after explicit WhatsApp
  confirmation. Athletes can disconnect Calendar and delete saved places by message.

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
  push daily       built: morning sleep check-ins, meal and supplement timing,
                    sent in each athlete's own timezone
        │
  autoregulate     built: same-day readiness may only hold or reduce load
        │
  calendar agent   built: reads events/locations, computes travel, proposes
                    slots, writes only a confirmed option to an app-owned calendar
        │
  injury gate      built: the model cannot clear an injury; a named person must
                    │        graded return-to-load protocols are not built yet
        │
  coach console    built: overview, searchable squad directory, athlete history,
                    readiness/program/nutrition context, and WhatsApp Desk
        │
  nutrition        food-access timing built; targets still need athlete/pro approval
```

You cannot autoregulate on data you cannot parse reliably, and you cannot
prescribe from a history you do not trust. Nutrition, sleep and supplements sit
late deliberately: highest harm when wrong, hardest to verify, and needing a
dietitian or physio in the loop rather than a rule in a Python file.

**The coach console** is what makes this a coaching tool rather than twenty
separate athlete tools. Sign in once at `/coach/login`; the authenticated
workspace then has four persistent sections:

- **Overview** — squad totals, same-day check-ins, pending approvals, and the
  exceptions that need a coach first.
- **Athletes** — searchable status/readiness directory. Each athlete opens into
  training history and charts plus recovery, programming, scheduling, nutrition,
  supplements, and an evidence-based message draft.
- **WhatsApp Desk** — Inbox, Needs approval, Scheduled, and Sent views with the
  athlete conversation, unread feedback, exact drafts and delivery status.
- **Analytics** — dated goal pacing across the squad: ahead, on track, or
  lagging against a visible starting-1RM-to-target checkpoint.

Athlete onboarding starts with bodyweight, all three 1RMs, training frequency,
experience, current injuries, and an optional dated lift goal. A fresh injury
opens four deterministic training-management paths for the coach to choose
between; none diagnoses or clears the athlete, and any newer injury report makes
the earlier choice stale.

The overview still orders decisions before observations:

```
Coach Rao — roster                                    2026-09-10
5 of 9 athletes need a look today.

NEEDS YOU (1)
  Priya K.    injury open 23d (left knee, squatting) · has asked to be cleared
              [ who cleared them, and on what basis ]  (Clear injury)
WATCH (3)
  Neha D.     no logs in 11 days
  Rohit S.    squat — stalled
  Sameer B.   squat — down on last session
MEET PREP (1)
  Ananya R.   meet in 5 weeks
FINE (4)
  Arjun M., Dev P., Kavya S., Meera J.
```

Silence is the signal no athlete will ever send you, so it is read out of the
absence of rows rather than the presence of one. Every other line traces to the
same rule that answers the athlete — the console computes no new verdicts.

Coach writes are explicit and attributed: enrolling an athlete, approving or
holding a message, writing a direct note, and closing an injury flag. Injury
clearance records the coach's name, reason and timestamp; nothing in the agent
or athlete channel can perform that write.

Set `COACH_ACCESS_TOKEN` to open it. Unset means closed, never open.

### Nothing proactive goes out unreviewed

The agent messages first. That is the useful part and also the risky part — an
outbound message is the one thing an athlete cannot ignore, and it arrives with
the coach's authority attached whether or not the coach wrote it.

So the send is split in two. The agent prepares morning prompts and responses to
athlete feedback, then queues them at `/coach/whatsapp` with the supporting
evidence:

```
Coach Rao — outbox                                     2026-09-10
QUEUED FOR TOMORROW (1)
  Priya Kulkarni                                  +919812340001
  Where they are: squat — stalled
  ┌────────────────────────────────────────────────────────────┐
  │ Good morning — recovery check-in. How many hours did you   │
  │ sleep? … Today's usual training time is 18:30.             │
  └────────────────────────────────────────────────────────────┘
  [ Approve for 2026-09-11 ]  [ Don't send ]
```

The coach edits anything that reads wrong and approves. In the morning, only
approved drafts are sent — **and the athlete receives the coach's wording, not
the agent's**. Drafting runs in each athlete's own local evening, so a squad
spread across timezones is still reviewed the night before *their* morning.

Unreviewed means unsent. A coach who is asleep, busy or away produces silence,
not an unsupervised broadcast — the same way an unset token closes the console
rather than opening it. This cannot be disabled by deployment configuration.

Every approval records who made it, when, and whether the wording was changed.
Untouched morning prompts whose evidence has not changed can be approved as a
safe batch. New readiness data, an injury, a schedule update, an edit, or any
other newer athlete fact forces individual review. If evidence changes after
approval but before sending, the approval is invalidated automatically.

To test the workflow without Twilio, load the fictional demo squad from
Overview, open **WhatsApp → Inbox → Test the WhatsApp workflow**, and submit a
check-in such as `slept 5h, readiness 4, soreness 6, stress 7`. The simulator
uses the real parser, storage and approval queue but is restricted to reserved
non-dialable demo numbers, so it cannot message a real athlete.

There is also a terminal equivalent, for a deployment with no web access:

```bash
python scripts/clear_injury.py --list
# +919000000000  open 20d since 2026-08-20  (left knee, squatting) · STALE
```

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
  coach/       Layer 4 — the roster view, coach auth, one audited write
  decision/    Layer 3 — verdicts, readiness, prescriptions, reply templates
               guardian.py — the injury gate; issues the only SafetyClearance
  programming/ Pure Python — five methods, selector, session structure
  channels/    Twilio/WhatsApp transport: identity, signatures, chunking
  integrations/ Google Calendar OAuth/API and Google Routes travel facts
  scheduling/   slot search, sleep/travel gates, and the outbox review gate
  router.py    the seam: parse → store → decide → reply
  main.py      FastAPI service
chat.py        terminal harness, no phone required
reference/     OpenPowerlifting sample the validation bounds derive from
docs/          programming, readiness and nutrition evidence/policy boundaries
scripts/       clear_injury.py — COACH TOOL: list flagged athletes, close a flag
               check_gemini.py — prove Layer 1 against messy input
               bench_providers.py — score models against labelled cases
tests/         341 tests, no network
```
