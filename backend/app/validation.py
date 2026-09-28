"""
validation.py

Input validation for FlowDay data models.

These functions run BEFORE the CP-SAT solver is invoked so bad inputs are
rejected early with clear, human-readable messages rather than causing silent
misbehaviour inside the solver.

All functions raise ValueError on failure.  FastAPI endpoints catch these and
convert them to HTTP 400 responses.
"""

from app.models import DaySchedule, FixedEvent, FlexibleTask


# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------

def validate_fixed_events(events: list[FixedEvent]) -> None:
    """
    Raise ValueError if any two FixedEvents overlap in time.

    Two events overlap when one starts before the other ends:
        A.start_time < B.end_time  AND  B.start_time < A.end_time

    Checks every pair in O(n²) — fine for realistic day sizes (< 20 events).
    """
    for i in range(len(events)):
        for j in range(i + 1, len(events)):
            a, b = events[i], events[j]
            if a.start_time < b.end_time and b.start_time < a.end_time:
                raise ValueError(
                    f"Fixed events overlap: "
                    f"'{a.title}' [{a.start_time}–{a.end_time}] "
                    f"and '{b.title}' [{b.start_time}–{b.end_time}]. "
                    "Fixed events must not overlap."
                )


def validate_flexible_task(task: FlexibleTask) -> None:
    """
    Raise ValueError for any constraint inconsistency on a single FlexibleTask.

    Checks
    ------
    1. duration > 0  (also enforced by Pydantic, but explicit here for clarity)
    2. deadline >= earliest_start  (if both set)
    3. latest_end >= earliest_start  (if both set)
    4. deadline >= duration  (task must fit before deadline)
    5. latest_end - earliest_start >= duration  (window wide enough; if both set)
    """
    if task.duration <= 0:
        raise ValueError(
            f"Task '{task.title}': duration must be > 0, got {task.duration}."
        )

    if task.deadline is not None and task.earliest_start is not None:
        if task.deadline < task.earliest_start:
            raise ValueError(
                f"Task '{task.title}': deadline ({task.deadline}) is before "
                f"earliest_start ({task.earliest_start}). "
                "A task cannot be due before it is allowed to start."
            )
        if task.deadline - task.earliest_start < task.duration:
            raise ValueError(
                f"Task '{task.title}': window between earliest_start "
                f"({task.earliest_start}) and deadline ({task.deadline}) "
                f"is {task.deadline - task.earliest_start} min, which is "
                f"less than the task duration ({task.duration} min)."
            )

    if task.latest_end is not None and task.earliest_start is not None:
        if task.latest_end < task.earliest_start:
            raise ValueError(
                f"Task '{task.title}': latest_end ({task.latest_end}) is before "
                f"earliest_start ({task.earliest_start})."
            )
        if task.latest_end - task.earliest_start < task.duration:
            raise ValueError(
                f"Task '{task.title}': window between earliest_start "
                f"({task.earliest_start}) and latest_end ({task.latest_end}) "
                f"is {task.latest_end - task.earliest_start} min, which is "
                f"less than the task duration ({task.duration} min)."
            )

    if task.deadline is not None and task.deadline < task.duration:
        raise ValueError(
            f"Task '{task.title}': deadline ({task.deadline}) is less than "
            f"the task duration ({task.duration} min). "
            "The task cannot finish before midnight even if it starts at 00:00."
        )


def validate_day_schedule(schedule: DaySchedule) -> None:
    """
    Run all validation checks on a complete DaySchedule.

    Validates:
    - No overlapping fixed events
    - Every flexible task's constraint consistency
    """
    validate_fixed_events(schedule.fixed_events)
    for task in schedule.flexible_tasks:
        validate_flexible_task(task)


# ---------------------------------------------------------------------------
# __main__ — demonstrate that bad inputs are caught before the solver
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from app.models import FixedEvent, FlexibleTask

    print("FlowDay validation tests\n")
    passed = 0
    failed = 0

    def expect_error(label: str, fn) -> None:
        global passed, failed
        try:
            fn()
            print(f"  FAIL  {label}  (no error raised — should have been)")
            failed += 1
        except ValueError as e:
            print(f"  PASS  {label}")
            print(f"        → {e}")
            passed += 1

    def expect_ok(label: str, fn) -> None:
        global passed, failed
        try:
            fn()
            print(f"  PASS  {label}")
            passed += 1
        except ValueError as e:
            print(f"  FAIL  {label}  (unexpected error: {e})")
            failed += 1

    print("── Fixed event overlap ─────────────────────────────────")

    expect_error(
        "Two events that overlap (B starts during A)",
        lambda: validate_fixed_events([
            FixedEvent(id="a", title="Meeting A", start_time=600, end_time=690),
            FixedEvent(id="b", title="Meeting B", start_time=660, end_time=750),
        ]),
    )

    expect_error(
        "Event B completely inside event A",
        lambda: validate_fixed_events([
            FixedEvent(id="a", title="Long block", start_time=480, end_time=720),
            FixedEvent(id="b", title="Short block", start_time=540, end_time=600),
        ]),
    )

    expect_ok(
        "Two events that are adjacent (no overlap)",
        lambda: validate_fixed_events([
            FixedEvent(id="a", title="Morning Class", start_time=600, end_time=690),
            FixedEvent(id="b", title="Lunch",         start_time=690, end_time=750),
        ]),
    )

    expect_ok(
        "Two events with a gap between them",
        lambda: validate_fixed_events([
            FixedEvent(id="a", title="Morning Class", start_time=600, end_time=690),
            FixedEvent(id="b", title="Afternoon Lab", start_time=780, end_time=900),
        ]),
    )

    print("\n── Flexible task constraints ───────────────────────────")

    expect_error(
        "Deadline before earliest_start",
        lambda: validate_flexible_task(FlexibleTask(
            id="t1", title="Bad task",
            duration=30, priority=5,
            earliest_start=600,  # 10:00 AM
            deadline=540,        # 9:00 AM — impossible
        )),
    )

    expect_error(
        "latest_end before earliest_start",
        lambda: validate_flexible_task(FlexibleTask(
            id="t2", title="Bad task 2",
            duration=30, priority=5,
            earliest_start=720,  # 12:00 PM
            latest_end=660,      # 11:00 AM — impossible
        )),
    )

    expect_error(
        "Window too narrow for duration (deadline - earliest_start < duration)",
        lambda: validate_flexible_task(FlexibleTask(
            id="t3", title="Tight task",
            duration=60, priority=5,
            earliest_start=600,  # 10:00 AM
            deadline=630,        # 10:30 AM — only 30 min window for 60 min task
        )),
    )

    expect_error(
        "duration <= 0",
        lambda: FlexibleTask(  # caught by Pydantic gt=0 constraint
            id="t4", title="Zero duration",
            duration=0, priority=5,
        ),
    )

    expect_ok(
        "Valid task: deadline well after earliest_start",
        lambda: validate_flexible_task(FlexibleTask(
            id="t5", title="Valid task",
            duration=60, priority=7,
            earliest_start=540,  # 9:00 AM
            deadline=780,        # 1:00 PM — 240 min window
        )),
    )

    expect_ok(
        "Valid task: no constraints at all",
        lambda: validate_flexible_task(FlexibleTask(
            id="t6", title="Free task",
            duration=45, priority=3,
        )),
    )

    print(f"\n{'─' * 50}")
    print(f"  Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("  ✓ All validation tests passed — solver never reached.")
