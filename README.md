# Hackathon Event Planner

Reads messages about a 4-hour hackathon (150 students, 50 teams) from a text file and builds a plan for five areas: **venue, schedule, food, judging, budget**. When a new message arrives, it updates the plan, or rejects the message if it would break a rule, and prints a trace of every model call.

## The idea in one minute

1. **One model call reads the messages.** The model (Groq) turns text into plain facts such as `event.budget_limit = 650000`. This is the only place a model is used.
2. **Plain code decides the rest.** Who wins a conflict, which venue and food to pick, the schedule, the judge allocation and the budget are all ordinary code. No model call, no tokens.
3. **A rule checker validates the whole plan.** If a message would break a rule, the old plan stays and the message is marked REJECTED with the reason.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # then put your key in .env: GROQ_API_KEY=...
```

Frontend (only if you change it; the built version is already in `frontend/out`):

```bash
cd frontend && npm install && npm run build
```

`.env` options:

| Variable | Meaning | Default |
|---|---|---|
| `GROQ_API_KEY` | your Groq key (required for any model call) | none |
| `GROQ_MODEL` | model to use. Set this to a model on the organizers' small-model list | `llama-3.3-70b-versatile` |
| `STATE_FILE` | where the plan state is saved | `state.json` |
| `HACKATHON` | id of a hackathon made in the web UI (command line only) | default |
| `OUTPUT_FILE` | file the command line writes the plan and trace to | `final_output.json` |
| `MAX_FULL_RUN_SECONDS` / `MAX_INCREMENTAL_SECONDS` / `MAX_INCREMENTAL_CALLS` | run limits | 120 / 60 / 5 |

## How to run

**Command line** (one command for every message file, no flags):

```bash
python main.py run --messages data/sample_messages.txt
python main.py predict          # which areas will make model calls for the next change
```

It prints the numbered trace, then the plan, and saves the plan plus the full trace to `final_output.json`.

**Web page:**

```bash
uvicorn api:app --port 8000     # then open http://localhost:8000
```

## Message file format

Each message is a header line followed by its text:

```
MSG_001 | Dean's office | email | 2026-11-09
The hackathon will run for 4 hours. 150 students...
```

Also accepted: dates like `9 Nov`, `Dean's office, email` in one column, and `From: / Date: / Message:` blocks. If nothing can be read, you get an error, never a silent empty run.

## Full run or update?

The system decides by itself, with no flags:
- **No saved plan, or 4 or more unseen messages:** a fresh **full run** (limit 2 minutes). The old state is saved as `state.json.old`.
- **Fewer than 4 unseen messages:** an **update** (limit 5 model calls and 1 minute). Only the affected areas are re-planned.
- **Messages already seen:** skipped as duplicates (`NO_CHANGE` if all of them were).

## What happens to a message

1. **Read:** the model extracts facts (key, subject, value, approved yes/no).
2. **Decide:** each fact is accepted, superseded or rejected.
   - Not approved (a question, a quote) means rejected.
   - Higher authority wins: Dean's office, then Finance, then coordinator, then caterer/venue, then student, then judge, then the setup form. Same authority: the newer date wins.
3. **Resolve:** a map says which areas a changed fact affects. Only those are re-run.
4. **Plan:** plain code builds the affected sections.
5. **Validate:** the rule checker looks at the whole plan.
6. **Commit or reject:** valid plans become active. A broken plan is dropped, the old plan stays, and the offending message shows REJECTED with the reason.

A message ends up as one of: ACCEPTED, SUPERSEDED, REJECTED, IRRELEVANT (no planning facts), DUPLICATE.

## The five areas

| Area | What it does |
|---|---|
| venue | Keeps venues that seat everyone and meet the rules and budget. Prefers one with a generator, then the cheapest. |
| food | Headcount = students + staff + judges + guests (computed, never taken from a message). Picks the best package the budget still allows after the chosen venue. |
| judging | Splits teams across judges, checks the per-judge limit, and totals the honorarium. |
| schedule | Build time, prayer break, lunch (30 min assumed if no message gives one, and the plan says so), then judge visits. Uses a start hour if one is known. |
| budget | Adds venue, food, honorarium and every other cost. It must stay within the limit. |

## Rules the checker enforces

Total within budget; venue seats everyone; minimum capacity; maximum venue price; generator required; food price cap; food count equals headcount; enough judges for the per-judge limit; minimum judges; prayer break present; schedule blocks in order; event ends before the venue's closing hour.

**Rules it does not know:** any other rule a message states is kept as a note and shown under "Noted, not enforced". It is never silently ignored. An unknown fact key makes every area re-run.

## The web page

- **Hackathon picker (top):** each hackathon has its own folder under `hackathons/` with its own state and trace.
- **Plan:** the plan, a rejection banner when the last change was refused, and the unenforced notes.
- **Trace:** every model call, numbered, with model, area, input, output and tokens, and a total per run.
- **Messages:** every message with its status and reason. You can filter them.
- **Setup:** make your own hackathon with buttons and fields (students, team limit, venues with seats, food, judging, other costs, rules), or paste a description and click "Fill the form with AI", check it, then save. Form values are the lowest authority, so any real message overrides them. Saving a form makes no model call.
- **Upload a messages file (.txt):** runs the file exactly like the command line.
- **Paste a new message:** simulates one live message. The Source field matters, because it sets the authority.

## Project layout

```
main.py                 command line
api.py                  web server (FastAPI) + serves frontend/out
engine/orchestrator.py  the whole pipeline, trace and the message-file parser
engine/decision_engine.py   authority ranking and fact conflicts
engine/dependency_resolver.py   which areas a changed fact affects
engine/constraint_engine.py     the rule checker
engine/setup.py         setup form to facts, text to form (one model call)
engine/predict.py       which areas will call the model
agents/reading_agent.py Groq client and the fact-reading prompt
planners/               venue, food, judging, schedule, budget (plain code)
models/schemas.py       data shapes
state/state_manager.py  safe saving of state.json (with .bak recovery)
data/                   sample and test message files
tests/                  automated tests
frontend/               Next.js page (built output in frontend/out)
```

## Test files in `data/`

| File | Use |
|---|---|
| `sample_messages.txt` | the 8-message sample pack |
| `reject_test.txt` | after the sample: a budget cut and a 50-box order, both should be REJECTED |
| `test_pack_2.txt` | a fresh 5-message pack (120 students, Rs 500,000), should give a valid plan |
| `test_changes_2.txt` | after `test_pack_2`: a valid printing-cost change |
| `test_changes_wrong.txt` | after `test_pack_2`: 60 boxes for 138 people, should be REJECTED |

Run the automated tests with `python -m pytest -q`. They use a fake model, so they need no key.

## Known limits

- The real model has not been tested here. Check the first run's output by hand.
- Wrong-message detection depends on the model's approved flag and on sender keywords.
- Reading has one retry. A very slow or rate-limited model can hit the time limit.
- A cap on the saved setup: deleting an item in the form retracts it, but only the form's own values.
- State is in plain JSON files, one run at a time.
- Open question for the help desk: the caterer says 177 people, our count is 180 (150 + 10 + 20).
