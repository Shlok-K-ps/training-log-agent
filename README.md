# Training-Log Agent

A WhatsApp agent for a 20-athlete powerlifting team. Athletes text their sessions
in plain English. The agent parses them into structured data, tracks every lift
over time, and returns a verdict: **progressing, stalled, or deload**.

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
is four function schemas in [`app/agent/schemas.py`](app/agent/schemas.py), and
anything it returns outside them is thrown away before it reaches the database.

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
`GEMINI_API_KEY`, then:

```bash
python chat.py
```

Now the messy half works — "squats felt awful today, ground out the last two at
one forty" parses.

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
pytest -q          # 96 tests, no network, under two seconds
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
  prescribe        next session's numbers, not just a verdict
        │
  push daily       the agent messages first, instead of waiting
        │
  autoregulate     adjust today's load from today's reported readiness
        │
  injury flags     graded return-to-load protocols, physio in the loop
        │
  nutrition        macros, sleep, supplements
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
  decision/    Layer 3 — the rules and the reply templates
  channels/    Twilio/WhatsApp transport: identity, signatures, chunking
  router.py    the seam: parse → store → decide → reply
  main.py      FastAPI service
chat.py        terminal harness, no phone required
tests/         96 tests, no network
```
