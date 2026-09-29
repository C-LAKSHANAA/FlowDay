# FlowDay — Complete Project Reference Document

> This document covers every component, every design decision, every data flow, and every scenario in the FlowDay project from first principles to live demo. After reading this you should be able to answer any question about what exists, why it exists, how it connects, and what happens in every edge case.

> **Last updated:** September 29, 2026. Reflects the complete FlowDay codebase including all sprint updates: Groq LLM integration, deadline warning system, backlog scheduling, date validation, mini calendar sidebar, localStorage persistence, and high-priority enforcement.

---

## Table of Contents

1. [What FlowDay Is](#1-what-flowday-is)
2. [Why It Was Built This Way](#2-why-it-was-built-this-way)
3. [Repository Structure](#3-repository-structure)
4. [Data Model — The Foundation](#4-data-model--the-foundation)
5. [The CP-SAT Solver — Core Engine](#5-the-cp-sat-solver--core-engine)
6. [Disruption System — Real-Time Adaptation](#6-disruption-system--real-time-adaptation)
7. [Validation Layer](#7-validation-layer)
8. [Fixtures — Hardcoded Scenarios](#8-fixtures--hardcoded-scenarios)
9. [Persistence — Completion Log & localStorage](#9-persistence--completion-log--localstorage)
10. [Duration Prediction — ML Layer](#10-duration-prediction--ml-layer)
11. [Task Parser — Natural Language Input](#11-task-parser--natural-language-input)
12. [The FastAPI Backend — Endpoints A to Z](#12-the-fastapi-backend--endpoints-a-to-z)
13. [The Angular Frontend — Components A to Z](#13-the-angular-frontend--components-a-to-z)
14. [The Weekly Calendar — Visual Design](#14-the-weekly-calendar--visual-design)
15. [Deadline Warning System](#15-deadline-warning-system)
16. [Backlog Scheduling — Smart Slot Allocation](#16-backlog-scheduling--smart-slot-allocation)
17. [Notifications — Toast System](#17-notifications--toast-system)
18. [The Polling System — Clock Sync](#18-the-polling-system--clock-sync)
19. [GitHub Actions — CI/CD](#19-github-actions--cicd)
20. [The Test Suite](#20-the-test-suite)
21. [Every "What If" Scenario](#21-every-what-if-scenario)
22. [Demo Script / Checklist](#22-demo-script--checklist)

---

## 1. What FlowDay Is

FlowDay is an intelligent daily scheduling assistant. The core idea: you have a list of things you need to do (flexible tasks) and a set of commitments you cannot move (fixed events like lectures, meetings, family lunch). FlowDay uses a constraint-satisfaction solver to automatically place your tasks into the gaps between fixed events, respecting deadlines, time windows, priorities, and task dependencies.

What makes it more than a to-do list:

- **Overflow handling** — when tasks can't all fit, higher-priority tasks win; lower-priority ones go to a backlog with a flag if their deadline is today.
- **Real-time disruption** — when a meeting runs late, one API call re-solves the rest of the day in under a second. The system knows which tasks were already done and doesn't move them.
- **Automatic detection** — a polling loop running every 60 seconds notices when the clock has passed an event's expected end without a disruption being filed, and applies it automatically.
- **Dependency ordering** — a task that depends on another can never be scheduled before its prerequisite finishes, and is forced to backlog if its prerequisite can't be scheduled.
- **Learning** — every time you mark a task complete and record how long it actually took, the system trains a ML model to predict more accurate durations for future similar tasks.
- **Natural-language input** — describe a task in plain English ("call mom urgent today, 15 min") and the system parses it into structured fields for you to review and confirm.

---

## 2. Why It Was Built This Way

### Why Google OR-Tools CP-SAT?

Scheduling with hard constraints (no overlap, must-finish-before-deadline, depends-on) is combinatorially hard. A greedy algorithm would fail to find valid orderings in edge cases. CP-SAT is a production-grade constraint solver that handles these naturally, runs in milliseconds for day-sized problems, and supports the exact features needed: optional intervals (overflow), precedence constraints (dependencies), and a maximising objective (priority).

### Why FastAPI and not Django/Flask?

FastAPI gives automatic request/response validation via Pydantic (the same models used everywhere), auto-generated Swagger UI at `/docs`, async support for future extensions, and clean type annotations throughout. It is the right balance of productivity and capability for a Python API.

### Why Angular and not React?

Angular's opinionated structure (standalone components, services, HttpClient, RxJS) makes the polling architecture and reactive form patterns straightforward. The `interval()` + `switchMap()` + `catchError()` pipeline for polling is idiomatic Angular/RxJS and requires no third-party state management.

### Why a flat JSON file and not a database?

The completion log is genuinely a write-append, read-all workload. A JSON file with a threading lock handles that with zero infrastructure overhead. The persistence module (`persistence.py`) is the only place that knows about the file, so swapping to SQLite or PostgreSQL later only requires changing that one module.

### Why scikit-learn GradientBoostingRegressor?

It handles small, noisy datasets better than LinearRegression (which assumes a linear relationship between estimated and actual duration). It is interpretable enough for debugging and fast to train on the small datasets involved (< 1000 entries). The cold-start fallback (return estimated duration unchanged) means the feature works on day one before any data is collected.

---

## 3. Repository Structure

```
FlowDay/
├── .github/
│   └── workflows/
│       ├── backend-ci.yml     # Python tests on push/PR to backend/**
│       ├── frontend-ci.yml    # Angular build on push/PR to frontend/**
│       └── pr-check.yml       # Full stack check on every PR to main/develop
│
├── backend/
│   ├── app/
│   │   ├── models.py          # Pydantic data models — shared source of truth
│   │   ├── solver.py          # CP-SAT scheduling + disruption logic
│   │   ├── fixtures.py        # Hardcoded sample schedules for dev/testing
│   │   ├── validation.py      # Pre-solver input validation
│   │   ├── persistence.py     # Completion log file I/O
│   │   ├── duration_model.py  # ML duration predictor (scikit-learn)
│   │   ├── task_parser.py     # Free-text → structured task (LLM or heuristic)
│   │   └── main.py            # FastAPI app — all HTTP endpoints
│   ├── tests/
│   │   ├── test_solver.py     # 20 solver + integration tests
│   │   └── test_duration_model.py  # 8 ML model tests
│   ├── data/
│   │   └── completion_log.json     # Append-only completion log
│   └── requirements.txt
│
├── frontend/
│   └── src/
│       ├── main.ts                           # Bootstrap + HttpClient provider
│       ├── styles.css                        # Global design tokens
│       └── app/
│           ├── models/schedule.models.ts     # TypeScript interfaces
│           ├── services/schedule.service.ts  # All HTTP calls in one place
│           ├── weekly-calendar/              # Main calendar view + all interactions
│           └── task-editor/                  # Task creation/edit form
```

---

## 4. Data Model — The Foundation

All models live in `backend/app/models.py`. They are Pydantic `BaseModel` subclasses, which means they self-validate on construction, serialize cleanly to JSON for FastAPI responses, and are reused across all layers.

### FixedEvent

Represents an unmovable block of time (a lecture, a meeting, dinner).

| Field | Type | Purpose |
|---|---|---|
| `id` | str | Unique identifier used to reference events in disruptions |
| `title` | str | Display name |
| `start_time` | int | Minutes since midnight (e.g. 540 = 9:00 AM) |
| `end_time` | int | Minutes since midnight, must be > start_time |

**Why minutes since midnight?** Integer arithmetic is exact, fast, and directly usable as CP-SAT variable bounds. No timezone issues, no datetime parsing. All display conversion happens at the boundary (frontend or print helpers).

The model validates `end_time > start_time` via `@model_validator`.

### FlexibleTask

Represents a task the solver places in available time slots.

| Field | Type | Purpose |
|---|---|---|
| `id` | str | Unique identifier |
| `title` | str | Display name |
| `duration` | int (> 0) | Planned duration in minutes |
| `priority` | int (1–10) | Higher = more important; used in objective |
| `deadline` | int? | Must finish by this time |
| `earliest_start` | int? | Cannot start before this time |
| `latest_end` | int? | Must end by this time |
| `status` | "scheduled" or "backlog" | Set by solver |
| `start_time` | int? | Assigned by solver; null until scheduled |
| `is_deadline_today` | bool | Set by solver: True when task is in backlog AND deadline falls within today's window |
| `actual_duration` | int? | Set during task_overrun: new estimated total duration from original start |
| `depends_on` | str? | ID of a prerequisite task; null = no dependency |

**`effective_duration` property** — returns `actual_duration` if set, otherwise `duration`. All solver and display code uses this so overrunning tasks automatically use their updated length.

**Why `is_deadline_today` as a field and not computed in the frontend?** The solver knows `day_start` and `day_end` at solve time. The frontend doesn't. Keeping this computation in the backend ensures it's always consistent with the actual schedule window.

### DaySchedule

Groups one day's worth of events and tasks.

| Field | Type | Purpose |
|---|---|---|
| `date` | str | ISO 8601 date string |
| `day_start` | int | Earliest schedulable time |
| `day_end` | int | Latest schedulable time |
| `fixed_events` | list[FixedEvent] | Immovable blocks |
| `flexible_tasks` | list[FlexibleTask] | Tasks to be placed |

Validates: `day_end > day_start`, all fixed events fall within day bounds.

### WeekSchedule

A container for exactly 7 `DaySchedule` objects (Mon–Sun). The `@model_validator` enforces the count. Used by `solve_week()` and the week demo endpoint.

### TaskCompletionLog / TaskCompleteRequest

Two models added for the completion-logging and ML features.

`TaskCompleteRequest` is what the user sends: `task_id`, `actual_duration`, `category`.

`TaskCompletionLog` is what gets stored: adds `task_title`, `estimated_duration` (looked up from the current schedule), `completed_at` (auto-set to UTC ISO timestamp).

### DisruptDayResponse / DisruptWeekResponse

Wrapper response types that bundle a schedule with a plain-English `explanations` list. Used by the disrupt and check endpoints so the frontend always gets both the updated schedule and an explanation of what changed.

---

## 5. The CP-SAT Solver — Core Engine

`backend/app/solver.py` is the heart of the system. Its job is to take a `DaySchedule` with un-placed tasks and return one with `start_time` assigned to every task that fits.

### How solve_schedule() Works

**Step 1 — Fixed intervals.** Every `FixedEvent` is added as a non-variable CP-SAT interval with a constant start and size. These block time but have no decision variables — the solver treats them as immovable walls.

**Step 2 — Optional intervals.** For each `FlexibleTask` a boolean variable `is_scheduled` is created. The task's start variable is bounded to `[lo, hi]` where `lo` starts at `day_start` and is tightened by `earliest_start`; `hi` starts at `day_end - duration` and is tightened by `deadline` and `latest_end`. If `hi < lo` after tightening, the task geometrically can't fit and is skipped entirely (it will land in backlog). If it can fit, an `new_optional_fixed_size_interval_var` is created — this interval only participates in the NoOverlap constraint when `is_scheduled == 1`.

**Step 3 — NoOverlap.** A single `add_no_overlap` constraint covers all intervals (fixed + all optional flexible). This is the constraint that prevents everything from overlapping.

**Step 4 — Precedence constraints (depends_on).** After NoOverlap is set up, the solver loops through tasks with `depends_on` set and adds two constraints:
- `is_scheduled(B) <= is_scheduled(A)` — B can only be scheduled if A is. If A goes to backlog, B is forced to backlog.
- `start(B) >= start(A) + effective_duration(A)` enforced via `only_enforce_if(both_scheduled)` — B cannot start before A finishes, but this only applies when both are scheduled.

**Step 5 — Objective.** Maximise a weighted sum:
```
sum over all tasks: (priority × 1,000,000 − effective_duration × 100 − id_rank × 1) × is_scheduled
```
The weights are chosen so the hierarchy is strict:
- A 1-point priority difference (1,000,000 units) always outweighs any duration or id difference (max 144,050 units).
- A 1-minute shorter duration (100 units) always outweighs any id difference (max ~50 units).
- Id rank breaks ties deterministically when priority and duration are identical.

This means: highest priority first, then shorter tasks when priority is equal (leaving more room for others), then lexicographically smaller id.

**Step 6 — Extract results.** After solving, the inner `_is_deadline_today()` function checks each backlog task's deadline against the day's window. Tasks with a deadline within `[day_start, day_end]` get `is_deadline_today = True`.

### solve_week()

Simply calls `solve_schedule()` on each of the 7 days independently. Days have no knowledge of each other — tasks don't carry over between days.

### The Three Objective Weight Constants

```python
_W_PRIORITY = 1_000_000
_W_DURATION = 100
_W_ID       = 1
```

These are defined once at module level and referenced in every `objective_terms.append()` call. If you ever need to change the relative weighting, these are the only values to touch.

---

## 6. Disruption System — Real-Time Adaptation

### trigger_disruption()

Accepts a `DaySchedule`, a disruption dict, and an optional `current_time`. Supports five disruption types:

#### event_overrun
A fixed event ran longer than planned. Updates the event's `end_time` to `new_end_time`, then re-solves.

With `current_time`: completed tasks (`end_time <= current_time`) and in-progress tasks (`start_time <= current_time < end_time`) are locked — they are converted to synthetic `FixedEvent` objects with prefix `_locked_` so the solver cannot move or drop them. Only future tasks are reset to backlog and re-solved.

Without `current_time`: all tasks reset to backlog, whole day re-solved.

The synthetic locked events are stripped from the returned schedule — the caller sees only the real fixed events.

#### task_overrun
A currently in-progress task is taking longer than planned. Validates that the task is genuinely in-progress at `current_time`. Sets `actual_duration = new_estimated_end - start_time`. The task is locked (its slot is extended via a synthetic fixed event). Future tasks re-solved around the new longer block.

#### event_cancelled
Removes the target event entirely. The freed time is automatically available to the solver — no special handling needed. Backlog tasks may be rescued if their priority justifies it.

#### task_early_finish
An in-progress task finished sooner than planned. Sets `actual_duration` to the shorter value. The task is locked as completed (no further scheduling needed). The freed time is available to future tasks.

#### day_shrink
Updates `day_end` to a new, earlier value. Tasks that no longer fit within the shortened window are not forced — they simply cannot get a valid `start_var` domain and land in backlog. No crash.

### detect_and_apply_overruns()

Used by `GET /schedule/check`. Scans a `DaySchedule` at a given `current_time` for:
1. Fixed events where `current_time > event.end_time` — the event should have ended but hasn't.
2. Scheduled tasks where `current_time > start_time + effective_duration` and `actual_duration is None` — the task was supposed to be done but hasn't been marked complete.

For each detected overrun, applies `trigger_disruption()` *without* `current_time` (a full re-solve, not a locked re-solve — explained below).

**Why no current_time for auto-detected event overruns?** When the system auto-detects that an event is overrunning, tasks that were scheduled to start at the event's original end time are not actually in progress — they were waiting for the event to finish. Passing `current_time` would incorrectly lock them as in-progress. A full re-solve is correct here.

**Why current_time for task overruns?** Task overruns ARE genuinely in-progress events. Locking past tasks is correct.

### generate_explanation()

After any disruption, compares old and new schedules task-by-task and produces plain-English lines:
- Moved: "Complete assignment draft moved from 06:30 to 07:30 because Morning Class ran until 12:00."
- Dropped: "Work on side project was moved to backlog because there wasn't enough remaining time."
- Rescued: "Reply to emails was scheduled at 14:00 after time opened up."

The `_because()` inner function maps each disruption type to a specific clause using the event/task titles from the schedules.

---

## 7. Validation Layer

`backend/app/validation.py` runs before the solver to catch bad input early.

### validate_fixed_events(events)

O(n²) pairwise overlap check using the standard interval condition: `A.start < B.end AND B.start < A.end`. Adjacent events (one ends exactly when the next starts) are correctly allowed.

Raises `ValueError` with a message naming both events if any overlap is found.

### validate_flexible_task(task)

Checks five conditions:
1. `duration > 0` (also enforced by Pydantic, but explicit here)
2. `deadline >= earliest_start` if both set
3. `latest_end >= earliest_start` if both set
4. Window between `earliest_start` and `deadline` >= `duration`
5. Window between `earliest_start` and `latest_end` >= `duration`

### validate_day_schedule(schedule)

Calls both of the above on the full schedule. Used by `POST /schedule/solve` before handing off to the solver.

**Why not put this in the Pydantic validators?** Some of these checks are cross-field (deadline vs earliest_start), which Pydantic's `@model_validator` could handle. But `validate_fixed_events` needs the whole list — not just a single event — so it lives outside the model. Keeping all pre-solver validation in one module makes it easy to wire to new endpoints.

---

## 8. Fixtures — Hardcoded Scenarios

`backend/app/fixtures.py` provides deterministic sample data for development, testing, and demo endpoints.

### get_dummy_schedule()
Day: Sep 24, 2026, 6 AM–11 PM. Two fixed events (Morning Class 10:00–11:30, Dinner 20:00–21:00). Five flexible tasks with varied priorities (3–9) and deadlines. Used by `/schedule/demo` and the single-day disruption endpoints.

### get_overflow_schedule()
Day: Sep 25, 2026, 9 AM–6 PM. Two fixed events (Standup 9:00–9:30, Lunch 13:00–14:00). Eight tasks totalling 660 min against 450 min of free time. Designed so lower-priority tasks go to backlog, proving the priority objective works.

### get_dummy_week_schedule()
Seven days Mon Sep 28 – Sun Oct 4, 2026. Each day has its own character:
- Mon–Fri: 2 fixed events (academic/work pattern), progressively lighter as the week ends
- Saturday: gym only, leisure tasks
- Sunday: family lunch only, light recovery tasks

Used by `/schedule/week/demo` and the week disruption endpoints.

### get_dependency_schedule() / get_dependency_overflow_schedule()
Fixtures specifically for dependency testing. Task B depends on Task A. In the overflow version, Task C (highest priority) wins the only available slot, forcing A to backlog, which cascades to force B to backlog even though B's priority is high enough to normally win.

### get_tiebreak_schedule()
Four tasks all with the same priority (7) and deadline (11:00 AM). Only two 60-min slots available. Proves the tie-break objective: shorter tasks win, then lexicographically smaller id.

### get_deadline_today_schedule()
Two 90-min tasks due today whose deadline falls within `day_end=750` (12:30 PM). Two fixed events leave only a 60-min gap — neither 90-min task can fit. Both land in backlog with `is_deadline_today=True`. A 60-min no-deadline task and a 60-min task with a deadline outside the day window provide contrast.

### get_deadline_today_overflow_fixture()
A narrow-window day where some tasks can fit and some can't, specifically designed to test the `is_deadline_today` flag.

---

## 9. Persistence — Completion Log

`backend/app/persistence.py` owns all file I/O for the completion log.

**File location:** `backend/data/completion_log.json`

**Format:** A single JSON array. Each element is a `TaskCompletionLog` serialised as a flat JSON object.

**Operations:**
- `append_completion(entry)` — read existing array, append, write back. Protected by a `threading.Lock` for concurrent requests. Auto-sets `completed_at` to UTC ISO timestamp if not provided. Returns the entry as written.
- `read_all_completions()` — reads and deserialises all entries.
- `read_completions_for_task(task_id)` — filters by task id.

**Why read-modify-write instead of append-only?** JSON does not support append-only writes without re-reading. The lock keeps it safe for a single-process server. If this became a bottleneck, the swap to SQLite is trivial — only this module changes.

**Cold start:** `_ensure_file()` creates the directory and an empty `[]` file on first call, so the endpoint works on a fresh checkout with no manual setup.

---

## 10. Duration Prediction — ML Layer

`backend/app/duration_model.py` learns from completion history to predict actual task durations.

### Features
`[estimated_duration (int), category_encoded (int)]`

`category` is label-encoded: a `category_map` dict (`str → int`) is built at training time and stored alongside the model in the joblib artefact. At prediction time, unknown categories map to the `__unknown__` bucket so the model never crashes on a new category.

### Model
`GradientBoostingRegressor(n_estimators=100, max_depth=3, learning_rate=0.1, random_state=42)`.

Random state 42 ensures deterministic training — same data always produces the same model.

### train_duration_model()
Reads all completion log entries via `persistence.read_all_completions()`. Requires at least `MIN_SAMPLES = 5` entries (raises `ValueError` with a clear message otherwise). Trains the model, optionally computes a 5-fold CV R² score for ≥10 samples, saves `{"model": ..., "category_map": ...}` to `backend/data/duration_model.joblib`.

### predict_duration(category, estimated_duration)
Loads the joblib artefact. If the file doesn't exist: returns `round(estimated_duration * FALLBACK_RATIO)` (default ratio = 1.0, so returns unchanged). If the file is corrupted or a load error occurs: logs a warning and returns the fallback. Clamps output to `[1, 480]` minutes regardless of what the model returns.

### Cold Start
`FALLBACK_RATIO = 1.0` by default. This means "return estimated_duration unchanged." This is the correct behaviour: with no data, the best prediction is the user's own estimate. The ratio can be tuned if historical data shows a systematic bias (e.g. tasks always take 20% longer — set to 1.2).

---

## 11. Task Parser — Natural Language Input

`backend/app/task_parser.py` converts free-text descriptions into `FlexibleTask`-shaped dicts.

### Environment Setup

The backend loads a `backend/.env` file automatically via `python-dotenv` (`load_dotenv()` is called at the top of `main.py` before any other imports). The relevant env var is `GROQ_API_KEY`.

### Two Parse Paths

**LLM path (`GROQ_API_KEY` set):**
Sends the text to the **Groq** chat completions API using model `qwen/qwen3.8-27b` with a strict system prompt: "return ONLY valid JSON, no markdown, no explanation." Parameters: `temperature=0`, `max_tokens=256`. The JSON response is cleaned (strips code fences), the first JSON object is extracted via regex, then validated field-by-field: integer fields coerced to `int` or set to null; string fields stripped. Unknown fields silently dropped.

The `groq` Python package must be installed (`pip install groq`). If the package is missing, a `RuntimeError` is raised and the endpoint returns HTTP 503.

**Heuristic path (default, no `GROQ_API_KEY`):**
Regex-based extraction:
- Time range: patterns like `"from 11am to 5pm"`, `"11:00am-11:30am"` → sets `earliest_start`, `latest_end`, and computes `duration`
- Duration: patterns like `\d+\s*(?:hour|hr|h)\b` and `\d+\s*(?:min(?:ute)?s?)\b`
- Deadline: "today" → 1380 (23:00); "by/before/due/at HH:MM" → parsed and converted; "tomorrow" → null
- Priority: keyword map (urgent→9, asap→9, critical→10, important→7, high priority→8, low→3, whenever→2)
- Category: keyword-to-category map (read/chapter/book→reading, exercise/workout/gym/run→exercise, email/reply/call/meeting→admin, study/exam/lecture/homework/assignment→study, code/program/develop→coding, write/essay/report→writing)
- Title: the full input text, truncated to 80 characters

### Output Schema
```json
{
  "title":          "string or null",
  "duration":       "int or null",
  "deadline":       "int or null (minutes since midnight)",
  "priority":       "int or null",
  "category":       "string or null",
  "earliest_start": "int or null",
  "latest_end":     "int or null",
  "parser_used":    "\"llm\" or \"heuristic\""
}
```

Fields the parser cannot confidently determine are null — never guessed. The frontend shows these as pre-filled suggestions, not final values. The user always confirms before the task is added.

---

## 12. The FastAPI Backend — Endpoints A to Z

All endpoints are in `backend/app/main.py`. CORS is configured to allow `localhost:4200` (Angular dev server), `localhost:5000` (backend itself for browser testing), and `https://c-lakshanaa.github.io` (GitHub Pages deployment).

| Method | Path | Purpose | Returns |
|---|---|---|---|
| GET | `/` | Health check | `{"status":"ok","app":"FlowDay"}` |
| GET | `/schedule/demo` | Solve dummy single-day fixture | `DaySchedule` |
| GET | `/schedule/week/demo` | Solve dummy week fixture | `WeekSchedule` |
| POST | `/schedule/solve` | Validate + solve user-submitted schedule | `DaySchedule` |
| POST | `/schedule/check` | Auto-detect overruns at current_time | `DisruptDayResponse` |
| POST | `/schedule/disrupt` | Apply event_overrun to demo day | `DisruptDayResponse` |
| POST | `/schedule/week/disrupt` | Apply disruption to one day of demo week | `DisruptWeekResponse` |
| POST | `/tasks/complete` | Log a completed task | `TaskCompletionLog` |
| GET | `/tasks/completion-log` | Return all completion log entries | `list[TaskCompletionLog]` |
| GET | `/tasks/predict-duration` | ML-based duration prediction | `{predicted_duration, is_model_based, message}` |
| POST | `/tasks/parse` | Free-text → structured task fields | `{title, duration, deadline, priority, category, ...}` |
| GET | `/docs` | Swagger UI | Interactive HTML |

### Key Design Patterns

**`POST /schedule/solve` validates before solving.** All other endpoints use fixture data so their input is already known-good. Only user-submitted schedules go through `validate_day_schedule()`. Validation errors return HTTP 400; solver/constraint errors return HTTP 422.

**Disruption endpoints pre-validate overlap.** Before calling `trigger_disruption()`, the disrupt endpoints construct the post-disruption fixed event list and run `validate_fixed_events()` on it. This catches the case where extending an event would make it overlap its neighbour.

**`POST /schedule/check` is safe to poll.** When no overruns are detected it returns the schedule unchanged with an empty `explanations` list. The frontend only shows a notification when `explanations.length > 0`.

**`GET /tasks/predict-duration` uses query params, not a body.** GET requests semantically should not have bodies. Category and estimated_duration are small scalar values appropriate for query parameters.

---

## 13. The Angular Frontend — Components A to Z

### `main.ts`
Bootstraps the application. Provides `HttpClient` globally via `provideHttpClient()`. No `AppModule` — the app uses standalone components throughout.

### `schedule.models.ts`
TypeScript interfaces mirroring every Pydantic model. Any time a model changes in the backend, the corresponding interface needs updating here. Key interfaces: `FlexibleTask`, `FixedEvent`, `DaySchedule`, `WeekSchedule`, `CalendarBlock`, `DependencyArrow`, `DisruptDayResponse`, `DisruptWeekResponse`, `CheckRequest`, `DurationPrediction`, `ParsedTask`.

### `schedule.service.ts`
The single HTTP boundary between the Angular app and the backend. Every backend call goes through here. No component makes direct HTTP calls. Methods:
- `getDemo()`, `getWeekDemo()` — load fixture schedules
- `disrupt()`, `disruptWeek()` — manual disruption
- `solveDay()` — re-solve after task editor changes
- `checkSchedule()` — used by the poller
- `predictDuration()` — duration suggestion
- `parseTask()` — NL parse

**Why centralise HTTP in a service?** Any URL change (e.g. pointing to a production backend) is one change in one file. Any authentication header added in future is one change. Components stay focused on display logic.

### `WeeklyCalendarComponent`
The main view. Implements `OnInit` (loads the week) and `OnDestroy` (clears timers).

Key state:
- `week: WeekSchedule | null` — the raw data (loaded from `localStorage` first, then built empty)
- `dayColumns: DayColumn[]` — derived display data: blocks, backlog, dependency arrows
- `changedBlockIds: Set<string>` — ids of blocks that shifted in the last disruption (drives CSS animation)
- `explanations: string[]`, `toastVisible` — disruption toast state
- `panel: DisruptionPanel | null` — disruption panel state
- `taskEditorDay`, `taskEditorTask` — task editor state
- `currentMin`, `currentTimeString`, `currentTimeTopPct` — system clock, updated every 30 s
- `todayDateStr`, `selectedDateStr` — ISO date strings for today and selected week
- `miniCalendarDays`, `miniMonthTitle`, `activeMiniMonth` — mini month calendar sidebar state

**localStorage persistence.** All schedule data is stored in `localStorage` under key `flowday_week_schedule_v2`. The format is a `Record<string, DaySchedule>` keyed by ISO date string. `loadWeekForDate()` reads localStorage first; if a date is missing it creates an empty `DaySchedule`. `saveMasterStorage()` writes back every day of the current week after any change (solve, delete, disruption).

**`buildColumn(day, index)`** converts a `DaySchedule` into display-ready data:
1. Fixed events → `CalendarBlock` with `kind: 'fixed'`
2. Scheduled tasks → `CalendarBlock` with `kind: 'task'`, including `deadlineAtRisk`, `deadlineWarning`, and `minutesUntilDeadline` fields
3. Backlog tasks → kept in `backlog[]` for the backlog section
4. Dependency arrows → computed from `depends_on` references between scheduled blocks in the same column

**`toPosition(startMin, endMin)`** converts time intervals to `topPct` / `heightPct` percentages within the full 24-hour grid (0–1440 minutes). `topPct = (start − 0) / 1440 × 100`. Minimum `heightPct` is 2.5% so very short tasks remain clickable.

**`onTaskSave(event)`** — two separate paths:
- **Fixed task** (`is_fixed: true` AND `start_time !== null`): converted to `FixedEvent`, added to `fixed_events`, rest of the day re-solved around it.
- **Flexible task** (`is_fixed: false` OR `start_time: null`): added/updated in `flexible_tasks`, full `solveDay()` called. After solve, `ensureHighPriorityInSchedule()` runs to promote any priority ≥ 8 tasks the solver left in backlog.

**`scheduleFromBacklog(dayDate, task)`** — smart scheduling from the backlog:
1. Calls `findFreeSlot()` to search for the earliest free gap after 8:00 AM
2. If a slot is found: opens the task editor pre-filled with that start time
3. If no slot AND `priority ≥ 8`: forces scheduling at 9:00 AM (high-priority override)
4. If no slot AND `priority < 8`: opens the editor without a pre-filled time

**`ensureHighPriorityInSchedule(day)`** — post-solve enforcement: any task with `priority ≥ 8` that the solver left in `backlog` is force-promoted to `scheduled` using `earliest_start` or 9:00 AM as fallback.

**`deadlineWarningTasks`** — computed getter that scans today's tasks for any with a `deadline` within 60 minutes of `currentMin`. Used to drive the 1-hour warning banner at the top of the calendar.

### `TaskEditorComponent`
Standalone form component. Receives `editTask`, `dayTasks`, and `dayDate` as inputs; emits `save` (with the task data) and `cancel`.

Three-phase input flow:
1. **NL parse input** at the top — user describes the task, hits →, backend parses it, form fields are pre-filled
2. **Structured fields** — title, date picker, category, duration (with suggestion), priority buttons (High/Medium/Low), schedule mode toggle, depends-on dropdown, optional constraints (earliest start, latest end, deadline)
3. **Schedule mode** — three options:
   - `auto` (Flexible): no fixed start time, solver places the task; submits with `status: 'backlog'`, `start_time: null`
   - `specific` (Fixed Time): user picks an exact start time; submits with `status: 'scheduled'`
   - `backlog`: explicit backlog intent, same output as `auto`

**Date validation.** A `taskDate` date-picker field lets users pick the target day. Two computed getters:
- `isPastDate`: true if selected date is before today (ISO string comparison)
- `isPastTime`: true if on today and selected start time has already passed the current wall clock

Both validations only fire in **Fixed Time** (`scheduleMode === 'specific'`) mode. Auto/backlog tasks skip them since they have no start time. When a past time is detected, a warning banner appears with a **"Set to Now"** quick-fix button.

**Duration suggestion pipeline:** `onCategoryOrDurationChange()` pushes to a `Subject`. The Subject feeds into `debounceTime(600) → distinctUntilChanged → switchMap(predictDuration)`. The response populates `prediction`. The chip appears only when `prediction.predicted_duration !== duration` and `!suggestionDismissed`. Accepting the suggestion sets `duration = prediction.predicted_duration` and dismisses the chip. Dismissing without accepting hides the chip but keeps `duration` unchanged.

**Priority escalation.** In `onTaskSave()`, if the task has a `deadline` within 120 minutes of `currentMin`, its priority is automatically escalated to 9 (High) before the solver is called.

---

## 14. The Weekly Calendar — Visual Design

The calendar renders as a CSS flexbox grid. The hour axis (left) is a fixed 46px column. Each day takes equal `flex: 1` width. The grid height is fixed at **1560px** (24 hours × 65px per hour) and spans the full day — midnight to midnight.

### Block Positioning
CSS `position: absolute` within `col-body` (which is `position: relative; flex: 1`). Top and height are percentages of the column height derived from `toPosition()`. The grid covers 0–1440 minutes (midnight–midnight):
- A 60-minute task has `heightPct = 60/1440 × 100 = 4.17%`
- A task starting at 9 AM (540 min) has `topPct = 540/1440 × 100 = 37.5%`

`heightPct` has a minimum of 2.5% so very short tasks are always clickable.

### Visual Hierarchy (seven levels, visually distinct)
1. **Fixed events** — blue left border, blue background; click to trigger disruption panel
2. **Flexible tasks (scheduled)** — green left border, green background
3. **Tasks with dependencies** — amber left border (instead of green)
4. **Overdue tasks** (`deadlineAtRisk`)  — red border tint + `⚠️ OVERDUE` badge
5. **Near-deadline tasks** (`deadlineWarning`) — amber pulse + `⏰ DUE IN X MIN` badge
6. **Shifted blocks** — amber flash animation that fades over 3 seconds (post-disruption)
7. **Backlog tasks** — rendered as cards in the Backlog section below the grid

Within backlog cards:
- **Ordinary backlog** — grey card with task title, duration, priority badge
- **Missed deadline (`is_deadline_today=true`)** — red border, `MISSED DEADLINE` pill, red text
- **High priority** — red `High Priority` badge
- Each card has **🕒 Schedule** and **🗑️ Delete** action buttons

### Dependency Arrows
An SVG overlay (`position: absolute; inset: 0; pointer-events: none`) sits on top of each `col-body`. Dependency arrows are dashed amber lines with arrowheads pointing from the bottom of the prerequisite block to the top of the dependent block. `viewBox="0 0 100 100"` with percentage coordinates means the SVG stretches with the column automatically.

---

## 15. Deadline Warning System

A two-layer deadline awareness system surfaces urgency without requiring the user to scan the calendar manually.

### 1-Hour Warning Banner
Displayed at the top of the main calendar area (above the grid scroll area) when **any task in today's schedule** has a deadline within 60 minutes of the current system clock.

- Driven by `deadlineWarningTasks` — a computed getter that scans `today`'s `flexible_tasks`
- Updates every 30 seconds with the clock (`clockInterval`)
- Lists all near-deadline tasks inline: `"Review notes" is due in 23 min | "Assignment" is due in 47 min`
- Styled as `.deadline-banner` — amber/orange background with ⚠️ icon

### Per-Block Badges
In `buildColumn()`, each scheduled task block is evaluated:

| Condition | Field set | Badge shown |
|---|---|---|
| `end_time > deadline` OR deadline passed in system clock | `deadlineAtRisk: true` | `⚠️ OVERDUE` |
| `0 ≤ (deadline − currentMin) ≤ 60` | `deadlineWarning: true`, `minutesUntilDeadline: N` | `⏰ DUE IN N MIN` (pulsing) |

Both badges are mutually exclusive: overdue takes priority. Badges are rendered inside the `.block-meta-row` inside each calendar block.

---

## 16. Backlog Scheduling — Smart Slot Allocation

The backlog section shows all tasks with `status: 'backlog'` across the entire week, sorted high-priority first.

### Add Task to Backlog
The **"+ Add Task"** button in the backlog section header calls `openGlobalTaskEditor()`. The task editor opens with `scheduleMode: 'auto'`. On submit, the task is saved with `status: 'backlog'`, `start_time: null` and sent through `solveDay()` — the solver may place it or leave it in backlog depending on available time.

### Schedule Button (`scheduleFromBacklog`)
Each backlog card has a **🕒 Schedule** button. `scheduleFromBacklog(dayDate, task)` runs:
1. **`findFreeSlot(day, duration, deadline)`** — scans all occupied intervals (fixed events + scheduled tasks) sorted by start time. Finds the first gap ≥ `duration` minutes after 8:00 AM and before `deadline` (or `day_end`).
2. **Free slot found** → opens task editor pre-filled with that start time in Fixed Time mode
3. **No free slot + priority ≥ 8** → forces scheduling at 9:00 AM (high-priority tasks must appear in the schedule even if overlapping)
4. **No free slot + priority < 8** → opens task editor without a pre-filled time; user picks manually

### High-Priority Enforcement
`ensureHighPriorityInSchedule(day)` runs after every `solveDay()` call. Any task with `priority ≥ 8` that the solver returned in `backlog` is force-promoted:
- `start_time` set to `earliest_start` if available, else `9:00 AM` (540 min)
- `status` set to `'scheduled'`

This guarantees high-priority tasks are always visible in the calendar, even if the solver couldn't find a clean non-overlapping slot.

---

## 17. Notifications — Toast System

FlowDay uses a single toast notification surface.

### Disruption / Update Toast (dark, top-right)
Triggered after any call to `submitDisruption()`. Dark background (`#1e293b`), auto-dismisses after 5 seconds. Each explanation line from the backend is rendered as a bullet. The toast is dismissible via an ✕ button. Communicates: "you triggered a disruption and here's what the solver changed."

`showToast(lines)` is also called after `clearSchedule()` and `resetWeek()` to confirm those actions.

---

## 18. The Polling System — Clock Sync

The frontend maintains a real-time clock via `setInterval` every 30 seconds (`clockInterval`) in `WeeklyCalendarComponent`.

```
setInterval(() => updateClock(), 30_000)
```

`updateClock()` updates:
- `currentTimeString` — formatted as `HH:MM` (displayed in sidebar and `Today (HH:MM)` button)
- `currentMin` — minutes since midnight (used for past-time validation, deadline warnings, and the red current-time line)
- `currentTimeTopPct` — CSS percentage for the red "current time" indicator line on today's column

**Auto-detection polling (`POST /schedule/check`)** is implemented in the backend and fully functional via the Swagger UI, but is not wired to a periodic frontend interval in the current version. The disruption panel allows manual disruption triggering from the UI. Auto-detection can be demonstrated via the `/schedule/check` endpoint directly.

---

## 19. GitHub Actions — CI/CD

Three workflows in `.github/workflows/`:

### backend-ci.yml
Triggers on push/PR when `backend/**` changes. Runs on Python 3.11 and 3.12 in a matrix. Steps:
1. Checkout
2. Set up Python with pip cache keyed on `requirements.txt`
3. `pip install -r requirements.txt`
4. `pytest tests/ -v --tb=short`
5. Import check of all app modules (catches missing `__init__`, broken imports)

### frontend-ci.yml
Triggers on push/PR when `frontend/**` changes. Node 22, cache keyed on `package-lock.json`. Steps:
1. Checkout
2. Set up Node with npm cache
3. `npm ci` (uses lockfile for reproducibility)
4. `ng build --configuration development` (catches TypeScript errors)
5. `ng build --configuration production` (catches budget overruns, AOT compilation errors)

### pr-check.yml
Runs on every PR to `main`/`develop` regardless of which files changed. Runs both backend and frontend jobs in parallel. An `all-green` gate job with `needs: [backend, frontend]` and `if: always()` fails the PR if either job fails. This prevents merging a frontend change that happens to break the backend import chain.

---

## 20. The Test Suite

28 tests total across two test files. Run with `pytest tests/ -v` from `backend/`.

### test_solver.py (20 tests)

| Test | What it verifies |
|---|---|
| `test_comfortable_fit` | All tasks scheduled when there's room |
| `test_tight_fit` | All tasks fit when total duration exactly equals available time |
| `test_overflow_priority` | Lower-priority task deferred to backlog when only one slot |
| `test_impossible_single_task` | Task in a fully-blocked day → backlog, no crash |
| `test_deadline_respected` | No task placed with `start + duration > deadline` |
| `test_window_respected` | No task placed before `earliest_start` or after `latest_end` |
| `test_fully_booked_day` | Two events filling the whole day → all tasks in backlog |
| `test_single_disruption_reflow` | Post-disruption schedule has no overlaps and is within bounds |
| `test_cascading_disruptions` | Two sequential disruptions both produce valid schedules |
| `test_tie_break_determinism` | Same priority + deadline → shorter task wins, 5 identical runs |
| `test_overlapping_fixed_events_rejected` | Validation raises before solver |
| `test_self_contradictory_task_rejected` | deadline < earliest_start raises before solver |
| `test_in_progress_task_not_moved` | start_time unchanged after disruption with current_time |
| `test_backlog_rescue` | Cancelling an event pulls a backlogged task back in |
| `test_day_shrink` | Tasks past new day_end fall to backlog |
| `test_dependency_ordering` | B always starts after A finishes when B depends_on A |
| `test_dependency_cascade_to_backlog` | B goes to backlog when A goes to backlog |
| `test_check_detects_event_overrun` | Auto-detection applies disruption, returns explanations |
| `test_check_no_overrun_returns_unchanged` | No action when current_time is before event ends |
| `test_check_endpoint_via_fastapi` | Full integration: POST /schedule/check via TestClient |

### test_duration_model.py (8 tests)

| Test | What it verifies |
|---|---|
| `test_cold_start_returns_estimated_duration` | Returns estimate unchanged with no model file |
| `test_cold_start_different_categories` | Cold start consistent across all categories |
| `test_train_raises_with_too_few_entries` | ValueError when < 5 entries |
| `test_train_and_predict_with_sufficient_data` | Model trains, file created, prediction reasonable |
| `test_predict_unknown_category_does_not_crash` | Unseen category maps to `__unknown__` gracefully |
| `test_prediction_clamped_to_valid_range` | Negative raw prediction → clamped to 1 |
| `test_prediction_clamped_upper_bound` | Huge raw prediction → clamped to 480 |
| `test_corrupted_model_file_falls_back` | Corrupt joblib → fallback, no crash |

All ML tests use `tmp_path` and `monkeypatch` so they never touch the real log or model files.

---

## 21. Every "What If" Scenario

**What if all tasks are longer than the day?**
`hi < lo` for every task during variable creation → no variables created → all tasks land in backlog via the "variable never created" path. No crash.

**What if two tasks have identical priority and duration?**
Id rank (lexicographic order) breaks the tie. The solver will always schedule the one with the lexicographically smaller id. This is tested and verified across 5 runs.

**What if a task's dependency isn't in the same schedule?**
`task_index.get(dep_id)` returns `None` → the constraint creation is skipped → the dependent task is treated as having no dependency. It may or may not be scheduled based purely on its own priority.

**What if the backend is unreachable during polling?**
`catchError(() => EMPTY)` in the switchMap pipeline returns an empty observable. The subscription continues. No error is shown. The next poll attempt (60 seconds later) tries again.

**What if the LLM returns malformed JSON?**
`_parse_json_response()` raises `ValueError` with the raw response included in the message. `task_parse()` catches this and returns HTTP 422 with a clear `detail` string. The Angular form shows the error under the parse input.

**What if `GROQ_API_KEY` is not set?**
`parse_task_text()` uses the heuristic parser. The endpoint works normally and returns `parser_used: "heuristic"`. No degraded functionality — the heuristic handles most common patterns accurately.

**What if the `groq` package is not installed but `GROQ_API_KEY` is set?**
`_llm_parse()` catches the `ImportError` and raises `RuntimeError("groq package not installed. Run: pip install groq")`. The endpoint returns HTTP 503 with that message.

**What if the ML model file doesn't exist?**
`predict_duration()` checks `MODEL_FILE.exists()`. Returns `round(estimated_duration * FALLBACK_RATIO)` (= estimated_duration unchanged with default ratio 1.0). `is_model_based: false` in the response. The frontend suggestion chip shows "No past data yet — using your estimate as-is."

**What if a disruption would create an overlapping fixed event?**
The disrupt endpoints pre-validate the post-disruption event list with `validate_fixed_events()`. HTTP 400 is returned before `trigger_disruption()` is ever called.

**What if `new_day_end` is set to before `day_start`?**
`trigger_disruption(day_shrink)` raises `ValueError("new_day_end must be after day_start")`. HTTP 422 returned.

**What if a task is marked complete but its id doesn't exist in the schedule?**
`POST /tasks/complete` searches all 7 days of the solved week. If not found: HTTP 404 with `"No FlexibleTask with id='...' found"`.

**What if the completion log JSON is corrupted?**
`_read_all()` in `persistence.py` catches `json.JSONDecodeError` and returns an empty list. Append operations continue working. The file is effectively reset to empty on the next write.

**What if two requests hit `append_completion()` simultaneously?**
The `threading.Lock` serialises the read-modify-write. One request waits while the other completes. Both entries are written correctly.

**What if a task is added from the backlog with no available free slot?**
If `priority ≥ 8`: `ensureHighPriorityInSchedule()` force-promotes it to scheduled at 9:00 AM. It will appear in the calendar even if it overlaps with another block (the overlap algorithm positions it side-by-side). If `priority < 8`: it stays in backlog.

**What if the user submits the task editor with a past date?**
In Fixed Time (`scheduleMode === 'specific'`) mode, `isPastDate` returns true and `submit()` blocks with an error message. In Auto mode, the date check is skipped — a backlog task with a past date is treated as "carry over" and is still added.

**What if `localStorage` is cleared by the browser?**
`loadMasterStorage()` returns an empty `Record`. All 7 days are initialised as empty `DaySchedule` objects (no tasks, no events). The user starts with a blank week. No crash.

---

## 22. Demo Script / Checklist

This is a continuous walkthrough of the entire system. No code — just what to do in what order and what to observe at each step.

---

### Prerequisites

- Backend running: `cd backend`, activate `.venv`, `uvicorn app.main:app --reload --port 5000`
- Frontend running: `cd frontend`, `npm start`
- Browser open at `http://localhost:4200`
- Second browser tab open at `http://localhost:5000/docs`

---

### Step 1 — View the Weekly Calendar

1. Open `http://localhost:4200`. The weekly calendar loads automatically.
2. Observe 7 columns (Mon 28 Sep – Sun 4 Oct 2026).
3. Blue blocks = fixed events (lectures, dinner, gym, etc.). Green blocks = flexible tasks placed by the solver.
4. Note that no two blocks overlap within any column.
5. Scroll down — observe the Backlog section (should be empty since all tasks fit in the demo week).

**What just happened:** Angular called `GET /schedule/week/demo`. The backend loaded the 7-day fixture, ran CP-SAT on each day independently, and returned 7 solved DaySchedule objects. The frontend converted each task's time into percentage offsets and rendered them as absolutely-positioned CSS blocks.

---

### Step 2 — Create a Task via Natural Language

1. Click the `+` button in the Monday column header.
2. The Task Editor modal opens.
3. In "Describe your task", type: `review notes urgent today 30 min`
4. Press → (or click the arrow button).
5. Watch the form fields populate: Title = "review notes urgent today 30 min", Duration = 30, Priority = 9 (urgent), Deadline = 23:00 (today), Category = "reading" (from "review").
6. Change the title to "Review Monday notes".
7. Click "Add task". The modal closes.
8. The task appears in the Monday column (or backlog if no slot is available).

**What just happened:** Angular called `POST /tasks/parse` with the text. The heuristic parser extracted duration (30 min), priority (urgent→9), deadline (today→1380), and category (review→reading). The form was pre-filled. After clicking "Add task", Angular called `POST /schedule/solve` with the updated Monday schedule. The solver placed the new task in an available slot.

---

### Step 3 — Trigger a Manual Disruption

1. In the Wednesday column, find the "Tutorial" fixed event (around 11:00 AM – 12:30 PM).
2. Hover over it — observe the blue glow on hover and "click to disrupt" hint.
3. Click the Tutorial block. The disruption panel opens.
4. The "Tutorial" event is pre-selected.
5. Set "New end time" to 13:30 (one hour overrun).
6. Click "Apply".

**What to observe:**
- The disruption panel closes.
- A dark toast appears in the top-right: "What changed" with explanation lines like "Assignment draft — section 2 moved from 08:20 to 13:30 because Tutorial ran until 13:30."
- Shifted blocks in the Wednesday column flash amber for 2.5 seconds.
- The rest of the week is completely unchanged.

**What just happened:** Angular called `POST /schedule/week/disrupt` with `day_date: "2026-09-30"`, `event_id: "wed-evt-001"`, `new_end_time: 810`. The backend solved the full week, found Wednesday, applied `trigger_disruption()` on just that day, and returned the updated WeekSchedule with explanations. The frontend diff'd old vs new block positions for Wednesday only, set the shifted block IDs, and triggered the CSS animation.

---

### Step 4 — Watch Automatic Detection Catch an Overrun

1. Open `http://localhost:5000/docs` in a second tab.
2. Navigate to `POST /schedule/check`.
3. Click "Try it out".
4. First call `GET /schedule/demo` to get a solved schedule (copy the JSON response).
5. In the `/schedule/check` body, paste the schedule and set `current_time` to a value 30 minutes past a fixed event's `end_time` (e.g. if Morning Class ends at 690, set `current_time: 720`).
6. Execute. Observe the response: `explanations` will contain at least one line about the overrun. The returned schedule will have tasks shifted past the new event end time.

**What just happened:** `detect_and_apply_overruns()` scanned the schedule, found the fixed event whose `end_time (690) < current_time (720)`, constructed an `event_overrun` disruption with `new_end_time = 720`, applied it without `current_time` (full re-solve), and returned the updated schedule with explanations.

**In the Angular app:** The polling loop does exactly this automatically every 60 seconds. When it detects a change, the green banner appears at the bottom-right.

---

### Step 5 — Task with a Dependency Respects Ordering

1. Open `http://localhost:5000/docs`.
2. Call `POST /schedule/solve` with this body:
```
{
  "date": "2026-10-07",
  "day_start": 540,
  "day_end": 780,
  "fixed_events": [],
  "flexible_tasks": [
    {"id": "A", "title": "Task A", "duration": 60, "priority": 7},
    {"id": "B", "title": "Task B (depends on A)", "duration": 60, "priority": 8, "depends_on": "A"}
  ]
}
```
3. Execute. Observe the response: Task A is scheduled first (e.g. 09:00–10:00), Task B is scheduled immediately after (10:00–11:00). Despite B having higher priority, it cannot start before A finishes.

**What just happened:** The solver created a boolean `both_scheduled` variable and added `start(B) >= start(A) + 60` only when both are scheduled. The `is_scheduled(B) <= is_scheduled(A)` constraint ensures if A goes to backlog, B must too.

---

### Step 6 — Deadline-Today Flag When Task Can't Fit

1. Call `POST /schedule/solve` with this body:
```
{
  "date": "2026-10-06",
  "day_start": 540,
  "day_end": 750,
  "fixed_events": [
    {"id": "e1", "title": "Morning standup", "start_time": 540, "end_time": 600},
    {"id": "e2", "title": "Team sync", "start_time": 660, "end_time": 750}
  ],
  "flexible_tasks": [
    {"id": "dt-001", "title": "Urgent report", "duration": 90, "priority": 9, "deadline": 750},
    {"id": "dt-002", "title": "Critical review", "duration": 90, "priority": 9, "deadline": 750},
    {"id": "dt-003", "title": "Someday reading", "duration": 60, "priority": 3}
  ]
}
```
2. Execute. Observe:
   - `dt-001` and `dt-002` are both in backlog with `is_deadline_today: true` (deadline 750 is within day_start 540 – day_end 750, and no 90-minute gap exists).
   - `dt-003` is in backlog with `is_deadline_today: false` (no deadline set).

**In the Angular app:** Both dt-001 and dt-002 would appear in the Backlog section with red borders, "MISSED" pill, and red text. The backlog header would show "2 missed today" in a red badge.

---

### Step 7 — Backlog Task Rescued When Time Frees Up

Continuing from Step 6, now cancel one of the fixed events:

1. Call `POST /schedule/solve` with the same schedule but remove `e2` from `fixed_events`.
2. Execute. Now the 60-minute gap between e1 (ends 10:00) and the end of day (12:30) is wide open.
3. Observe: `dt-001` (90 min, p=9) and `dt-002` (90 min, p=9) both get scheduled. Backlog is empty.

**What just happened:** With `e2` removed, free time = 600–750 = 150 minutes. Both 90-minute tasks fit sequentially. The solver's objective pulled them out of backlog because the freed time justifies it. `is_deadline_today` is automatically `false` for scheduled tasks.

---

### Step 8 — Run the Full Test Suite Live

In the backend terminal (or a new terminal with `.venv` active):

```
cd backend
pytest tests/ -v
```

**What to observe:**
- 28 tests collected
- All 28 pass
- Coverage spans: comfortable fit, tight fit, overflow priority, impossible tasks, deadline constraints, window constraints, fully booked day, single disruption, cascading disruptions, tie-break determinism, validation rejection, in-progress locking, backlog rescue, day shrink, dependency ordering, dependency cascade, auto-detection, no-overrun idempotency, FastAPI integration
- Duration: ~4–7 seconds (the solver is fast for small problems)

Every test is self-contained — no test relies on another, no shared state, no fixture files required. Each builds its own minimal `DaySchedule` inline using the `day()`, `task()`, and `event()` helper factories at the top of `test_solver.py`.

---

### End State

After completing the demo:
- The weekly calendar shows a correctly-solved 7-day schedule
- Wednesday's column shows a re-arranged schedule from Step 3
- The backlog section is clean (or shows only intentionally unscheduled tasks)
- The completion log at `backend/data/completion_log.json` may have entries from any task marking done
- All 28 tests are green

The entire flow — from NL task creation through visual calendar rendering, manual disruption, automatic detection, dependency ordering, deadline flagging, backlog rescue, and test verification — has been walked through without any manual schedule manipulation. FlowDay did the scheduling, detected the disruption, and re-scheduled around it automatically.

---

*Document last updated: September 29, 2026. Reflects the complete FlowDay codebase including sprint updates: Groq LLM integration, deadline warning system, backlog scheduling, smart slot allocation, high-priority enforcement, date/time validation in task editor, mini month calendar sidebar, full 24-hour grid, localStorage-based persistence, and CORS deployment configuration.*
