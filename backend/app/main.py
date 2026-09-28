"""
main.py

FlowDay FastAPI application.

Run with:
    uvicorn app.main:app --reload --port 5000

Endpoints:
    GET  /                      — health check
    GET  /schedule/demo         — solve the dummy fixture, return a DaySchedule
    GET  /schedule/week/demo    — solve the dummy week fixture, return a WeekSchedule
    POST /schedule/solve        — validate + solve a user-submitted DaySchedule
    POST /schedule/check        — auto-detect overruns at current_time; returns updated schedule
    POST /schedule/disrupt      — apply a disruption; returns schedule + explanations
    POST /schedule/week/disrupt — apply a disruption to one day; returns week + explanations
    GET  /docs                  — Swagger UI
"""

from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.fixtures import get_dummy_schedule, get_dummy_week_schedule
from app.models import DaySchedule, DisruptDayResponse, DisruptWeekResponse, WeekSchedule
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
    allow_origins=["http://localhost:4200", "http://localhost:5000"],
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
