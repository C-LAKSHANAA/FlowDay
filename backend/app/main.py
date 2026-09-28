"""
main.py

FlowDay FastAPI application.

Run with:
    uvicorn app.main:app --reload --port 5000

Endpoints:
    GET  /                        — health check
    GET  /schedule/demo           — solve the dummy fixture, return a DaySchedule
    GET  /schedule/week/demo      — solve the dummy week fixture, return a WeekSchedule
    POST /schedule/solve          — validate + solve a user-submitted DaySchedule
    POST /schedule/check          — auto-detect overruns at current_time
    POST /schedule/disrupt        — apply a disruption; returns schedule + explanations
    POST /schedule/week/disrupt   — apply a disruption to one day; returns week + explanations
    POST /tasks/complete          — log a completed task
    GET  /tasks/completion-log    — return all completion log entries
    GET  /tasks/predict-duration  — ML-based duration prediction
    POST /tasks/parse             — parse free-text into structured task fields
    GET  /docs                    — Swagger UI
"""

from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.fixtures import get_dummy_schedule, get_dummy_week_schedule
from app.models import (
    DaySchedule,
    DisruptDayResponse,
    DisruptWeekResponse,
    TaskCompleteRequest,
    TaskCompletionLog,
    WeekSchedule,
)
from app.persistence import append_completion, read_all_completions
from app.duration_model import predict_duration
from app.task_parser import parse_task_text
from app.solver import (
    detect_and_apply_overruns,
    generate_explanation,
    solve_schedule,
    solve_week,
    trigger_disruption,
)
from app.validation import validate_day_schedule, validate_fixed_events

app = FastAPI(title="FlowDay", version="0.1.0")

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://localhost:5000",
        "https://c-lakshanaa.github.io",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class EventOverrunDisruption(BaseModel):
    """Disruption: a fixed event has run over its scheduled end time (single day)."""

    type: Literal["event_overrun"]
    event_id: str = Field(..., description="ID of the FixedEvent that overran")
    new_end_time: int = Field(
        ..., ge=1, le=1440,
        description="New end time in minutes since midnight",
    )


class WeekDisruption(BaseModel):
    """Disruption scoped to a specific day within a WeekSchedule."""

    day_date: str = Field(..., description="ISO date of the day to disrupt, e.g. '2026-09-30'")
    type: Literal["event_overrun"]
    event_id: str = Field(..., description="ID of the FixedEvent that overran")
    new_end_time: int = Field(
        ..., ge=1, le=1440,
        description="New end time in minutes since midnight",
    )


class CheckRequest(BaseModel):
    """
    Request body for GET /schedule/check.

    The caller supplies the current solved schedule and a ``current_time``
    (minutes since midnight) representing "now".  The endpoint compares
    current_time against every fixed event and scheduled flexible task and
    automatically applies any overruns it detects.
    """

    schedule:     DaySchedule = Field(..., description="The current solved DaySchedule.")
    current_time: int = Field(
        ..., ge=0, le=1440,
        description="Current wall-clock time in minutes since midnight.",
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _validation_error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", tags=["health"])
def root():
    """Basic health check."""
    return {"status": "ok", "app": "FlowDay"}


@app.get("/schedule/demo", response_model=DaySchedule, tags=["schedule"])
def schedule_demo():
    """Solve the dummy single-day fixture and return the DaySchedule."""
    return solve_schedule(get_dummy_schedule())


@app.get("/schedule/week/demo", response_model=WeekSchedule, tags=["schedule"])
def schedule_week_demo():
    """Solve the dummy week fixture and return all 7 solved DaySchedules."""
    return solve_week(get_dummy_week_schedule())


@app.post("/schedule/solve", response_model=DaySchedule, tags=["schedule"])
def schedule_solve(schedule: DaySchedule):
    """
    Validate and solve a user-submitted DaySchedule.

    Returns the solved DaySchedule with start_time assigned to each
    schedulable task.
    """
    try:
        validate_day_schedule(schedule)
    except ValueError as exc:
        raise _validation_error(exc) from exc

    return solve_schedule(schedule)


@app.post("/schedule/check", response_model=DisruptDayResponse, tags=["schedule"])
def schedule_check(body: CheckRequest):
    """
    Automatically detect and apply overruns that occurred by ``current_time``.

    The caller provides the current solved schedule and a ``current_time``
    (minutes since midnight).  The endpoint scans for:

    - **FixedEvent overruns** — events whose ``end_time`` has been passed
      without an explicit disruption being filed.  Treated as still running
      until ``current_time``.
    - **FlexibleTask overruns** — scheduled tasks whose expected finish has
      been passed but have no ``actual_duration`` recorded (i.e. they were
      never marked done or updated).  Treated as overrunning until
      ``current_time``.

    Each detected overrun is applied via ``trigger_disruption()`` exactly as
    if the user had submitted it manually.  Disruptions are applied in order
    (fixed events first, then tasks), each building on the previous result.

    If no overruns are detected the original schedule is returned unchanged
    with an empty ``explanations`` list — this makes it safe to poll
    periodically.

    Returns
    -------
    schedule     : The updated DaySchedule (unchanged if no overruns found).
    explanations : Plain-English lines for every overrun that was applied.
    """
    try:
        updated, explanations = detect_and_apply_overruns(
            body.schedule, body.current_time
        )
        return DisruptDayResponse(schedule=updated, explanations=explanations)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/schedule/disrupt", response_model=DisruptDayResponse, tags=["schedule"])
def schedule_disrupt(disruption: EventOverrunDisruption):
    """
    Apply an event_overrun disruption to the demo single-day schedule.

    Returns
    -------
    schedule     : The updated DaySchedule after re-solving.
    explanations : Plain-English lines describing what moved and why.
    """
    try:
        solved = solve_schedule(get_dummy_schedule())

        updated_events = [
            e.model_copy(update={"end_time": disruption.new_end_time})
            if e.id == disruption.event_id else e
            for e in solved.fixed_events
        ]
        try:
            validate_fixed_events(updated_events)
        except ValueError as exc:
            raise _validation_error(exc) from exc

        disruption_dict = disruption.model_dump()
        result = trigger_disruption(solved, disruption_dict)
        explanations = generate_explanation(solved, result, disruption_dict)

        return DisruptDayResponse(schedule=result, explanations=explanations)

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/schedule/week/disrupt", response_model=DisruptWeekResponse, tags=["schedule"])
def schedule_week_disrupt(disruption: WeekDisruption):
    """
    Apply an event_overrun disruption to a single day within the demo week schedule.

    Only the targeted day is re-solved; all other days are returned unchanged.

    Returns
    -------
    schedule     : The full updated WeekSchedule.
    explanations : Plain-English lines describing changes in the disrupted day.
    """
    try:
        week = solve_week(get_dummy_week_schedule())

        target_index = next(
            (i for i, d in enumerate(week.days) if d.date == disruption.day_date),
            None,
        )
        if target_index is None:
            raise HTTPException(
                status_code=404,
                detail=f"No day with date '{disruption.day_date}' found in week schedule.",
            )

        target_day = week.days[target_index]

        updated_events = [
            e.model_copy(update={"end_time": disruption.new_end_time})
            if e.id == disruption.event_id else e
            for e in target_day.fixed_events
        ]
        try:
            validate_fixed_events(updated_events)
        except ValueError as exc:
            raise _validation_error(exc) from exc

        day_disruption = {
            "type":         disruption.type,
            "event_id":     disruption.event_id,
            "new_end_time": disruption.new_end_time,
        }
        updated_day = trigger_disruption(target_day, day_disruption)
        explanations = generate_explanation(target_day, updated_day, day_disruption)

        new_days = list(week.days)
        new_days[target_index] = updated_day

        updated_week = week.model_copy(update={"days": new_days})
        return DisruptWeekResponse(schedule=updated_week, explanations=explanations)

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Task completion endpoints
# ---------------------------------------------------------------------------

@app.post("/tasks/complete", response_model=TaskCompletionLog, tags=["tasks"])
def task_complete(body: TaskCompleteRequest):
    """
    Mark a flexible task as complete and log the actual vs estimated duration.

    The endpoint looks up the task's ``estimated_duration`` by searching the
    current solved demo week schedule for a task matching ``body.task_id``.

    Steps
    -----
    1. Solve the demo week to get the current schedule.
    2. Find the FlexibleTask whose ``id == body.task_id``.
    3. Build a ``TaskCompletionLog`` entry with estimated and actual durations.
    4. Append it to ``backend/data/completion_log.json``.
    5. Return the written log entry (including the auto-set ``completed_at``).

    Raises
    ------
    404  Task id not found in the current demo week schedule.
    """
    week = solve_week(get_dummy_week_schedule())

    # Search all days for the task
    found_task = None
    for day in week.days:
        for t in day.flexible_tasks:
            if t.id == body.task_id:
                found_task = t
                break
        if found_task:
            break

    if found_task is None:
        raise HTTPException(
            status_code=404,
            detail=f"No FlexibleTask with id='{body.task_id}' found in the current schedule.",
        )

    entry = TaskCompletionLog(
        task_id=            found_task.id,
        task_title=         found_task.title,
        estimated_duration= found_task.duration,
        actual_duration=    body.actual_duration,
        category=           body.category,
    )

    return append_completion(entry)


@app.get("/tasks/completion-log", response_model=list[TaskCompletionLog], tags=["tasks"])
def get_completion_log():
    """
    Return all task completion log entries in chronological order.
    """
    return read_all_completions()


@app.get("/tasks/predict-duration", tags=["tasks"])
def get_predicted_duration(
    category: str = "",
    estimated_duration: int = 60,
):
    """
    Return a predicted actual duration for a task based on past log data.

    Query parameters
    ----------------
    category           : Task category string (e.g. "reading", "assignment").
                         Empty string is valid — treated as uncategorised.
    estimated_duration : The user's own estimate in minutes.  Used as the
                         primary feature and as the cold-start fallback.

    Response
    --------
    {
        "predicted_duration": int,   // minutes
        "is_model_based": bool,      // false = cold-start fallback
        "message": str               // human-readable label for the UI
    }

    When no model has been trained yet (cold start), returns
    ``estimated_duration`` unchanged with ``is_model_based: false``.
    """
    from app.duration_model import MODEL_FILE

    predicted = predict_duration(
        category=category,
        estimated_duration=estimated_duration,
    )

    is_model_based = MODEL_FILE.exists()

    if is_model_based and predicted != estimated_duration:
        message = (
            f"Suggested: {predicted} min, based on past similar tasks"
            + (f" in '{category}'" if category else "")
            + "."
        )
    elif is_model_based:
        message = f"No adjustment needed — {predicted} min matches your past average."
    else:
        message = "No past data yet — using your estimate as-is."

    return {
        "predicted_duration": predicted,
        "is_model_based":     is_model_based,
        "message":            message,
    }


class TaskParseRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500,
                      description="Free-text task description to parse.")


@app.post("/tasks/parse", tags=["tasks"])
def task_parse(body: TaskParseRequest):
    """
    Parse a free-text task description into structured FlexibleTask fields.

    Uses an LLM (OpenAI) when ``OPENAI_API_KEY`` env var is set; falls back
    to a lightweight heuristic parser so the endpoint always works without
    an API key.

    The response is a suggestion only — the frontend pre-fills the task
    creation form with these values and the user must confirm before the
    task is added to the schedule.

    Returns a dict with these fields (null when not inferable):
        title, duration, deadline, priority, category,
        earliest_start, latest_end, parser_used

    Raises HTTP 422 if the LLM returns malformed JSON.
    """
    parser_used = "llm" if __import__("os").environ.get("OPENAI_API_KEY") else "heuristic"

    try:
        result = parse_task_text(body.text)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Could not parse task description: {exc}",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    result["parser_used"] = parser_used
    return result
