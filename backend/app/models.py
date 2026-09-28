from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator

class FixedEvent(BaseModel):
    """
    A calendar event with a fixed start and end time that cannot be moved.
    The solver treats these as hard blocked intervals.
    """

    id: str
    title: str
    start_time: int = Field(..., ge=0, lt=1440, description="Minutes since midnight")
    end_time: int = Field(..., ge=1, le=1440, description="Minutes since midnight")

    @model_validator(mode="after")
    def end_after_start(self) -> "FixedEvent":
        if self.end_time <= self.start_time:
            raise ValueError(
                f"end_time ({self.end_time}) must be greater than "
                f"start_time ({self.start_time})"
            )
        return self


class FlexibleTask(BaseModel):
    """
    A task that needs to be scheduled by the solver within a given day.
    The solver assigns start_time based on duration, priority, and constraints.
    """

    id: str
    title: str
    duration: int = Field(..., gt=0, description="Required duration in minutes")
    priority: int = Field(..., ge=1, description="Higher value = more important")
    deadline: Optional[int] = Field(
        default=None,
        ge=1,
        le=1440,
        description="Must finish by this time (minutes since midnight); None = no deadline",
    )
    earliest_start: Optional[int] = Field(
        default=None,
        ge=0,
        lt=1440,
        description="Cannot start before this time (minutes since midnight)",
    )
    latest_end: Optional[int] = Field(
        default=None,
        ge=1,
        le=1440,
        description="Must end by this time (minutes since midnight)",
    )
    status: Literal["scheduled", "backlog"] = "backlog"
    start_time: Optional[int] = Field(
        default=None,
        ge=0,
        lt=1440,
        description="Assigned by solver; None until scheduled",
    )
    is_deadline_today: bool = Field(
        default=False,
        description=(
            "Set by the solver after solving. True when the task is in backlog "
            "AND its deadline falls within the day being solved — indicating "
            "it was due today but could not be placed. Always False for "
            "scheduled tasks and for backlog tasks with no deadline."
        ),
    )
    actual_duration: Optional[int] = Field(
        default=None,
        gt=0,
        description=(
            "Re-estimated total duration set during a task_overrun disruption. "
            "When set, replaces `duration` as the effective length of the task "
            "for the purpose of calculating its end time and blocking future tasks. "
            "Represents the full duration from the original start_time to the "
            "new estimated finish (i.e. new_estimated_end - start_time). "
            "None means no overrun — use `duration` as normal."
        ),
    )
    depends_on: Optional[str] = Field(
        default=None,
        description=(
            "ID of another FlexibleTask that must finish before this task can start. "
            "The solver enforces: start_time(this) >= start_time(dependency) + duration(dependency). "
            "If the dependency goes to backlog, this task also goes to backlog — "
            "it cannot be scheduled without its prerequisite."
        ),
    )

    @property
    def effective_duration(self) -> int:
        """Duration used for scheduling: actual_duration if set, else duration."""
        return self.actual_duration if self.actual_duration is not None else self.duration

    @model_validator(mode="after")
    def validate_time_window(self) -> "FlexibleTask":
        # earliest_start + duration must not exceed latest_end
        if self.earliest_start is not None and self.latest_end is not None:
            if self.earliest_start >= self.latest_end:
                raise ValueError(
                    f"earliest_start ({self.earliest_start}) must be less than "
                    f"latest_end ({self.latest_end})"
                )
            if self.latest_end - self.earliest_start < self.duration:
                raise ValueError(
                    f"Time window ({self.latest_end - self.earliest_start} min) "
                    f"is too narrow for duration ({self.duration} min)"
                )

        # deadline and latest_end should be consistent if both are set
        if self.deadline is not None and self.latest_end is not None:
            if self.latest_end > self.deadline:
                raise ValueError(
                    f"latest_end ({self.latest_end}) cannot be after "
                    f"deadline ({self.deadline})"
                )

        # status/start_time consistency
        if self.status == "scheduled" and self.start_time is None:
            raise ValueError("A task with status 'scheduled' must have a start_time.")
        if self.status == "backlog" and self.start_time is not None:
            raise ValueError("A task with status 'backlog' should not have a start_time.")

        return self


class DaySchedule(BaseModel):
    """
    The full schedule for a single day, combining fixed events and flexible tasks.
    Passed to the solver and returned as the solved schedule.
    """

    date: str = Field(..., description="ISO 8601 date string, e.g. '2026-09-24'")
    day_start: int = Field(
        ..., ge=0, lt=1440, description="Earliest schedulable time (minutes since midnight)"
    )
    day_end: int = Field(
        ..., ge=1, le=1440, description="Latest schedulable time (minutes since midnight)"
    )
    fixed_events: list[FixedEvent] = Field(default_factory=list)
    flexible_tasks: list[FlexibleTask] = Field(default_factory=list)

    @model_validator(mode="after")
    def day_end_after_day_start(self) -> "DaySchedule":
        if self.day_end <= self.day_start:
            raise ValueError(
                f"day_end ({self.day_end}) must be greater than "
                f"day_start ({self.day_start})"
            )
        return self

    @model_validator(mode="after")
    def events_within_day_bounds(self) -> "DaySchedule":
        for event in self.fixed_events:
            if event.start_time < self.day_start or event.end_time > self.day_end:
                raise ValueError(
                    f"FixedEvent '{event.title}' [{event.start_time}–{event.end_time}] "
                    f"falls outside day bounds [{self.day_start}–{self.day_end}]"
                )
        return self


class WeekSchedule(BaseModel):
    """
    A full 7-day schedule, Monday through Sunday.
    `days` should contain exactly 7 DaySchedule objects in ISO date order.
    """

    week_start_date: str = Field(
        ...,
        description="ISO 8601 date of Monday, e.g. '2026-09-28'",
    )
    days: list[DaySchedule] = Field(
        ...,
        description="7 DaySchedule objects, Monday (index 0) through Sunday (index 6)",
    )

    @model_validator(mode="after")
    def exactly_seven_days(self) -> "WeekSchedule":
        if len(self.days) != 7:
            raise ValueError(
                f"WeekSchedule must contain exactly 7 days, got {len(self.days)}"
            )
        return self


class DisruptDayResponse(BaseModel):
    """
    Response body for POST /schedule/disrupt.
    Bundles the updated DaySchedule with plain-English change explanations.
    """
    schedule:     DaySchedule
    explanations: list[str] = Field(
        default_factory=list,
        description="Plain-English lines describing what changed and why.",
    )


class DisruptWeekResponse(BaseModel):
    """
    Response body for POST /schedule/week/disrupt.
    Bundles the updated WeekSchedule with plain-English change explanations
    for the day that was disrupted.
    """
    schedule:     WeekSchedule
    explanations: list[str] = Field(
        default_factory=list,
        description="Plain-English lines describing what changed in the disrupted day.",
    )
