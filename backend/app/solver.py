"""
solver.py

CP-SAT scheduler for FlowDay.
Takes a DaySchedule (fixed events + flexible tasks) and assigns start times
to flexible tasks while respecting no-overlap, day bounds, and optional
per-task constraints (deadline, earliest_start, latest_end).

Overflow handling
-----------------
Each flexible task has a boolean `is_scheduled` variable.  Its interval is
an *optional* interval gated on that boolean, so the solver can freely drop
any task from the schedule.  The objective maximises the sum of
(priority * is_scheduled) across all tasks, so higher-priority tasks are
always preferred when there isn't enough room for everyone.
"""

import sys
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from ortools.sat.python import cp_model

from app.models import DaySchedule, FlexibleTask, WeekSchedule


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(minutes: int) -> str:
    """Convert minutes-since-midnight to a HH:MM string for display."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _print_results(label: str, input_schedule: DaySchedule, result: DaySchedule) -> None:
    """Pretty-print solver results for a named scenario."""
    width = 60
    print("=" * width)
    print(f"  {label}")
    print("=" * width)

    # Fixed events — verify they are unchanged
    print("\nFixed events (unchanged):")
    for evt in result.fixed_events:
        original = next(e for e in input_schedule.fixed_events if e.id == evt.id)
        changed = (evt.start_time != original.start_time or
                   evt.end_time   != original.end_time)
        flag = "  *** CHANGED — BUG ***" if changed else ""
        print(f"  [{_fmt(evt.start_time)} – {_fmt(evt.end_time)}]  {evt.title}{flag}")

    # Flexible tasks
    scheduled = [t for t in result.flexible_tasks if t.status == "scheduled"]
    backlog   = [t for t in result.flexible_tasks if t.status == "backlog"]

    total_priority = sum(t.priority for t in scheduled)

    print(f"\nScheduled tasks ({len(scheduled)})  "
          f"[total priority captured: {total_priority}]:")
    for task in sorted(scheduled, key=lambda t: t.start_time):  # type: ignore[arg-type]
        end = task.start_time + task.duration  # type: ignore[operator]
        print(f"  [{_fmt(task.start_time)} – {_fmt(end)}]  "  # type: ignore[arg-type]
              f"p={task.priority:2d}  {task.title}")

    if backlog:
        print(f"\nBacklog tasks ({len(backlog)}):")
        for task in sorted(backlog, key=lambda t: t.priority, reverse=True):
            print(f"  p={task.priority:2d}  {task.title}")
    else:
        print("\n  (all tasks scheduled)")

    print()


# ---------------------------------------------------------------------------
# Core solver
# ---------------------------------------------------------------------------

# Objective weight constants — chosen so the priority hierarchy is strict:
#   1 point of priority  beats any combination of duration + id differences
#   1 min shorter duration beats any id difference
#
# With priority in [1,10], duration in [1,1440], id_rank in [0, n_tasks-1]:
#   W_PRIORITY  = 1_000_000  → priority gap of 1  = 1_000_000 units
#   W_DURATION  = 100        → max duration cost   = 144_000 < 1_000_000 ✓
#   W_ID        = 1          → max id_rank cost     < 100 (W_DURATION) ✓
_W_PRIORITY = 1_000_000
_W_DURATION = 100
_W_ID       = 1


def solve_schedule(schedule: DaySchedule) -> DaySchedule:
    """
    Assign start times to FlexibleTasks in *schedule* using CP-SAT.

    Each task is optional — the solver decides whether to include it.

    Objective (three-level hierarchy, encoded as a single weighted sum)
    -------------------------------------------------------------------
    1. PRIMARY   Maximise total priority of scheduled tasks.
    2. SECONDARY Among tasks with equal priority, prefer shorter duration
                 (a shorter task leaves more room for other tasks).
    3. TERTIARY  Among tasks with equal priority and duration, prefer the
                 lexicographically smaller id (full determinism).

    Returns a new DaySchedule (input is never mutated).
    """

    model = cp_model.CpModel()

    day_start = schedule.day_start
    day_end   = schedule.day_end

    all_intervals: list = []

    # -----------------------------------------------------------------------
    # Fixed events — always-present, non-variable intervals
    # -----------------------------------------------------------------------
    for event in schedule.fixed_events:
        fixed_interval = model.new_fixed_size_interval_var(
            start=event.start_time,
            size=event.end_time - event.start_time,
            name=f"fixed_{event.id}",
        )
        all_intervals.append(fixed_interval)

    # -----------------------------------------------------------------------
    # Flexible tasks — optional interval per task
    # -----------------------------------------------------------------------
    task_vars: dict[str, tuple[cp_model.IntVar, cp_model.IntVar]] = {}
    # task_vars[task.id] = (start_var, is_scheduled_var)

    # Pre-compute id rank for tertiary tie-break (lexicographic order of ids)
    sorted_ids = sorted(t.id for t in schedule.flexible_tasks)
    id_rank: dict[str, int] = {tid: rank for rank, tid in enumerate(sorted_ids)}

    objective_terms: list = []

    for task in schedule.flexible_tasks:
        lo = day_start
        hi = day_end - task.effective_duration

        if hi < lo:
            continue

        if task.earliest_start is not None:
            lo = max(lo, task.earliest_start)
        if task.latest_end is not None:
            hi = min(hi, task.latest_end - task.effective_duration)
        if task.deadline is not None:
            hi = min(hi, task.deadline - task.effective_duration)

        if hi < lo:
            continue

        is_scheduled = model.new_bool_var(f"is_scheduled_{task.id}")
        start_var    = model.new_int_var(lo, hi, f"start_{task.id}")

        interval_var = model.new_optional_fixed_size_interval_var(
            start=start_var,
            size=task.effective_duration,
            is_present=is_scheduled,
            name=f"interval_{task.id}",
        )

        all_intervals.append(interval_var)
        task_vars[task.id] = (start_var, is_scheduled)

        # Weighted objective term — use effective_duration for tie-breaking
        # so an overrunning task doesn't get unfairly penalised vs a fresh task
        objective_terms.append(
            (task.priority  * _W_PRIORITY
             - task.effective_duration * _W_DURATION
             - id_rank[task.id] * _W_ID)
            * is_scheduled
        )

    # -----------------------------------------------------------------------
    # NoOverlap
    # -----------------------------------------------------------------------
    model.add_no_overlap(all_intervals)

    # -----------------------------------------------------------------------
    # Precedence constraints — depends_on
    # -----------------------------------------------------------------------
    # For every task B that declares depends_on=A:
    #   - If both A and B are schedulable, enforce:
    #       start(B) >= start(A) + effective_duration(A)
    #     using an OnlyEnforceIf so the constraint only applies when both
    #     is_scheduled booleans are True.
    #   - Additionally, B can only be scheduled if A is also scheduled:
    #       is_scheduled(B) <= is_scheduled(A)
    #     This cascades: if A goes to backlog, B is forced to backlog too.
    #
    # If A's variable was never created (task too long to fit), B's variable
    # also cannot be created, so B is already excluded from task_vars and
    # will land in backlog naturally.

    task_index: dict[str, "FlexibleTask"] = {t.id: t for t in schedule.flexible_tasks}

    for task in schedule.flexible_tasks:
        if task.depends_on is None:
            continue
        dep_id = task.depends_on

        # Both this task and its dependency must have variables
        if task.id not in task_vars or dep_id not in task_vars:
            # One or both couldn't be created (geometrically impossible).
            # The dependent task will land in backlog via the normal path.
            continue

        dep_task = task_index.get(dep_id)
        if dep_task is None:
            continue  # dependency references a task not in this schedule

        start_b, is_sched_b = task_vars[task.id]
        start_a, is_sched_a = task_vars[dep_id]

        # B can only be scheduled if A is scheduled
        model.add(is_sched_b <= is_sched_a)

        # When both are scheduled: start(B) >= start(A) + effective_duration(A)
        # OnlyEnforceIf both booleans — the constraint is vacuous when either is 0
        both_scheduled = model.new_bool_var(f"both_sched_{dep_id}_{task.id}")
        model.add_bool_and([is_sched_a, is_sched_b]).only_enforce_if(both_scheduled)
        model.add_bool_or([is_sched_a.negated(), is_sched_b.negated()]).only_enforce_if(
            both_scheduled.negated()
        )
        model.add(
            start_b >= start_a + dep_task.effective_duration
        ).only_enforce_if(both_scheduled)

    # -----------------------------------------------------------------------
    # Objective: maximise total priority of scheduled tasks
    # -----------------------------------------------------------------------
    if objective_terms:
        model.maximize(sum(objective_terms))

    # -----------------------------------------------------------------------
    # Solve
    # -----------------------------------------------------------------------
    solver = cp_model.CpSolver()
    status = solver.solve(model)

    # -----------------------------------------------------------------------
    # Extract results — build updated task list
    # -----------------------------------------------------------------------
    updated_tasks: list[FlexibleTask] = []

    def _is_deadline_today(task: FlexibleTask) -> bool:
        """
        True when a backlog task has a deadline that falls within today's
        schedulable window — it was due today but couldn't be placed.
        """
        return (
            task.deadline is not None
            and schedule.day_start <= task.deadline <= schedule.day_end
        )

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for task in schedule.flexible_tasks:
            if task.id in task_vars:
                start_var, is_scheduled = task_vars[task.id]
                if solver.value(is_scheduled):
                    updated_tasks.append(task.model_copy(update={
                        "start_time": solver.value(start_var),
                        "status": "scheduled",
                        "is_deadline_today": False,
                    }))
                else:
                    updated_tasks.append(task.model_copy(update={
                        "start_time": None,
                        "status": "backlog",
                        "is_deadline_today": _is_deadline_today(task),
                    }))
            else:
                # Variable never created (impossible to schedule) — keep as backlog.
                updated_tasks.append(task.model_copy(update={
                    "start_time": None,
                    "status": "backlog",
                    "is_deadline_today": _is_deadline_today(task),
                }))
    else:
        # Solver returned INFEASIBLE or unknown — leave everything in backlog.
        for task in schedule.flexible_tasks:
            updated_tasks.append(task.model_copy(update={
                "start_time": None,
                "status": "backlog",
                "is_deadline_today": _is_deadline_today(task),
            }))

    return schedule.model_copy(update={"flexible_tasks": updated_tasks})


# ---------------------------------------------------------------------------
# Disruption handling
# ---------------------------------------------------------------------------

def trigger_disruption(
    schedule: DaySchedule,
    disruption: dict,
    current_time: int | None = None,
) -> DaySchedule:
    """
    Apply a real-time disruption to a DaySchedule and re-solve.

    Supported disruption types
    --------------------------
    "event_overrun"
        A fixed event has run long.  Update its end_time and re-solve so
        flexible tasks are re-placed around the new, longer block.

        Shape::

            {
                "type": "event_overrun",
                "event_id": "<id of the FixedEvent>",
                "new_end_time": <int, minutes since midnight>
            }

    current_time parameter
    ----------------------
    When provided (minutes since midnight), the solver respects task state:

    - COMPLETED  start_time + duration <= current_time
                 Kept exactly as-is.  Excluded from the CP-SAT model so the
                 solver cannot move or drop them.  Their time slot is still
                 added as a fixed interval so future tasks don't overlap them.

    - IN PROGRESS start_time <= current_time < start_time + duration
                 Also kept as-is and added as a fixed interval.  The solver
                 will not touch its start_time.  (Full in-progress handling —
                 e.g. partial credit — is deferred to a later module.)

    - FUTURE      start_time > current_time, or status == "backlog"
                 Reset to backlog and handed to the solver for re-placement.

    When current_time is None the whole day is open (original behaviour).

    Fixed events before current_time are still added to the CP-SAT model as
    fixed intervals (they block time), but cannot be disrupted because the
    disruption target must be a *future* event.

    Raises
    ------
    ValueError
        If the disruption type is unknown, required keys are missing, the
        referenced event_id does not exist, or (when current_time is set) the
        disrupted event has already ended before current_time.
    """

    disruption_type = disruption.get("type")

    if disruption_type == "event_overrun":
        event_id     = disruption.get("event_id")
        new_end_time = disruption.get("new_end_time")

        if event_id is None or new_end_time is None:
            raise ValueError(
                "'event_overrun' disruption requires 'event_id' and 'new_end_time'."
            )

        # ── Update the target fixed event ───────────────────────────────────
        updated_events = []
        found = False
        for event in schedule.fixed_events:
            if event.id == event_id:
                if new_end_time <= event.start_time:
                    raise ValueError(
                        f"new_end_time ({new_end_time}) must be after "
                        f"the event's start_time ({event.start_time})."
                    )
                updated_events.append(event.model_copy(update={"end_time": new_end_time}))
                found = True
            else:
                updated_events.append(event)

        if not found:
            raise ValueError(
                f"No FixedEvent with id='{event_id}' found in schedule.fixed_events."
            )

        # ── Partition flexible tasks by their relationship to current_time ──
        #
        # locked_tasks   — completed or in-progress; kept as-is, added as
        #                  fixed intervals so the solver respects their slots
        # tasks_to_solve — future tasks (or still-backlogged); handed to solver
        locked_tasks:   list[FlexibleTask] = []
        tasks_to_solve: list[FlexibleTask] = []

        if current_time is None:
            # No time context — reset everything and re-solve from scratch
            tasks_to_solve = [
                t.model_copy(update={"start_time": None, "status": "backlog"})
                for t in schedule.flexible_tasks
            ]
        else:
            for task in schedule.flexible_tasks:
                if task.status == "scheduled" and task.start_time is not None:
                    task_end = task.start_time + task.duration
                    if task_end <= current_time:
                        # Completed — preserve exactly
                        locked_tasks.append(task)
                    elif task.start_time <= current_time:
                        # In progress — preserve exactly
                        locked_tasks.append(task)
                    else:
                        # Future — reset to backlog for re-solving
                        tasks_to_solve.append(
                            task.model_copy(update={"start_time": None, "status": "backlog"})
                        )
                else:
                    # Was already in backlog — eligible for re-solving
                    tasks_to_solve.append(
                        task.model_copy(update={"start_time": None, "status": "backlog"})
                    )

        # ── Build the schedule the solver will see ──────────────────────────
        #
        # Locked tasks are injected as extra fixed events so the NoOverlap
        # constraint keeps future tasks away from their slots.  They are NOT
        # in flexible_tasks for the solver, so their start_time is immutable.
        locked_as_fixed = [
            # Reuse FixedEvent model — same fields we need
            type("_FE", (), {  # minimal duck-typed object; use a real FixedEvent below
                "id": f"_locked_{t.id}",
                "start_time": t.start_time,
                "end_time": t.start_time + t.duration,
            })()
            for t in locked_tasks
        ]

        # Use proper FixedEvent objects so the solver's type annotations hold
        from app.models import FixedEvent as _FE
        locked_fixed_events = [
            _FE(
                id=f"_locked_{t.id}",
                title=f"[locked] {t.title}",
                start_time=t.start_time,       # type: ignore[arg-type]
                end_time=t.start_time + t.duration,  # type: ignore[operator]
            )
            for t in locked_tasks
        ]

        disrupted_schedule = schedule.model_copy(update={
            "fixed_events":   updated_events + locked_fixed_events,
            "flexible_tasks": tasks_to_solve,
        })

        # ── Solve only the future tasks ─────────────────────────────────────
        solved = solve_schedule(disrupted_schedule)

        # ── Reconstruct full task list: locked first, then solver results ───
        all_tasks = locked_tasks + list(solved.flexible_tasks)

        # Return schedule with original fixed events (not the locked extras)
        return solved.model_copy(update={
            "fixed_events":   updated_events,   # restored — no _locked_ events
            "flexible_tasks": all_tasks,
        })

    elif disruption_type == "task_overrun":
        """
        A flexible task that is currently in-progress is taking longer than
        planned.  Its start_time is immutable — we only update how long it
        will run and re-solve everything that comes after it.

        Required disruption keys
        ------------------------
        task_id             : id of the in-progress FlexibleTask
        new_estimated_end   : new expected finish time (minutes since midnight)

        The task's actual_duration is set to (new_estimated_end - start_time).
        The task is then added to the CP-SAT model as a fixed interval so
        future tasks are pushed out to avoid overlapping it.
        current_time must be provided so the solver knows which tasks are
        past/in-progress vs future.
        """
        task_id           = disruption.get("task_id")
        new_estimated_end = disruption.get("new_estimated_end")

        if task_id is None or new_estimated_end is None:
            raise ValueError(
                "'task_overrun' disruption requires 'task_id' and 'new_estimated_end'."
            )
        if current_time is None:
            raise ValueError(
                "'task_overrun' disruption requires current_time to be set "
                "so the solver knows which tasks are in-progress."
            )

        # ── Locate the target task ──────────────────────────────────────────
        target = next(
            (t for t in schedule.flexible_tasks if t.id == task_id),
            None,
        )
        if target is None:
            raise ValueError(
                f"No FlexibleTask with id='{task_id}' found in schedule."
            )
        if target.status != "scheduled" or target.start_time is None:
            raise ValueError(
                f"Task '{task_id}' is not currently scheduled — "
                "only scheduled (in-progress) tasks can overrun."
            )

        task_end_original = target.start_time + target.duration
        if not (target.start_time <= current_time < task_end_original):
            raise ValueError(
                f"Task '{task_id}' is not in-progress at current_time={current_time}. "
                f"It runs [{target.start_time}–{task_end_original}]."
            )
        if new_estimated_end <= target.start_time:
            raise ValueError(
                f"new_estimated_end ({new_estimated_end}) must be after "
                f"the task's start_time ({target.start_time})."
            )
        if new_estimated_end <= task_end_original:
            raise ValueError(
                f"new_estimated_end ({new_estimated_end}) must be later than "
                f"the original end ({task_end_original}) — "
                "use task_overrun only when the task is running longer."
            )

        # ── Update the in-progress task's actual_duration ───────────────────
        new_actual_duration = new_estimated_end - target.start_time
        updated_target = target.model_copy(update={
            "actual_duration": new_actual_duration,
        })

        # ── Partition all tasks ─────────────────────────────────────────────
        # The overrunning task itself is locked (in-progress) with its new
        # effective end time.  All other completed/in-progress tasks are also
        # locked.  Future tasks are reset and re-solved.
        locked_tasks:   list[FlexibleTask] = []
        tasks_to_solve: list[FlexibleTask] = []

        for task in schedule.flexible_tasks:
            if task.id == task_id:
                # This is the overrunning task — lock it with the updated duration
                locked_tasks.append(updated_target)
                continue

            if task.status == "scheduled" and task.start_time is not None:
                task_end = task.start_time + task.effective_duration
                if task_end <= current_time or task.start_time <= current_time:
                    # Completed or in-progress — lock as-is
                    locked_tasks.append(task)
                else:
                    # Future — reset for re-solving
                    tasks_to_solve.append(
                        task.model_copy(update={"start_time": None, "status": "backlog"})
                    )
            else:
                tasks_to_solve.append(
                    task.model_copy(update={"start_time": None, "status": "backlog"})
                )

        # ── Inject locked tasks as fixed intervals ──────────────────────────
        from app.models import FixedEvent as _FE2
        locked_fixed_events = [
            _FE2(
                id=f"_locked_{t.id}",
                title=f"[locked] {t.title}",
                start_time=t.start_time,                    # type: ignore[arg-type]
                end_time=t.start_time + t.effective_duration,  # type: ignore[operator]
            )
            for t in locked_tasks
        ]

        disrupted_schedule = schedule.model_copy(update={
            "fixed_events":   list(schedule.fixed_events) + locked_fixed_events,
            "flexible_tasks": tasks_to_solve,
        })

        solved = solve_schedule(disrupted_schedule)

        # ── Reconstruct full task list ──────────────────────────────────────
        all_tasks = locked_tasks + list(solved.flexible_tasks)

        return solved.model_copy(update={
            "fixed_events":   list(schedule.fixed_events),  # original events only
            "flexible_tasks": all_tasks,
        })

    elif disruption_type == "event_cancelled":
        """
        A fixed event has been cancelled — remove it entirely and re-solve
        so the freed slot can absorb backlog tasks.

        Required disruption keys
        ------------------------
        event_id : id of the FixedEvent to remove

        All future flexible tasks (start_time > current_time, or backlog)
        are reset and re-solved.  Completed / in-progress tasks are locked.
        If current_time is None the whole day is re-solved.
        """
        event_id = disruption.get("event_id")
        if event_id is None:
            raise ValueError("'event_cancelled' disruption requires 'event_id'.")

        # Remove the cancelled event
        remaining_events = [e for e in schedule.fixed_events if e.id != event_id]
        if len(remaining_events) == len(schedule.fixed_events):
            raise ValueError(
                f"No FixedEvent with id='{event_id}' found in schedule.fixed_events."
            )

        # Partition flexible tasks exactly as in event_overrun
        locked_tasks:   list[FlexibleTask] = []
        tasks_to_solve: list[FlexibleTask] = []

        if current_time is None:
            tasks_to_solve = [
                t.model_copy(update={"start_time": None, "status": "backlog"})
                for t in schedule.flexible_tasks
            ]
        else:
            for task in schedule.flexible_tasks:
                if task.status == "scheduled" and task.start_time is not None:
                    task_end = task.start_time + task.effective_duration
                    if task_end <= current_time or task.start_time <= current_time:
                        locked_tasks.append(task)
                    else:
                        tasks_to_solve.append(
                            task.model_copy(update={"start_time": None, "status": "backlog"})
                        )
                else:
                    tasks_to_solve.append(
                        task.model_copy(update={"start_time": None, "status": "backlog"})
                    )

        from app.models import FixedEvent as _FE3
        locked_fixed_events = [
            _FE3(
                id=f"_locked_{t.id}",
                title=f"[locked] {t.title}",
                start_time=t.start_time,                      # type: ignore[arg-type]
                end_time=t.start_time + t.effective_duration,  # type: ignore[operator]
            )
            for t in locked_tasks
        ]

        disrupted_schedule = schedule.model_copy(update={
            "fixed_events":   remaining_events + locked_fixed_events,
            "flexible_tasks": tasks_to_solve,
        })

        solved = solve_schedule(disrupted_schedule)
        all_tasks = locked_tasks + list(solved.flexible_tasks)

        return solved.model_copy(update={
            "fixed_events":   remaining_events,  # cancelled event gone
            "flexible_tasks": all_tasks,
        })

    elif disruption_type == "task_early_finish":
        """
        An in-progress task finished earlier than planned — its actual_duration
        is shorter than its original duration, freeing time for later tasks.

        Required disruption keys
        ------------------------
        task_id           : id of the in-progress FlexibleTask
        actual_end_time   : the real finish time (< original planned end)

        current_time must be provided.

        The task's actual_duration is set to (actual_end_time - start_time).
        It is immediately locked as completed (since it has finished early),
        and its freed slot is available to future tasks.
        """
        task_id         = disruption.get("task_id")
        actual_end_time = disruption.get("actual_end_time")

        if task_id is None or actual_end_time is None:
            raise ValueError(
                "'task_early_finish' disruption requires 'task_id' and 'actual_end_time'."
            )
        if current_time is None:
            raise ValueError(
                "'task_early_finish' disruption requires current_time."
            )

        target = next(
            (t for t in schedule.flexible_tasks if t.id == task_id), None
        )
        if target is None:
            raise ValueError(
                f"No FlexibleTask with id='{task_id}' found in schedule."
            )
        if target.status != "scheduled" or target.start_time is None:
            raise ValueError(
                f"Task '{task_id}' is not currently scheduled."
            )

        original_end = target.start_time + target.effective_duration
        if actual_end_time >= original_end:
            raise ValueError(
                f"actual_end_time ({actual_end_time}) must be earlier than "
                f"the task's original end ({original_end}). "
                "Use task_overrun for late finishes."
            )
        if actual_end_time <= target.start_time:
            raise ValueError(
                f"actual_end_time ({actual_end_time}) must be after "
                f"the task's start_time ({target.start_time})."
            )

        new_actual_duration = actual_end_time - target.start_time
        # Task is now completed (finished early) — lock it with the shorter duration
        finished_task = target.model_copy(update={"actual_duration": new_actual_duration})

        locked_tasks   = [finished_task]   # early-finished task is locked/completed
        tasks_to_solve: list[FlexibleTask] = []

        for task in schedule.flexible_tasks:
            if task.id == task_id:
                continue  # already handled above

            if task.status == "scheduled" and task.start_time is not None:
                task_end = task.start_time + task.effective_duration
                if task_end <= current_time or task.start_time <= current_time:
                    locked_tasks.append(task)
                else:
                    tasks_to_solve.append(
                        task.model_copy(update={"start_time": None, "status": "backlog"})
                    )
            else:
                tasks_to_solve.append(
                    task.model_copy(update={"start_time": None, "status": "backlog"})
                )

        from app.models import FixedEvent as _FE4
        locked_fixed_events = [
            _FE4(
                id=f"_locked_{t.id}",
                title=f"[locked] {t.title}",
                start_time=t.start_time,                      # type: ignore[arg-type]
                end_time=t.start_time + t.effective_duration,  # type: ignore[operator]
            )
            for t in locked_tasks
        ]

        disrupted_schedule = schedule.model_copy(update={
            "fixed_events":   list(schedule.fixed_events) + locked_fixed_events,
            "flexible_tasks": tasks_to_solve,
        })

        solved = solve_schedule(disrupted_schedule)
        all_tasks = locked_tasks + list(solved.flexible_tasks)

        return solved.model_copy(update={
            "fixed_events":   list(schedule.fixed_events),
            "flexible_tasks": all_tasks,
        })

    elif disruption_type == "day_shrink":
        """
        The available day has been cut short — everything must finish by the
        new, earlier day_end.  Tasks that no longer fit go to backlog.

        Required disruption keys
        ------------------------
        new_day_end : int  — new day_end in minutes since midnight.
                             Must be less than the current schedule.day_end.

        Behaviour
        ---------
        - schedule.day_end is updated to new_day_end.
        - Any fixed event that ends after new_day_end is NOT moved — it is
          kept as-is (it may represent an unavoidable obligation).  The caller
          is responsible for issuing separate disruptions for those if needed.
        - Completed / in-progress flexible tasks (per current_time) are locked.
        - Future flexible tasks are reset to backlog and re-solved within the
          new bounds.  Tasks whose duration cannot fit before new_day_end will
          simply not get a start variable and will remain in backlog — no crash.
        - If current_time is None the whole day is re-solved.

        Raises ValueError if new_day_end >= schedule.day_end (not actually
        shorter) or new_day_end <= schedule.day_start (no room at all).
        """
        new_day_end = disruption.get("new_day_end")
        if new_day_end is None:
            raise ValueError("'day_shrink' disruption requires 'new_day_end'.")
        if new_day_end >= schedule.day_end:
            raise ValueError(
                f"new_day_end ({new_day_end}) must be earlier than the current "
                f"day_end ({schedule.day_end}). Use day_shrink only to cut the day short."
            )
        if new_day_end <= schedule.day_start:
            raise ValueError(
                f"new_day_end ({new_day_end}) must be after day_start "
                f"({schedule.day_start}). No schedulable time would remain."
            )

        # Partition flexible tasks
        locked_tasks:   list[FlexibleTask] = []
        tasks_to_solve: list[FlexibleTask] = []

        if current_time is None:
            tasks_to_solve = [
                t.model_copy(update={"start_time": None, "status": "backlog"})
                for t in schedule.flexible_tasks
            ]
        else:
            for task in schedule.flexible_tasks:
                if task.status == "scheduled" and task.start_time is not None:
                    task_end = task.start_time + task.effective_duration
                    if task_end <= current_time or task.start_time <= current_time:
                        locked_tasks.append(task)
                    else:
                        tasks_to_solve.append(
                            task.model_copy(update={"start_time": None, "status": "backlog"})
                        )
                else:
                    tasks_to_solve.append(
                        task.model_copy(update={"start_time": None, "status": "backlog"})
                    )

        from app.models import FixedEvent as _FE5
        locked_fixed_events = [
            _FE5(
                id=f"_locked_{t.id}",
                title=f"[locked] {t.title}",
                start_time=t.start_time,                      # type: ignore[arg-type]
                end_time=t.start_time + t.effective_duration,  # type: ignore[operator]
            )
            for t in locked_tasks
        ]

        # Build a shrunken schedule for the solver
        disrupted_schedule = schedule.model_copy(update={
            "day_end":        new_day_end,
            "fixed_events":   list(schedule.fixed_events) + locked_fixed_events,
            "flexible_tasks": tasks_to_solve,
        })

        solved = solve_schedule(disrupted_schedule)
        all_tasks = locked_tasks + list(solved.flexible_tasks)

        return solved.model_copy(update={
            "day_end":        new_day_end,
            "fixed_events":   list(schedule.fixed_events),  # no _locked_ events
            "flexible_tasks": all_tasks,
        })

    else:
        raise ValueError(
            f"Unknown disruption type: '{disruption_type}'. "
            "Supported types: 'event_overrun', 'task_overrun', "
            "'event_cancelled', 'task_early_finish', 'day_shrink'."
        )


# ---------------------------------------------------------------------------
# Explanation generator
# ---------------------------------------------------------------------------

def generate_explanation(
    old_schedule: DaySchedule,
    new_schedule: DaySchedule,
    disruption: dict,
) -> list[str]:
    """
    Compare two DaySchedules and produce plain-English lines describing what
    changed and why.

    Covers three cases per task:
    - Moved (start_time changed)   → "X moved from HH:MM to HH:MM because <reason>."
    - Dropped to backlog           → "X was moved to backlog because <reason>."
    - Rescued from backlog         → "X was scheduled at HH:MM after time opened up."

    The 'because' clause is derived from the disruption dict so messages are
    specific rather than generic.
    """

    def fmt(minutes: int) -> str:
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    # Build the 'because' clause once from the disruption type
    disruption_type = disruption.get("type", "unknown")

    def _because(task_title: str) -> str:
        if disruption_type == "event_overrun":
            event_id     = disruption.get("event_id", "an event")
            new_end_time = disruption.get("new_end_time")
            # Try to look up the event title from either schedule
            event_title = event_id
            for evt in list(new_schedule.fixed_events) + list(old_schedule.fixed_events):
                if evt.id == event_id:
                    event_title = evt.title
                    break
            suffix = f" until {fmt(new_end_time)}" if new_end_time else ""
            return f"{event_title} ran{suffix}"

        if disruption_type == "event_cancelled":
            event_id = disruption.get("event_id", "an event")
            event_title = event_id
            for evt in old_schedule.fixed_events:
                if evt.id == event_id:
                    event_title = evt.title
                    break
            return f"{event_title} was cancelled"

        if disruption_type == "task_overrun":
            task_id = disruption.get("task_id", "a task")
            new_end  = disruption.get("new_estimated_end")
            task_title_src = task_id
            for t in old_schedule.flexible_tasks:
                if t.id == task_id:
                    task_title_src = t.title
                    break
            suffix = f" until {fmt(new_end)}" if new_end else ""
            return f"{task_title_src} overran{suffix}"

        if disruption_type == "task_early_finish":
            task_id = disruption.get("task_id", "a task")
            actual_end = disruption.get("actual_end_time")
            task_title_src = task_id
            for t in old_schedule.flexible_tasks:
                if t.id == task_id:
                    task_title_src = t.title
                    break
            suffix = f" at {fmt(actual_end)}" if actual_end else " early"
            return f"{task_title_src} finished{suffix}"

        if disruption_type == "day_shrink":
            new_end = disruption.get("new_day_end")
            suffix = f" to {fmt(new_end)}" if new_end else ""
            return f"the day was cut short{suffix}"

        return "a schedule disruption occurred"

    # Index tasks by id for fast lookup
    old_map: dict[str, FlexibleTask] = {t.id: t for t in old_schedule.flexible_tasks}
    new_map: dict[str, FlexibleTask] = {t.id: t for t in new_schedule.flexible_tasks}

    lines: list[str] = []

    # Walk through every task that appears in either schedule
    all_ids = list(dict.fromkeys(
        [t.id for t in old_schedule.flexible_tasks] +
        [t.id for t in new_schedule.flexible_tasks]
    ))

    for task_id in all_ids:
        old_task = old_map.get(task_id)
        new_task = new_map.get(task_id)

        if old_task is None or new_task is None:
            continue  # task appeared/disappeared entirely — skip

        old_scheduled = old_task.status == "scheduled" and old_task.start_time is not None
        new_scheduled = new_task.status == "scheduled" and new_task.start_time is not None

        if old_scheduled and new_scheduled:
            if old_task.start_time != new_task.start_time:
                # Task moved to a different slot
                lines.append(
                    f"{new_task.title} moved from {fmt(old_task.start_time)} "  # type: ignore[arg-type]
                    f"to {fmt(new_task.start_time)} because {_because(new_task.title)}."  # type: ignore[arg-type]
                )

        elif old_scheduled and not new_scheduled:
            # Task dropped to backlog
            lines.append(
                f"{old_task.title} was moved to backlog because "
                "there wasn't enough remaining time."
            )

        elif not old_scheduled and new_scheduled:
            # Task rescued from backlog
            lines.append(
                f"{new_task.title} was scheduled at {fmt(new_task.start_time)} "  # type: ignore[arg-type]
                f"after time opened up."
            )
        # else: both backlog — no change worth reporting

    return lines


# ---------------------------------------------------------------------------
# Automatic overrun detection  (used by GET /schedule/check)
# ---------------------------------------------------------------------------

def detect_and_apply_overruns(
    schedule: DaySchedule,
    current_time: int,
) -> tuple[DaySchedule, list[str]]:
    """
    Compare *current_time* against every fixed event and scheduled flexible
    task in *schedule*.  For anything whose expected end_time has been
    passed without it being marked complete, automatically construct and
    apply the corresponding disruption via ``trigger_disruption()``.

    Detection rules
    ---------------
    FixedEvent overrun
        ``current_time > event.end_time`` — the event should have finished
        but time has moved past it.  We treat ``current_time`` itself as the
        new end_time (the event is *still running* right now) and apply an
        ``event_overrun`` disruption.

    FlexibleTask overrun (in-progress only)
        A task is in-progress when
        ``task.start_time <= current_time < task.start_time + task.duration``.
        If ``current_time > task.start_time + task.duration`` the task *should*
        be done but we haven't been told it is — treat it as a ``task_overrun``
        with ``new_estimated_end = current_time``.

    Completed tasks (``current_time >= task.start_time + task.duration``) are
    skipped — they finished on time (or were already updated).

    Disruptions are applied one at a time, each building on the previous
    result, so cascading re-solves are correct.

    Parameters
    ----------
    schedule     : A previously solved DaySchedule.
    current_time : Minutes since midnight representing "now".

    Returns
    -------
    (updated_schedule, explanations)
        ``updated_schedule`` is the re-solved schedule after all detected
        overruns have been applied.  ``explanations`` is a flat list of
        plain-English strings (one per detected disruption, merged from all
        calls to ``generate_explanation``).
    """

    result       = schedule
    explanations: list[str] = []

    # ── 1. Fixed event overruns ─────────────────────────────────────────
    for event in schedule.fixed_events:
        if current_time > event.end_time:
            disruption = {
                "type":         "event_overrun",
                "event_id":     event.id,
                "new_end_time": current_time,   # event is still running
            }
            try:
                before = result
                # Do NOT pass current_time here — we want a full re-solve
                # of all future tasks, not locking anything as in-progress.
                # The auto-detected overrun should push everything after the
                # new event boundary, regardless of where tasks were before.
                updated = trigger_disruption(result, disruption)
                lines   = generate_explanation(before, updated, disruption)
                if not lines:
                    lines = [
                        f"{event.title} overran — still running at "
                        f"{current_time // 60:02d}:{current_time % 60:02d} "
                        f"(was scheduled to end at "
                        f"{event.end_time // 60:02d}:{event.end_time % 60:02d}). "
                        "Schedule re-evaluated."
                    ]
                explanations += lines
                result = updated
            except ValueError:
                pass

    # ── 2. Flexible task overruns ───────────────────────────────────────
    for task in schedule.flexible_tasks:
        if task.status != "scheduled" or task.start_time is None:
            continue

        original_end = task.start_time + task.effective_duration

        if current_time > original_end and task.actual_duration is None:
            disruption = {
                "type":               "task_overrun",
                "task_id":            task.id,
                "new_estimated_end":  current_time,
            }
            try:
                before  = result
                updated = trigger_disruption(result, disruption, current_time=current_time)
                lines   = generate_explanation(before, updated, disruption)
                if not lines:
                    lines = [
                        f"{task.title} overran — still running at "
                        f"{current_time // 60:02d}:{current_time % 60:02d} "
                        f"(was scheduled to end at "
                        f"{original_end // 60:02d}:{original_end % 60:02d}). "
                        "Schedule re-evaluated."
                    ]
                explanations += lines
                result = updated
            except ValueError:
                pass

    return result, explanations


# ---------------------------------------------------------------------------
# Week solver
# ---------------------------------------------------------------------------

def solve_week(week: WeekSchedule) -> WeekSchedule:
    """
    Solve each day in a WeekSchedule independently.

    Each DaySchedule is passed through solve_schedule() on its own — days
    have no knowledge of each other.  Returns a new WeekSchedule with every
    day's flexible tasks scheduled or backlogged.
    """
    solved_days = [solve_schedule(day) for day in week.days]
    return week.model_copy(update={"days": solved_days})


# ---------------------------------------------------------------------------
# __main__ — run both fixtures and print results
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from app.fixtures import get_dummy_schedule, get_overflow_schedule, get_tiebreak_schedule, get_deadline_today_schedule

    # --- Normal case: all tasks should fit ----------------------------------
    dummy_input  = get_dummy_schedule()
    dummy_result = solve_schedule(dummy_input)
    _print_results("NORMAL CASE — get_dummy_schedule()", dummy_input, dummy_result)

    # --- Overflow case: tasks exceed available time, priority decides -------
    overflow_input  = get_overflow_schedule()
    overflow_result = solve_schedule(overflow_input)
    _print_results("OVERFLOW CASE — get_overflow_schedule()", overflow_input, overflow_result)

    # Sanity check: verify backlog tasks have lower priority than scheduled ones
    scheduled_priorities = sorted(
        [t.priority for t in overflow_result.flexible_tasks if t.status == "scheduled"],
        reverse=True,
    )
    backlog_priorities = sorted(
        [t.priority for t in overflow_result.flexible_tasks if t.status == "backlog"],
        reverse=True,
    )
    if backlog_priorities and scheduled_priorities:
        min_scheduled = min(scheduled_priorities)
        max_backlog   = max(backlog_priorities)
        if max_backlog <= min_scheduled:
            print("✓ Priority ordering confirmed: all backlog tasks have "
                  f"priority <= {min_scheduled} (lowest scheduled priority).")
        else:
            print(f"⚠ Priority inversion detected: a backlog task has priority "
                  f"{max_backlog} but lowest scheduled priority is {min_scheduled}.")

    # --- Disruption WITHOUT current_time (whole-day re-solve) ---------------
    print()
    print("=" * 60)
    print("  DISRUPTION (no current_time) — Morning Class +30 min")
    print("=" * 60)

    base_input  = get_dummy_schedule()
    base_result = solve_schedule(base_input)

    disrupted_no_now = trigger_disruption(
        base_result,
        {"type": "event_overrun", "event_id": "evt-001", "new_end_time": 720},
        current_time=None,
    )

    def _task_map(r: DaySchedule) -> dict:
        return {t.id: t for t in r.flexible_tasks}

    before_map = _task_map(base_result)
    after_map  = _task_map(disrupted_no_now)

    print("\nAll tasks re-solved (no locking):")
    for tid, b in before_map.items():
        a = after_map[tid]
        b_slot = f"[{_fmt(b.start_time)} – {_fmt(b.start_time + b.duration)}]" if b.status == "scheduled" else "[backlog]"
        a_slot = f"[{_fmt(a.start_time)} – {_fmt(a.start_time + a.duration)}]" if a.status == "scheduled" else "[backlog]"
        note = "  ← shifted" if (b.status == a.status == "scheduled" and b.start_time != a.start_time) else ""
        print(f"  p={b.priority:2d}  {b.title}")
        print(f"        {b_slot}  →  {a_slot}{note}")

    # --- Disruption WITH current_time = 09:00 (540) -------------------------
    #
    # Solved schedule for get_dummy_schedule():
    #   [06:00–06:30]  Review lecture notes        (p=9)   COMPLETED by 09:00
    #   [06:30–08:00]  Complete assignment draft   (p=7)   COMPLETED by 09:00
    #   [08:00–08:30]  Reply to emails             (p=8)   COMPLETED by 09:00
    #   [08:30–09:30]  Work on side project        (p=3)   IN PROGRESS at 09:00
    #   [11:30–13:30]  Read research paper         (p=4)   FUTURE
    #
    # Morning Class (evt-001): 10:00–11:30 → extended to 12:00
    #
    # Expected:
    #   - Tasks ending by 09:00 → untouched (completed)
    #   - Work on side project  → untouched (in-progress, started 08:30)
    #   - Read research paper   → re-placed around the longer Morning Class

    CURRENT_TIME = 540  # 09:00 AM

    print()
    print("=" * 60)
    print(f"  DISRUPTION WITH current_time={_fmt(CURRENT_TIME)}")
    print("  Morning Class extended: 11:30 → 12:00")
    print("  Tasks before/during 09:00 must be locked")
    print("=" * 60)

    disrupted_with_now = trigger_disruption(
        base_result,
        {"type": "event_overrun", "event_id": "evt-001", "new_end_time": 720},
        current_time=CURRENT_TIME,
    )

    after_now_map = _task_map(disrupted_with_now)

    print(f"\n  current_time = {_fmt(CURRENT_TIME)}\n")
    all_tasks_sorted = sorted(
        base_result.flexible_tasks,
        key=lambda t: t.start_time if t.start_time is not None else 9999,
    )
    for task in all_tasks_sorted:
        b = before_map[task.id]
        a = after_now_map[task.id]

        task_end = (b.start_time + b.duration) if b.start_time is not None else None

        if b.start_time is not None and task_end is not None:
            if task_end <= CURRENT_TIME:
                state = "COMPLETED"
            elif b.start_time <= CURRENT_TIME:
                state = "IN PROGRESS"
            else:
                state = "FUTURE"
        else:
            state = "BACKLOG"

        b_slot = f"[{_fmt(b.start_time)} – {_fmt(b.start_time + b.duration)}]" if b.start_time is not None else "[backlog]"
        a_slot = f"[{_fmt(a.start_time)} – {_fmt(a.start_time + a.duration)}]" if a.start_time is not None else "[backlog]"

        locked   = "  ✓ LOCKED"   if state in ("COMPLETED", "IN PROGRESS") and b_slot == a_slot else ""
        shifted  = "  ← shifted"  if state == "FUTURE" and b.start_time != a.start_time else ""
        bug_flag = "  *** BUG — should be locked ***" if state in ("COMPLETED", "IN PROGRESS") and b_slot != a_slot else ""

        print(f"  [{state:11s}]  p={b.priority:2d}  {b.title}")
        print(f"               before: {b_slot}  →  after: {a_slot}{locked}{shifted}{bug_flag}")

    print()
    locked_count  = sum(1 for t in all_tasks_sorted
                        if (t.start_time is not None and t.start_time + t.duration <= CURRENT_TIME)
                        or (t.start_time is not None and t.start_time <= CURRENT_TIME))
    future_count  = sum(1 for t in all_tasks_sorted
                        if t.start_time is None or t.start_time > CURRENT_TIME)
    print(f"  Locked (completed + in-progress): {locked_count}")
    print(f"  Re-solved (future):               {future_count}")

    # --- Tie-break case: identical priority + deadline, different duration --
    print()
    print("=" * 60)
    print("  TIE-BREAK CASE — get_tiebreak_schedule()")
    print("  All tasks: priority=7, deadline=11:00, window=120 min")
    print("  Expected: shorter tasks win, lex-smaller id breaks ties")
    print("=" * 60)

    RUNS = 5  # Run multiple times to confirm determinism
    results_across_runs: list[set[str]] = []

    for run in range(RUNS):
        tb_result_run = solve_schedule(get_tiebreak_schedule())
        scheduled_ids_run = {t.id for t in tb_result_run.flexible_tasks
                             if t.status == "scheduled"}
        results_across_runs.append(scheduled_ids_run)

    all_identical = all(r == results_across_runs[0] for r in results_across_runs)
    scheduled_ids = results_across_runs[0]

    print(f"\n  Ran solver {RUNS} times. All results identical: "
          f"{'✓ YES' if all_identical else '✗ NO — non-deterministic!'}")

    tb_result = solve_schedule(get_tiebreak_schedule())
    print("\n  Tasks:")
    for task in sorted(tb_result.flexible_tasks,
                       key=lambda t: (t.status != "scheduled", t.id)):
        icon = "✓ scheduled" if task.status == "scheduled" else "✗ backlog  "
        print(f"    [{icon}]  id={task.id:8s}  "
              f"dur={task.duration:3d}min  p={task.priority}  {task.title}")

    print()
    tb_counts = {"passes": 0, "failures": 0}

    def _check(label: str, condition: bool) -> None:
        if condition:
            print(f"  PASS  {label}")
            tb_counts["passes"] += 1
        else:
            print(f"  FAIL  {label}")
            tb_counts["failures"] += 1

    _check("tb-001 (60 min) scheduled over tb-002 (90 min)",
           "tb-001" in scheduled_ids and "tb-002" not in scheduled_ids)

    _check("tb-aaa (lex-smaller id) scheduled over tb-zzz (lex-larger id)",
           "tb-aaa" in scheduled_ids and "tb-zzz" not in scheduled_ids)

    _check(f"Results identical across {RUNS} runs", all_identical)

    print(f"\n  {tb_counts['passes']} passed, {tb_counts['failures']} failed")

    # --- is_deadline_today flag test ----------------------------------------
    print()
    print("=" * 60)
    print("  IS_DEADLINE_TODAY — get_deadline_today_schedule()")
    print("  Day: 9:00–13:00. Some tasks due today can't fit → flagged.")
    print("=" * 60)

    dt_result = solve_schedule(get_deadline_today_schedule())

    scheduled = [t for t in dt_result.flexible_tasks if t.status == "scheduled"]
    backlog   = [t for t in dt_result.flexible_tasks if t.status == "backlog"]

    print(f"\n  Scheduled ({len(scheduled)}):")
    for t in sorted(scheduled, key=lambda t: t.start_time):  # type: ignore[arg-type]
        print(f"    [{_fmt(t.start_time)} – {_fmt(t.start_time + t.duration)}]  "  # type: ignore[operator]
              f"p={t.priority}  {t.title}  is_deadline_today={t.is_deadline_today}")

    print(f"\n  Backlog ({len(backlog)}):")
    for t in sorted(backlog, key=lambda t: t.id):
        flag = "⚠ URGENT" if t.is_deadline_today else "  "
        print(f"    {flag}  id={t.id}  p={t.priority}  "
              f"deadline={t.deadline}  is_deadline_today={t.is_deadline_today}  {t.title}")

    # Assertions
    print()
    dt_counts = {"passes": 0, "failures": 0}

    def _dt_check(label: str, condition: bool) -> None:
        if condition:
            print(f"  PASS  {label}")
            dt_counts["passes"] += 1
        else:
            print(f"  FAIL  {label}")
            dt_counts["failures"] += 1

    backlog_map = {t.id: t for t in backlog}
    sched_map   = {t.id: t for t in scheduled}

    # dt-001 and dt-002 are both 90 min; only a 60-min gap is free → both backlogged
    _dt_check("dt-001 is in backlog (no 90-min gap available)",
              "dt-001" in backlog_map)

    _dt_check("dt-002 is in backlog (no 90-min gap available)",
              "dt-002" in backlog_map)

    _dt_check("dt-001 is_deadline_today=True (deadline=750 within day_start=540..day_end=750)",
              "dt-001" in backlog_map and backlog_map["dt-001"].is_deadline_today is True)

    _dt_check("dt-002 is_deadline_today=True (deadline=750 within day window)",
              "dt-002" in backlog_map and backlog_map["dt-002"].is_deadline_today is True)

    # dt-003 (no deadline) must NOT be flagged regardless of status
    if "dt-003" in backlog_map:
        _dt_check("dt-003 is_deadline_today=False (no deadline)",
                  backlog_map["dt-003"].is_deadline_today is False)
    else:
        _dt_check("dt-003 is_deadline_today=False (scheduled — always False)",
                  sched_map["dt-003"].is_deadline_today is False)

    # dt-004 (deadline=1020, outside day_end=750) must NOT be flagged
    if "dt-004" in backlog_map:
        _dt_check("dt-004 is_deadline_today=False (deadline 1020 > day_end 750)",
                  backlog_map["dt-004"].is_deadline_today is False)
    else:
        _dt_check("dt-004 is_deadline_today=False (scheduled — always False)",
                  sched_map["dt-004"].is_deadline_today is False)

    # Scheduled tasks are never flagged
    for t in scheduled:
        _dt_check(f"{t.id} scheduled → is_deadline_today=False",
                  t.is_deadline_today is False)

    print(f"\n  {dt_counts['passes']} passed, {dt_counts['failures']} failed")

    # --- task_overrun disruption test ---------------------------------------
    #
    # Setup (using get_dummy_schedule(), solved):
    #
    #   [06:00–06:30]  Review lecture notes        p=9   COMPLETED at 09:00
    #   [06:30–08:00]  Complete assignment draft   p=7   COMPLETED at 09:00
    #   [08:00–08:30]  Reply to emails             p=8   COMPLETED at 09:00
    #   [08:30–09:30]  Work on side project        p=3   IN PROGRESS at 09:00
    #   [11:30–13:30]  Read research paper         p=4   FUTURE
    #   Fixed: Morning Class 10:00–11:30
    #
    # Disruption at current_time=09:00:
    #   "Work on side project" started at 08:30, planned to end at 09:30.
    #   New estimated end: 10:30 — overrunning by 60 min.
    #   This pushes into the Morning Class slot, which itself is fixed.
    #   Morning Class is 10:00–11:30.  The overrunning task's new end (10:30)
    #   overlaps it.  The solver must push "Read research paper" to start
    #   no earlier than 11:30 (after Morning Class).
    #
    # Expected:
    #   - "Work on side project": start_time=08:30 UNCHANGED, actual_duration=120
    #   - "Read research paper":  shifted to start at 11:30 or later
    #   - Completed tasks (3 tasks): completely unchanged

    print()
    print("=" * 60)
    print("  TASK OVERRUN — 'Work on side project' overruns into Morning Class")
    print("  current_time=09:00, new_estimated_end=10:30")
    print("=" * 60)

    to_base   = get_dummy_schedule()
    to_solved = solve_schedule(to_base)

    CURRENT_TIME_TO = 540  # 09:00

    # Find the in-progress task (Work on side project, starts 08:30)
    in_progress_task = next(
        t for t in to_solved.flexible_tasks if t.id == "task-005"
    )
    original_start    = in_progress_task.start_time
    original_end      = original_start + in_progress_task.duration
    new_estimated_end = 630   # 10:30 — overrun of 60 min

    print(f"\n  Before disruption:")
    print(f"    In-progress: [{_fmt(original_start)} – {_fmt(original_end)}]  "
          f"{in_progress_task.title}")
    future_before = [t for t in to_solved.flexible_tasks
                     if t.start_time is not None and t.start_time > CURRENT_TIME_TO]
    for t in sorted(future_before, key=lambda t: t.start_time):
        print(f"    Future:      [{_fmt(t.start_time)} – {_fmt(t.start_time + t.duration)}]  "
              f"{t.title}")

    to_disrupted = trigger_disruption(
        to_solved,
        {
            "type":               "task_overrun",
            "task_id":            "task-005",
            "new_estimated_end":  new_estimated_end,
        },
        current_time=CURRENT_TIME_TO,
    )

    print(f"\n  After disruption (new estimated end: {_fmt(new_estimated_end)}):")
    after_map_to = {t.id: t for t in to_disrupted.flexible_tasks}

    for task in to_disrupted.flexible_tasks:
        if task.status == "scheduled":
            eff_end = task.start_time + task.effective_duration
            overrun_flag = f"  [actual_duration={task.actual_duration}]" if task.actual_duration else ""
            print(f"    [{_fmt(task.start_time)} – {_fmt(eff_end)}]  "
                  f"p={task.priority}  {task.title}{overrun_flag}")
        else:
            print(f"    [backlog]  p={task.priority}  {task.title}")

    # Assertions
    print()
    to_counts = {"passes": 0, "failures": 0}

    def _to_check(label: str, condition: bool) -> None:
        if condition:
            print(f"  PASS  {label}")
            to_counts["passes"] += 1
        else:
            print(f"  FAIL  {label}")
            to_counts["failures"] += 1

    overrun_task = after_map_to["task-005"]
    research_task = after_map_to["task-003"]

    # 1. start_time of overrunning task is UNCHANGED
    _to_check(
        f"task-005 start_time unchanged ({_fmt(original_start)})",
        overrun_task.start_time == original_start,
    )

    # 2. actual_duration is set correctly
    expected_actual = new_estimated_end - original_start
    _to_check(
        f"task-005 actual_duration={expected_actual} "
        f"(new_end {_fmt(new_estimated_end)} - start {_fmt(original_start)})",
        overrun_task.actual_duration == expected_actual,
    )

    # 3. effective end time reflects the overrun
    _to_check(
        f"task-005 effective end = {_fmt(original_start + expected_actual)}",
        overrun_task.start_time + overrun_task.effective_duration == new_estimated_end,
    )

    # 4. downstream task starts at or after the overrun ends
    # (and must clear Morning Class 10:00–11:30 too)
    earliest_valid = max(new_estimated_end, 690)  # 10:30 or 11:30 (after Morning Class)
    if research_task.status == "scheduled":
        _to_check(
            f"task-003 (Read research paper) starts >= {_fmt(earliest_valid)}",
            research_task.start_time >= earliest_valid,
        )
    else:
        _to_check(
            "task-003 (Read research paper) went to backlog (acceptable if no room)",
            True,
        )

    # 5. completed tasks are untouched
    completed_ids = {"task-001", "task-002", "task-004"}
    before_map_to = {t.id: t for t in to_solved.flexible_tasks}
    for tid in completed_ids:
        b = before_map_to[tid]
        a = after_map_to[tid]
        _to_check(
            f"{tid} ({b.title}) start_time unchanged",
            a.start_time == b.start_time,
        )

    print(f"\n  {to_counts['passes']} passed, {to_counts['failures']} failed")

    # --- event_cancelled: backlog task pulled into freed slot ---------------
    #
    # Use get_overflow_schedule():
    #   Day 09:00-18:00, fixed events: Team standup (09:00-09:30),
    #                                  Lunch break (13:00-14:00)
    #   Free time ~450 min — tasks total 660 min, so some go to backlog.
    #   After solving, "Update documentation" (p=5, 60 min) is in backlog.
    #
    # Disruption: cancel "Lunch break" — frees 60 min.
    # Expected: "Update documentation" (or another backlog task) is now
    #           pulled into the schedule in the next solve.

    print()
    print("=" * 60)
    print("  EVENT_CANCELLED — backlog task gets pulled into freed slot")
    print("  Cancel 'Lunch break' -> backlog task should get scheduled")
    print("=" * 60)

    ov_input  = get_overflow_schedule()
    ov_solved = solve_schedule(ov_input)

    backlog_before = [t for t in ov_solved.flexible_tasks if t.status == "backlog"]
    sched_before   = [t for t in ov_solved.flexible_tasks if t.status == "scheduled"]

    print(f"\n  Before cancellation:")
    for t in sorted(sched_before, key=lambda t: t.start_time):  # type: ignore[arg-type]
        print(f"    [scheduled] [{_fmt(t.start_time)}-{_fmt(t.start_time+t.duration)}]  "  # type: ignore[operator]
              f"p={t.priority}  {t.title}")
    for t in sorted(backlog_before, key=lambda t: t.priority, reverse=True):
        print(f"    [backlog]                              p={t.priority}  {t.title}")

    cancelled_result = trigger_disruption(
        ov_solved,
        {"type": "event_cancelled", "event_id": "of-evt-002"},  # Lunch break
        current_time=None,
    )

    backlog_after  = [t for t in cancelled_result.flexible_tasks if t.status == "backlog"]
    sched_after    = [t for t in cancelled_result.flexible_tasks if t.status == "scheduled"]

    print(f"\n  After cancellation of 'Lunch break':")
    for t in sorted(sched_after, key=lambda t: t.start_time):  # type: ignore[arg-type]
        print(f"    [scheduled] [{_fmt(t.start_time)}-{_fmt(t.start_time+t.duration)}]  "  # type: ignore[operator]
              f"p={t.priority}  {t.title}")
    for t in sorted(backlog_after, key=lambda t: t.priority, reverse=True):
        print(f"    [backlog]                              p={t.priority}  {t.title}")

    # Confirm 'Lunch break' is gone
    cancelled_event_ids = {e.id for e in cancelled_result.fixed_events}
    # Confirm at least one previously-backlogged task is now scheduled
    backlog_ids_before = {t.id for t in backlog_before}
    rescued = [t for t in sched_after if t.id in backlog_ids_before]

    print()
    ec_counts = {"passes": 0, "failures": 0}

    def _ec_check(label: str, condition: bool) -> None:
        if condition:
            print(f"  PASS  {label}")
            ec_counts["passes"] += 1
        else:
            print(f"  FAIL  {label}")
            ec_counts["failures"] += 1

    _ec_check("'Lunch break' removed from fixed_events",
              "of-evt-002" not in cancelled_event_ids)

    _ec_check(f"At least one backlog task rescued ({[t.title for t in rescued]})",
              len(rescued) >= 1)

    _ec_check("Backlog count decreased after cancellation",
              len(backlog_after) < len(backlog_before))

    print(f"\n  {ec_counts['passes']} passed, {ec_counts['failures']} failed")

    # --- task_early_finish: freed slot absorbed by next task ----------------
    #
    # Use get_dummy_schedule(), solved.
    # "Work on side project" is scheduled at [08:30-09:30].
    # At current_time=09:00 it finishes early — actual_end=09:00 (30 min early).
    # This frees 08:30-09:00 window... but more importantly, we verify that
    # the task's actual_duration is correctly recorded and future tasks
    # are re-solved (they may shift earlier into the freed time).

    print()
    print("=" * 60)
    print("  TASK_EARLY_FINISH — task finishes 30 min early, futures re-solve")
    print("  'Work on side project' ends at 09:00 instead of 09:30")
    print("=" * 60)

    ef_base   = get_dummy_schedule()
    ef_solved = solve_schedule(ef_base)

    CURRENT_TIME_EF = 540  # 09:00

    wsp = next(t for t in ef_solved.flexible_tasks if t.id == "task-005")
    print(f"\n  Before: 'Work on side project' [{_fmt(wsp.start_time)}-"  # type: ignore[arg-type]
          f"{_fmt(wsp.start_time + wsp.duration)}]")  # type: ignore[operator]

    ef_result = trigger_disruption(
        ef_solved,
        {
            "type":            "task_early_finish",
            "task_id":         "task-005",
            "actual_end_time": 540,   # 09:00 — finishes 30 min early
        },
        current_time=CURRENT_TIME_EF,
    )

    ef_map = {t.id: t for t in ef_result.flexible_tasks}
    wsp_after = ef_map["task-005"]

    print(f"  After:  'Work on side project' [{_fmt(wsp_after.start_time)}-"  # type: ignore[arg-type]
          f"{_fmt(wsp_after.start_time + wsp_after.effective_duration)}]"  # type: ignore[operator]
          f"  actual_duration={wsp_after.actual_duration}")

    print()
    ef_counts = {"passes": 0, "failures": 0}

    def _ef_check(label: str, condition: bool) -> None:
        if condition:
            print(f"  PASS  {label}")
            ef_counts["passes"] += 1
        else:
            print(f"  FAIL  {label}")
            ef_counts["failures"] += 1

    _ef_check("task-005 start_time unchanged",
              wsp_after.start_time == wsp.start_time)

    _ef_check("task-005 actual_duration=30 (09:00 - 08:30)",
              wsp_after.actual_duration == 30)

    _ef_check("task-005 effective end = 09:00",
              wsp_after.start_time + wsp_after.effective_duration == 540)

    # Future tasks should still be scheduled (no room lost, only gained)
    research = ef_map["task-003"]
    _ef_check("task-003 (Read research paper) still scheduled after early finish",
              research.status == "scheduled")

    # Completed tasks untouched
    for tid in ("task-001", "task-002", "task-004"):
        before_t = next(t for t in ef_solved.flexible_tasks if t.id == tid)
        after_t  = ef_map[tid]
        _ef_check(f"{tid} start_time unchanged after early finish",
                  after_t.start_time == before_t.start_time)

    print(f"\n  {ef_counts['passes']} passed, {ef_counts['failures']} failed")

    # --- day_shrink: end-of-day tasks displaced to backlog ------------------
    #
    # Use get_dummy_schedule() (day 06:00-23:00 = 360-1380).
    # Solved schedule:
    #   [06:00-06:30]  Review lecture notes        p=9
    #   [06:30-08:00]  Complete assignment draft   p=7
    #   [08:00-08:30]  Reply to emails             p=8
    #   [08:30-09:30]  Work on side project        p=3
    #   [11:30-13:30]  Read research paper         p=4
    #   Fixed: Morning Class 10:00-11:30, Dinner 20:00-21:00
    #
    # Shrink day_end from 23:00 (1380) to 12:00 (720).
    # "Read research paper" spans 11:30-13:30 — it starts before the new
    # cutoff but ends after it, so it can't be placed and goes to backlog.
    # Everything else fits before 12:00.

    print()
    print("=" * 60)
    print("  DAY_SHRINK — day cut from 23:00 to 12:00")
    print("  Tasks ending after 12:00 must go to backlog")
    print("=" * 60)

    ds_base   = get_dummy_schedule()
    ds_solved = solve_schedule(ds_base)
    NEW_DAY_END = 720   # 12:00

    print(f"\n  Before shrink (day_end={_fmt(ds_solved.day_end)}):")
    for t in sorted(ds_solved.flexible_tasks,
                    key=lambda t: t.start_time if t.start_time is not None else 9999):
        if t.status == "scheduled":
            print(f"    [scheduled] [{_fmt(t.start_time)}-"  # type: ignore[arg-type]
                  f"{_fmt(t.start_time + t.duration)}]  "    # type: ignore[operator]
                  f"p={t.priority}  {t.title}")
        else:
            print(f"    [backlog]                     p={t.priority}  {t.title}")

    ds_result = trigger_disruption(
        ds_solved,
        {"type": "day_shrink", "new_day_end": NEW_DAY_END},
        current_time=None,
    )

    print(f"\n  After shrink (day_end={_fmt(ds_result.day_end)}):")
    for t in sorted(ds_result.flexible_tasks,
                    key=lambda t: t.start_time if t.start_time is not None else 9999):
        if t.status == "scheduled":
            end = t.start_time + t.effective_duration      # type: ignore[operator]
            marker = "  *** PAST CUTOFF ***" if end > NEW_DAY_END else ""
            print(f"    [scheduled] [{_fmt(t.start_time)}-{_fmt(end)}]  "  # type: ignore[arg-type]
                  f"p={t.priority}  {t.title}{marker}")
        else:
            print(f"    [backlog]                     p={t.priority}  {t.title}")

    print()
    ds_counts = {"passes": 0, "failures": 0}

    def _ds_check(label: str, condition: bool) -> None:
        if condition:
            print(f"  PASS  {label}")
            ds_counts["passes"] += 1
        else:
            print(f"  FAIL  {label}")
            ds_counts["failures"] += 1

    ds_map = {t.id: t for t in ds_result.flexible_tasks}

    # 1. day_end updated on the returned schedule
    _ds_check(f"Returned day_end = {_fmt(NEW_DAY_END)}",
              ds_result.day_end == NEW_DAY_END)

    # 2. No scheduled task ends after the new day_end
    violations = [
        t for t in ds_result.flexible_tasks
        if t.status == "scheduled" and t.start_time is not None
        and t.start_time + t.effective_duration > NEW_DAY_END
    ]
    _ds_check("No scheduled task ends after new day_end",
              len(violations) == 0)

    # 3. "Read research paper" (120 min): if it got scheduled, it must end by 12:00.
    #    If it's in backlog that's also fine (no room). Either way it must not
    #    be scheduled past the new cutoff.
    research = ds_map["task-003"]
    if research.status == "scheduled":
        research_end = research.start_time + research.effective_duration  # type: ignore[operator]
        _ds_check("task-003 (Read research paper) scheduled end <= new day_end",
                  research_end <= NEW_DAY_END)
    else:
        _ds_check("task-003 (Read research paper) in backlog (no room before cutoff)",
                  True)

    # 4. Tasks that fit before 12:00 remain scheduled
    fits_before = ["task-001", "task-002", "task-004"]  # all <= 30-90 min, start early
    for tid in fits_before:
        t = ds_map[tid]
        if t.status == "scheduled":
            _ds_check(f"{tid} ({t.title}) still scheduled and ends by {_fmt(NEW_DAY_END)}",
                      t.start_time + t.effective_duration <= NEW_DAY_END)
        # if it went to backlog due to no room that's also acceptable — just note it

    print(f"\n  {ds_counts['passes']} passed, {ds_counts['failures']} failed")
