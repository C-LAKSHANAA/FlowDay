"""
tests/test_solver.py

Self-contained pytest suite for the FlowDay CP-SAT solver.

Each test builds its own minimal DaySchedule inline so failures are
easy to diagnose without cross-test dependencies.  No reliance on
fixtures.py is required (though the same models are used).

Run with:
    pytest backend/tests/           (from repo root)
    pytest tests/                   (from backend/)
"""

import pytest

from app.models import DaySchedule, FixedEvent, FlexibleTask
from app.solver import solve_schedule, trigger_disruption
from app.validation import validate_day_schedule, validate_fixed_events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def day(
    date: str = "2026-01-01",
    day_start: int = 360,      # 6:00 AM
    day_end: int = 1380,       # 11:00 PM
    fixed_events=None,
    flexible_tasks=None,
) -> DaySchedule:
    """Convenience factory — keeps test bodies short."""
    return DaySchedule(
        date=date,
        day_start=day_start,
        day_end=day_end,
        fixed_events=fixed_events or [],
        flexible_tasks=flexible_tasks or [],
    )


def task(
    id: str,
    title: str = "",
    duration: int = 60,
    priority: int = 5,
    deadline: int | None = None,
    earliest_start: int | None = None,
    latest_end: int | None = None,
) -> FlexibleTask:
    return FlexibleTask(
        id=id,
        title=title or id,
        duration=duration,
        priority=priority,
        deadline=deadline,
        earliest_start=earliest_start,
        latest_end=latest_end,
    )


def event(id: str, title: str, start: int, end: int) -> FixedEvent:
    return FixedEvent(id=id, title=title, start_time=start, end_time=end)


def scheduled(result: DaySchedule) -> list[FlexibleTask]:
    return [t for t in result.flexible_tasks if t.status == "scheduled"]


def backlogged(result: DaySchedule) -> list[FlexibleTask]:
    return [t for t in result.flexible_tasks if t.status == "backlog"]


# ---------------------------------------------------------------------------
# 1. test_comfortable_fit
#    All tasks get scheduled when there is ample free time.
# ---------------------------------------------------------------------------

def test_comfortable_fit():
    schedule = day(
        flexible_tasks=[
            task("t1", duration=30, priority=7),
            task("t2", duration=60, priority=5),
            task("t3", duration=45, priority=6),
        ]
    )
    result = solve_schedule(schedule)

    assert len(scheduled(result)) == 3, "All 3 tasks should be scheduled"
    assert len(backlogged(result)) == 0


# ---------------------------------------------------------------------------
# 2. test_tight_fit
#    All tasks fit when the total duration exactly fills the available window
#    (no fixed events, tasks collectively use the whole day).
# ---------------------------------------------------------------------------

def test_tight_fit():
    # Window: 09:00-12:00 (180 min), tasks total exactly 180 min
    schedule = day(
        day_start=540,
        day_end=720,
        flexible_tasks=[
            task("t1", duration=60, priority=9),
            task("t2", duration=60, priority=8),
            task("t3", duration=60, priority=7),
        ],
    )
    result = solve_schedule(schedule)

    assert len(scheduled(result)) == 3, "All tasks should fit exactly"
    assert len(backlogged(result)) == 0


# ---------------------------------------------------------------------------
# 3. test_overflow_priority
#    When tasks overflow available time, lower-priority tasks go to backlog.
# ---------------------------------------------------------------------------

def test_overflow_priority():
    # Window: 09:00-10:00 (60 min), two tasks each 60 min → only one fits
    schedule = day(
        day_start=540,
        day_end=600,
        flexible_tasks=[
            task("hi", duration=60, priority=9),
            task("lo", duration=60, priority=3),
        ],
    )
    result = solve_schedule(schedule)

    sched_ids   = {t.id for t in scheduled(result)}
    backlog_ids = {t.id for t in backlogged(result)}

    assert "hi" in sched_ids,   "High-priority task should be scheduled"
    assert "lo" in backlog_ids, "Low-priority task should be in backlog"


# ---------------------------------------------------------------------------
# 4. test_impossible_single_task
#    A task longer than any available gap goes to backlog — no crash.
# ---------------------------------------------------------------------------

def test_impossible_single_task():
    # Fixed event fills the whole window, leaving 0 free minutes
    schedule = day(
        day_start=540,
        day_end=720,
        fixed_events=[event("e1", "All-day block", 540, 720)],
        flexible_tasks=[task("t1", duration=60, priority=8)],
    )
    result = solve_schedule(schedule)

    assert len(scheduled(result)) == 0,  "No room — task should not be scheduled"
    assert len(backlogged(result)) == 1, "Task should be in backlog"


# ---------------------------------------------------------------------------
# 5. test_deadline_respected
#    No task is ever placed such that start_time + duration > deadline.
# ---------------------------------------------------------------------------

def test_deadline_respected():
    schedule = day(
        day_start=360,
        day_end=1380,
        flexible_tasks=[
            task("t1", duration=60, priority=8, deadline=600),   # must end by 10:00
            task("t2", duration=90, priority=6, deadline=780),   # must end by 13:00
            task("t3", duration=30, priority=9, deadline=420),   # must end by 07:00
        ],
    )
    result = solve_schedule(schedule)

    for t in scheduled(result):
        assert t.start_time + t.duration <= t.deadline, (
            f"Task '{t.id}' violates deadline: "
            f"ends at {t.start_time + t.duration}, deadline={t.deadline}"
        )


# ---------------------------------------------------------------------------
# 6. test_window_respected
#    No task placed before earliest_start or ending after latest_end.
# ---------------------------------------------------------------------------

def test_window_respected():
    schedule = day(
        day_start=360,
        day_end=1380,
        flexible_tasks=[
            task("t1", duration=60, priority=7,
                 earliest_start=720, latest_end=900),   # 12:00-15:00 window
            task("t2", duration=30, priority=8,
                 earliest_start=480, latest_end=600),   # 08:00-10:00 window
        ],
    )
    result = solve_schedule(schedule)

    for t in scheduled(result):
        if t.earliest_start is not None:
            assert t.start_time >= t.earliest_start, (
                f"Task '{t.id}' starts before earliest_start "
                f"({t.start_time} < {t.earliest_start})"
            )
        if t.latest_end is not None:
            assert t.start_time + t.duration <= t.latest_end, (
                f"Task '{t.id}' ends after latest_end "
                f"({t.start_time + t.duration} > {t.latest_end})"
            )


# ---------------------------------------------------------------------------
# 7. test_fully_booked_day
#    Fixed events fill the day; all flexible tasks go to backlog — no crash.
# ---------------------------------------------------------------------------

def test_fully_booked_day():
    # Two fixed events cover the whole 09:00-17:00 window with no gaps
    schedule = day(
        day_start=540,
        day_end=1020,
        fixed_events=[
            event("e1", "Morning block", 540, 780),   # 09:00-13:00
            event("e2", "Afternoon block", 780, 1020), # 13:00-17:00
        ],
        flexible_tasks=[
            task("t1", duration=30, priority=9),
            task("t2", duration=60, priority=7),
        ],
    )
    result = solve_schedule(schedule)

    assert len(scheduled(result)) == 0,  "No free time — nothing should be scheduled"
    assert len(backlogged(result)) == 2, "Both tasks should be in backlog"


# ---------------------------------------------------------------------------
# 8. test_single_disruption_reflow
#    A single event_overrun produces a valid re-solved schedule.
# ---------------------------------------------------------------------------

def test_single_disruption_reflow():
    schedule = day(
        day_start=540,
        day_end=1080,
        fixed_events=[
            event("e1", "Morning meeting", 540, 600),  # 09:00-10:00
        ],
        flexible_tasks=[
            task("t1", duration=60, priority=8),
            task("t2", duration=90, priority=6),
        ],
    )
    solved = solve_schedule(schedule)

    disrupted = trigger_disruption(
        solved,
        {"type": "event_overrun", "event_id": "e1", "new_end_time": 660},  # +1hr
    )

    # Result must be valid: no overlaps, no out-of-bounds
    _assert_no_overlaps(disrupted)
    _assert_within_bounds(disrupted)


# ---------------------------------------------------------------------------
# 9. test_cascading_disruptions
#    Two disruptions applied in sequence both produce valid results.
# ---------------------------------------------------------------------------

def test_cascading_disruptions():
    schedule = day(
        day_start=540,
        day_end=1080,
        fixed_events=[
            event("e1", "Meeting A", 540, 600),
            event("e2", "Meeting B", 720, 780),
        ],
        flexible_tasks=[
            task("t1", duration=60, priority=8),
            task("t2", duration=60, priority=6),
            task("t3", duration=60, priority=4),
        ],
    )

    step1 = solve_schedule(schedule)
    _assert_no_overlaps(step1)

    step2 = trigger_disruption(
        step1,
        {"type": "event_overrun", "event_id": "e1", "new_end_time": 660},
    )
    _assert_no_overlaps(step2)
    _assert_within_bounds(step2)

    step3 = trigger_disruption(
        step2,
        {"type": "event_overrun", "event_id": "e2", "new_end_time": 840},
    )
    _assert_no_overlaps(step3)
    _assert_within_bounds(step3)


# ---------------------------------------------------------------------------
# 10. test_tie_break_determinism
#     Same priority + deadline → shorter task preferred, consistently.
# ---------------------------------------------------------------------------

def test_tie_break_determinism():
    # 120-min window, two tasks with same priority + deadline, different durations
    schedule = day(
        day_start=540,
        day_end=660,
        flexible_tasks=[
            task("short", duration=60, priority=7, deadline=660),
            task("long",  duration=90, priority=7, deadline=660),
        ],
    )

    results = [solve_schedule(schedule) for _ in range(5)]

    # All runs must agree
    scheduled_ids_per_run = [
        frozenset(t.id for t in r.flexible_tasks if t.status == "scheduled")
        for r in results
    ]
    assert len(set(scheduled_ids_per_run)) == 1, (
        "Solver is non-deterministic across runs"
    )

    # Shorter task must win
    winner_ids = scheduled_ids_per_run[0]
    assert "short" in winner_ids, "Shorter task should be scheduled"
    assert "long" not in winner_ids, "Longer task should be in backlog"


# ---------------------------------------------------------------------------
# 11. test_overlapping_fixed_events_rejected
#     validate_fixed_events raises before the solver is called.
# ---------------------------------------------------------------------------

def test_overlapping_fixed_events_rejected():
    overlapping = [
        event("e1", "Block A", 600, 690),
        event("e2", "Block B", 660, 750),  # overlaps with e1
    ]
    with pytest.raises(ValueError, match="overlap"):
        validate_fixed_events(overlapping)


# ---------------------------------------------------------------------------
# 12. test_self_contradictory_task_rejected
#     Validation raises for a task whose deadline < earliest_start.
# ---------------------------------------------------------------------------

def test_self_contradictory_task_rejected():
    from app.validation import validate_flexible_task

    bad_task = FlexibleTask(
        id="bad",
        title="Impossible task",
        duration=30,
        priority=5,
        earliest_start=720,   # 12:00 PM
        deadline=600,         # 10:00 AM — before earliest_start
    )
    with pytest.raises(ValueError, match="deadline"):
        validate_flexible_task(bad_task)


# ---------------------------------------------------------------------------
# 13. test_in_progress_task_not_moved
#     An in-progress task's start_time is never changed by a disruption.
# ---------------------------------------------------------------------------

def test_in_progress_task_not_moved():
    schedule = day(
        day_start=480,
        day_end=1200,
        fixed_events=[
            event("e1", "Meeting", 600, 660),   # 10:00-11:00
        ],
        flexible_tasks=[
            task("inprog", duration=60, priority=7),   # will land before 10:00
            task("future", duration=60, priority=6),   # will land after 11:00
        ],
    )
    solved = solve_schedule(schedule)

    # Find the in-progress task — pick whichever starts first
    sorted_tasks = sorted(
        [t for t in solved.flexible_tasks if t.status == "scheduled"],
        key=lambda t: t.start_time,
    )
    in_prog_task = sorted_tasks[0]
    original_start = in_prog_task.start_time

    # current_time: task is in-progress (started but not finished)
    current_time = in_prog_task.start_time + in_prog_task.duration // 2

    disrupted = trigger_disruption(
        solved,
        {"type": "event_overrun", "event_id": "e1", "new_end_time": 720},
        current_time=current_time,
    )

    after = next(t for t in disrupted.flexible_tasks if t.id == in_prog_task.id)
    assert after.start_time == original_start, (
        f"In-progress task start_time changed: "
        f"{original_start} -> {after.start_time}"
    )


# ---------------------------------------------------------------------------
# 14. test_backlog_rescue
#     A backlogged task gets scheduled when a disruption frees enough time.
# ---------------------------------------------------------------------------

def test_backlog_rescue():
    # Window: 09:00-12:00 (180 min)
    # Fixed event blocks 09:00-11:00 (120 min) → 60 min free
    # Two tasks each 60 min → one goes to backlog initially
    schedule = day(
        day_start=540,
        day_end=720,
        fixed_events=[
            event("e1", "Block", 540, 660),   # 09:00-11:00 (120 min)
        ],
        flexible_tasks=[
            task("t1", duration=60, priority=8),
            task("t2", duration=60, priority=6),
        ],
    )
    solved = solve_schedule(schedule)

    assert any(t.status == "backlog" for t in solved.flexible_tasks), (
        "At least one task should be in backlog initially"
    )

    backlog_ids_before = {t.id for t in solved.flexible_tasks if t.status == "backlog"}

    # Cancel the fixed event — frees 120 min, now both tasks fit
    rescued = trigger_disruption(
        solved,
        {"type": "event_cancelled", "event_id": "e1"},
    )

    rescued_tasks = [
        t for t in rescued.flexible_tasks
        if t.id in backlog_ids_before and t.status == "scheduled"
    ]
    assert len(rescued_tasks) >= 1, (
        "Previously-backlogged task should be scheduled after event cancellation"
    )


# ---------------------------------------------------------------------------
# 15. test_day_shrink
#     Tasks that can't fit before the new day_end fall to backlog.
# ---------------------------------------------------------------------------

def test_day_shrink():
    # Window: 09:00-18:00 (540 min), shrink to 09:00-10:00 (60 min)
    # Only a 60-min task fits; the 120-min task cannot
    schedule = day(
        day_start=540,
        day_end=1080,
        flexible_tasks=[
            task("short", duration=60,  priority=8),
            task("long",  duration=120, priority=6),
        ],
    )
    solved = solve_schedule(schedule)

    # Both should be scheduled in the full-day version
    assert len(scheduled(solved)) == 2

    # Shrink to only 60 min of space
    shrunken = trigger_disruption(
        solved,
        {"type": "day_shrink", "new_day_end": 600},   # 09:00-10:00
    )

    assert shrunken.day_end == 600, "day_end should be updated to new value"

    # No task scheduled past the new cutoff
    for t in scheduled(shrunken):
        end = t.start_time + t.effective_duration
        assert end <= 600, (
            f"Task '{t.id}' scheduled past new day_end: ends at {end}"
        )

    # The 120-min task cannot fit in 60 min → must be in backlog
    long_task = next(t for t in shrunken.flexible_tasks if t.id == "long")
    assert long_task.status == "backlog", (
        "120-min task should be in backlog when only 60 min remain"
    )


# ---------------------------------------------------------------------------
# Shared assertion helpers
# ---------------------------------------------------------------------------

def _assert_no_overlaps(result: DaySchedule) -> None:
    """All scheduled tasks and fixed events must be non-overlapping."""
    # Build unified interval list
    intervals: list[tuple[int, int, str]] = []

    for e in result.fixed_events:
        if not e.id.startswith("_locked_"):
            intervals.append((e.start_time, e.end_time, f"event:{e.id}"))

    for t in result.flexible_tasks:
        if t.status == "scheduled" and t.start_time is not None:
            intervals.append((
                t.start_time,
                t.start_time + t.effective_duration,
                f"task:{t.id}",
            ))

    intervals.sort()
    for i in range(len(intervals) - 1):
        a_start, a_end, a_name = intervals[i]
        b_start, b_end, b_name = intervals[i + 1]
        assert a_end <= b_start, (
            f"Overlap between {a_name} [{a_start}-{a_end}] "
            f"and {b_name} [{b_start}-{b_end}]"
        )


def _assert_within_bounds(result: DaySchedule) -> None:
    """All scheduled tasks must start >= day_start and end <= day_end."""
    for t in result.flexible_tasks:
        if t.status == "scheduled" and t.start_time is not None:
            assert t.start_time >= result.day_start, (
                f"Task '{t.id}' starts before day_start "
                f"({t.start_time} < {result.day_start})"
            )
            assert t.start_time + t.effective_duration <= result.day_end, (
                f"Task '{t.id}' ends after day_end "
                f"({t.start_time + t.effective_duration} > {result.day_end})"
            )


# ---------------------------------------------------------------------------
# 16. test_dependency_ordering
#     Task B (depends_on A) is never scheduled before A finishes.
# ---------------------------------------------------------------------------

def test_dependency_ordering():
    """B must start no earlier than A's end time when both are scheduled."""
    schedule = day(
        day_start=540,
        day_end=780,   # 240 min — plenty of room for both
        flexible_tasks=[
            task("A", title="Prerequisite", duration=60, priority=7),
            task("B", title="Dependent",    duration=60, priority=8),
        ],
    )
    # Manually add depends_on (not in the helper to keep it simple)
    tasks_with_dep = [
        schedule.flexible_tasks[0],
        schedule.flexible_tasks[1].model_copy(update={"depends_on": "A"}),
    ]
    schedule = schedule.model_copy(update={"flexible_tasks": tasks_with_dep})

    result = solve_schedule(schedule)

    task_map = {t.id: t for t in result.flexible_tasks}
    a = task_map["A"]
    b = task_map["B"]

    assert a.status == "scheduled", "Task A should be scheduled"
    assert b.status == "scheduled", "Task B should be scheduled (room available)"
    assert b.start_time >= a.start_time + a.duration, (
        f"Task B ({b.start_time}) must start after A finishes "
        f"({a.start_time + a.duration})"
    )


# ---------------------------------------------------------------------------
# 17. test_dependency_cascade_to_backlog
#     If dependency A goes to backlog, B must also go to backlog.
# ---------------------------------------------------------------------------

def test_dependency_cascade_to_backlog():
    """
    Window: only 60 min.
    Task C (p=9) wins the slot.
    Task A (p=5) goes to backlog — lower priority.
    Task B (p=8, depends_on A) must also go to backlog even though its
    priority would otherwise be high enough to displace A.
    """
    from app.fixtures import get_dependency_overflow_schedule

    result = solve_schedule(get_dependency_overflow_schedule())
    task_map = {t.id: t for t in result.flexible_tasks}

    c = task_map["dep-ov-c"]
    a = task_map["dep-ov-a"]
    b = task_map["dep-ov-b"]

    # C wins the only slot
    assert c.status == "scheduled", "Task C (p=9) should win the only slot"

    # A must be in backlog (lost to C on priority)
    assert a.status == "backlog", "Task A (p=5) should be in backlog"

    # B must also be in backlog because its dependency A is unscheduled
    assert b.status == "backlog", (
        "Task B must be in backlog because its dependency (A) is unscheduled"
    )

    # Extra safety: B was never placed before A even hypothetically
    assert b.start_time is None, "Task B should have no start_time"


# ---------------------------------------------------------------------------
# 18. test_check_detects_event_overrun
#     detect_and_apply_overruns() notices a fixed event whose end_time has
#     been passed and auto-applies an event_overrun disruption.
# ---------------------------------------------------------------------------

def test_check_detects_event_overrun():
    """
    Simulate the clock moving past a fixed event's scheduled end without
    an explicit disruption being filed.

    Setup
    -----
    Day 09:00-18:00.  One fixed event 09:00-10:00, one flexible task.
    The task is placed starting at 10:00 (right after the event).

    Simulate current_time = 10:30 — the event was supposed to end at 10:00
    but it's now 10:30 and still running.

    Expected
    --------
    detect_and_apply_overruns() detects the overrun, applies
    event_overrun with new_end_time=10:30 (630), re-solves, and returns:
    - at least one explanation line mentioning the event
    - no scheduled task starts before 10:30 (they all shifted)
    """
    from app.solver import detect_and_apply_overruns

    schedule = day(
        day_start=540,
        day_end=1080,
        fixed_events=[event("e1", "Morning meeting", 540, 600)],  # ends 10:00
        flexible_tasks=[
            task("t1", duration=60, priority=8),
            task("t2", duration=60, priority=6),
        ],
    )
    solved = solve_schedule(schedule)

    # Verify baseline: tasks placed at or after 10:00
    for t in solved.flexible_tasks:
        if t.status == "scheduled":
            assert t.start_time >= 600, "Baseline: tasks should start after event ends"

    # Simulate current_time=10:30 — event overran without user filing a disruption
    current_time = 630  # 10:30

    updated, explanations = detect_and_apply_overruns(solved, current_time)

    # At least one explanation must have been generated
    assert len(explanations) > 0, "Should produce at least one explanation for the overrun"

    # No task should be scheduled during or before the overran event's new end
    for t in updated.flexible_tasks:
        if t.status == "scheduled" and t.start_time is not None:
            assert t.start_time >= current_time, (
                f"Task '{t.id}' starts at {t.start_time} "
                f"which is before current_time {current_time} after auto-overrun"
            )


# ---------------------------------------------------------------------------
# 19. test_check_no_overrun_returns_unchanged
#     When current_time is before all event ends, no disruption is applied
#     and the schedule comes back identical.
# ---------------------------------------------------------------------------

def test_check_no_overrun_returns_unchanged():
    """
    If current_time is before all events/tasks finish, detect_and_apply_overruns
    returns the schedule unchanged with an empty explanation list.
    """
    from app.solver import detect_and_apply_overruns

    schedule = day(
        day_start=540,
        day_end=1080,
        fixed_events=[event("e1", "Meeting", 540, 600)],
        flexible_tasks=[task("t1", duration=60, priority=7)],
    )
    solved = solve_schedule(schedule)

    # current_time is before the event ends — nothing should be detected
    current_time = 560  # 09:20, still inside the event

    updated, explanations = detect_and_apply_overruns(solved, current_time)

    assert explanations == [], "No overruns should be detected before event ends"
    # Schedule should be functionally unchanged
    original_ids = {t.id: t.start_time for t in solved.flexible_tasks}
    for t in updated.flexible_tasks:
        assert t.start_time == original_ids[t.id], (
            f"Task '{t.id}' start_time changed unexpectedly"
        )


# ---------------------------------------------------------------------------
# 20. test_check_endpoint_via_fastapi (integration)
#     Hit POST /schedule/check via the FastAPI test client.
# ---------------------------------------------------------------------------

def test_check_endpoint_via_fastapi():
    """
    Integration test: POST /schedule/check with a schedule where a fixed
    event's end_time has been passed by current_time.  Confirms the endpoint
    returns a valid DisruptDayResponse with explanations.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # Build a solved schedule with one fixed event ending at 10:00
    schedule = day(
        day_start=540,
        day_end=1080,
        fixed_events=[event("e1", "Morning block", 540, 600)],
        flexible_tasks=[
            task("t1", duration=60, priority=8),
            task("t2", duration=60, priority=5),
        ],
    )
    solved = solve_schedule(schedule)

    # POST to /schedule/check with current_time past the event's end
    payload = {
        "schedule":     solved.model_dump(),
        "current_time": 630,   # 10:30 — event was supposed to end at 10:00
    }
    response = client.post("/schedule/check", json=payload)

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    data = response.json()
    assert "schedule" in data
    assert "explanations" in data
    assert isinstance(data["explanations"], list)
    assert len(data["explanations"]) > 0, "Should return at least one explanation"

    # Tasks in updated schedule must respect the new event boundary
    for t in data["schedule"]["flexible_tasks"]:
        if t["status"] == "scheduled":
            assert t["start_time"] >= 630, (
                f"Task '{t['id']}' starts at {t['start_time']} before new event end 630"
            )
