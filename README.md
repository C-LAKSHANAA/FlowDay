# FlowDay

An intelligent daily scheduling assistant that automatically places your tasks around fixed commitments, adapts in real time when things run late, and learns from how long tasks actually take.

---

## What It Does

- **Solves your day** — given a list of tasks and fixed events (lectures, meetings, gym), the CP-SAT constraint solver places tasks into available gaps, respecting deadlines, time windows, priorities, and task dependencies.
- **Handles overflow** — when not everything fits, higher-priority tasks win. Lower-priority tasks go to a backlog; anything that was due today is flagged "MISSED" in red.
- **Adapts to disruptions** — one click extends a fixed event that ran long, and the solver instantly re-arranges everything after it.
- **Auto-detects overruns** — a background poll every 60 seconds notices when the clock has passed an event's scheduled end without a disruption being filed, and re-solves automatically.
- **Respects dependencies** — mark Task B as depending on Task A, and it will never be placed before A finishes. If A can't be scheduled, B goes to backlog too.
- **Learns over time** — every time you mark a task complete and record how long it actually took, a scikit-learn model trains itself to predict more accurate durations for similar future tasks.
- **Understands plain English** — type "call mom urgent today 15 min" and the system parses it into structured fields for you to review before adding to the schedule.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Scheduling engine | Google OR-Tools CP-SAT |
| Backend API | FastAPI (Python 3.11+) |
| Data validation | Pydantic v2 |
| ML prediction | scikit-learn (GradientBoostingRegressor) |
| Persistence | JSON file + threading lock |
| Frontend | Angular 17 (standalone components) |
| Reactivity | RxJS |
| CI/CD | GitHub Actions |

---

## Project Structure

```
FlowDay/
├── backend/
│   ├── app/
│   │   ├── models.py          # Pydantic data models
│   │   ├── solver.py          # CP-SAT solver + all disruption types
│   │   ├── fixtures.py        # Sample schedules for dev/demo
│   │   ├── validation.py      # Pre-solver input validation
│   │   ├── persistence.py     # Completion log file I/O
│   │   ├── duration_model.py  # ML duration predictor
│   │   ├── task_parser.py     # Free-text → structured task
│   │   └── main.py            # FastAPI app + all endpoints
│   ├── tests/
│   │   ├── test_solver.py         # 20 solver tests
│   │   └── test_duration_model.py # 8 ML model tests
│   ├── data/
│   │   └── completion_log.json    # Append-only completion log
│   └── requirements.txt
│
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── models/            # TypeScript interfaces
│       │   ├── services/          # HTTP service layer
│       │   ├── weekly-calendar/   # Main calendar view
│       │   └── task-editor/       # Task creation form
│       ├── main.ts
│       └── styles.css
│
├── .github/workflows/             # GitHub Actions CI
├── README.md
└── FLOWDAY_PROJECT_DOCUMENT.md    # Full A–Z project reference
```

---

## Prerequisites

- **Python 3.11 or 3.12**
- **Node.js 18+** (22 recommended)
- **npm**

---

## Getting Started

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd FlowDay
```

---

### 2. Backend setup

```bash
cd backend
```

**Create and activate a virtual environment:**

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python -m venv .venv
source .venv/bin/activate
```

**Install dependencies:**

```bash
pip install -r requirements.txt
```

**Verify OR-Tools is working:**

```bash
python app/test_ortools_setup.py
```

Expected output:
```
Status : OPTIMAL
x = 0
y = 7
OR-Tools CP-SAT is working correctly.
```

**Start the backend:**

```bash
uvicorn app.main:app --reload --port 5000
```

The API is now running at `http://localhost:5000`.
Interactive docs at `http://localhost:5000/docs`.

---

### 3. Frontend setup

Open a **new terminal** (keep the backend running).

```bash
cd frontend
npm install
npm start
```

The app opens at `http://localhost:4200`.

---

### 4. Verify everything is connected

Open `http://localhost:4200` — the weekly calendar should load and display 7 days of tasks.

If you see a blank screen or error, check:
- Backend is running on port 5000 (not 8000).
- Both terminals are active.

---

## Running the Tests

From the `backend/` directory with the virtual environment active:

```bash
pytest tests/ -v
```

Expected: **28 passed** in under 10 seconds.

To run just the solver tests:
```bash
pytest tests/test_solver.py -v
```

To run just the ML model tests:
```bash
pytest tests/test_duration_model.py -v
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Health check |
| GET | `/schedule/demo` | Solve the demo single-day schedule |
| GET | `/schedule/week/demo` | Solve the demo 7-day schedule |
| POST | `/schedule/solve` | Solve a user-submitted DaySchedule |
| POST | `/schedule/check` | Auto-detect overruns at `current_time` |
| POST | `/schedule/disrupt` | Apply a disruption to the demo day |
| POST | `/schedule/week/disrupt` | Apply a disruption to one day of the week |
| POST | `/tasks/complete` | Log a completed task |
| GET | `/tasks/completion-log` | Retrieve all completion log entries |
| GET | `/tasks/predict-duration` | ML-predicted task duration |
| POST | `/tasks/parse` | Parse free-text into structured task fields |

Full interactive documentation: `http://localhost:5000/docs`

---

## Key Features In Depth

### Natural Language Task Creation
Type a description like `"read chapter 4, 30 min, due by noon"` in the task editor. The backend parses it into `title`, `duration`, `deadline`, `priority`, and `category`. The form is pre-filled for you to review — nothing is added until you confirm.

If `OPENAI_API_KEY` is set in the environment, the LLM parser (gpt-4o-mini) is used. Otherwise the built-in heuristic parser handles common patterns.

### Manual Disruption
Click any blue fixed event block on the calendar. Set a new (later) end time. Click Apply. The solver re-arranges only that day around the new boundary while the rest of the week stays untouched. Shifted tasks flash amber and a toast explains what moved.

### Automatic Detection
The frontend polls `POST /schedule/check` every 60 seconds. If the current time has passed a fixed event's scheduled end without a disruption being filed, the system detects and applies the overrun automatically. A green banner appears at the bottom-right when this happens.

### Dependency Ordering
When creating a task, select another task as a dependency. The solver guarantees the dependent task starts only after its prerequisite finishes. If the prerequisite can't be scheduled, the dependent task goes to backlog too.

### Duration Learning
After completing a task, call `POST /tasks/complete` with the actual duration. Once 5+ entries are logged, call `train_duration_model()` (or trigger it manually) to train the ML model. Future duration suggestions in the task editor will be based on your real completion history.

### Deadline-Today Flagging
If a task has a deadline within today's schedulable window but can't fit due to overflow, it appears in the backlog with a red "MISSED" label and `is_deadline_today: true`. When time frees up (e.g. an event is cancelled), the solver automatically rescues it into the schedule.

---

## Optional Configuration

### LLM-based task parsing (OpenAI)

```bash
# Set before starting the backend
export OPENAI_API_KEY=sk-...
```

Without this, the heuristic parser is used automatically — no degraded functionality.

### Changing the backend port

If port 5000 is in use, start on a different port and update the frontend:

```bash
uvicorn app.main:app --reload --port 8080
```

Then edit `frontend/src/app/services/schedule.service.ts`:
```typescript
const API = 'http://localhost:8080';
```

---

## GitHub Actions

Three workflows run automatically:

| Workflow | Trigger | What it does |
|---|---|---|
| `backend-ci.yml` | Push/PR to `backend/**` | Runs pytest on Python 3.11 + 3.12 |
| `frontend-ci.yml` | Push/PR to `frontend/**` | Builds dev + production bundles |
| `pr-check.yml` | Every PR to `main`/`develop` | Runs both in parallel; blocks merge if either fails |

---

## Further Reading

For a complete A–Z explanation of every component, every design decision, and every edge case scenario, see [`FLOWDAY_PROJECT_DOCUMENT.md`](./FLOWDAY_PROJECT_DOCUMENT.md).

---

## Quick Reference

```bash
# Terminal 1 — backend
cd backend
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
uvicorn app.main:app --reload --port 5000

# Terminal 2 — frontend
cd frontend
npm start

# Tests (backend terminal)
pytest tests/ -v

# Swagger UI
open http://localhost:5000/docs

# App
open http://localhost:4200
```
