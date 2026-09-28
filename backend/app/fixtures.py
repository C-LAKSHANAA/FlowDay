"""
fixtures.py

Hardcoded sample data for development and testing.

Week used in get_dummy_week_schedule(): 2026-09-28 (Mon) – 2026-10-04 (Sun)

Day design principles:
  - Weekdays (Mon–Fri): earlier start, 2 fixed events (a class/meeting + dinner),
    work/study flavoured tasks.
  - Saturday: later start, 1 fixed event (gym), leisure-flavoured tasks.
  - Sunday: latest start, 1 fixed event (family lunch), light tasks + rest.
"""

from app.models import DaySchedule, FixedEvent, FlexibleTask, WeekSchedule


# ---------------------------------------------------------------------------
# Single-day fixtures (used independently by solver tests / API demo)
# ---------------------------------------------------------------------------

def get_dummy_schedule() -> DaySchedule:
    """
    Returns a hardcoded sample DaySchedule for testing and development.

    Day window: 6:00 AM – 11:00 PM
    Includes 2 fixed events and 5 flexible tasks with varied priorities/deadlines.
    """

    day_start = 360   # 6:00 AM
    day_end   = 1380  # 11:00 PM

    fixed_events = [
        FixedEvent(
            id="evt-001",
            title="Morning Class",
            start_time=600,   # 10:00 AM
            end_time=690,     # 11:30 AM
        ),
        FixedEvent(
            id="evt-002",
            title="Dinner",
            start_time=1200,  # 8:00 PM
            end_time=1260,    # 9:00 PM
        ),
    ]

    flexible_tasks = [
        FlexibleTask(
            id="task-001",
            title="Review lecture notes",
            duration=30,
            priority=9,
            deadline=600,     # must finish by 10:00 AM
        ),
        FlexibleTask(
            id="task-002",
            title="Complete assignment draft",
            duration=90,
            priority=7,
            deadline=780,     # 1:00 PM
        ),
        FlexibleTask(
            id="task-003",
            title="Read research paper",
            duration=120,
            priority=4,
        ),
        FlexibleTask(
            id="task-004",
            title="Reply to emails",
            duration=30,
            priority=8,
            deadline=1140,    # 7:00 PM
        ),
        FlexibleTask(
            id="task-005",
            title="Work on side project",
            duration=60,
            priority=3,
        ),
    ]

    return DaySchedule(
        date="2026-09-24",
        day_start=day_start,
        day_end=day_end,
        fixed_events=fixed_events,
        flexible_tasks=flexible_tasks,
    )


def get_overflow_schedule() -> DaySchedule:
    """
    Returns a DaySchedule where flexible tasks intentionally exceed available
    free time, forcing the solver to drop lower-priority tasks to backlog.

    Day window: 9:00 AM – 6:00 PM → 540 min total.
    Fixed events block 90 min → 450 min free.
    Tasks total 660 min → 210 min must go to backlog.
    """

    day_start = 540   # 9:00 AM
    day_end   = 1080  # 6:00 PM

    fixed_events = [
        FixedEvent(id="of-evt-001", title="Team standup",
                   start_time=540, end_time=570),
        FixedEvent(id="of-evt-002", title="Lunch break",
                   start_time=780, end_time=840),
    ]

    flexible_tasks = [
        FlexibleTask(id="of-task-001", title="Critical bug fix",
                     duration=60,  priority=10),
        FlexibleTask(id="of-task-002", title="Client presentation prep",
                     duration=90,  priority=9),
        FlexibleTask(id="of-task-003", title="Architecture review",
                     duration=120, priority=8),
        FlexibleTask(id="of-task-004", title="Code review PRs",
                     duration=60,  priority=7),
        FlexibleTask(id="of-task-005", title="Write unit tests",
                     duration=90,  priority=6),
        FlexibleTask(id="of-task-006", title="Update documentation",
                     duration=60,  priority=5),
        FlexibleTask(id="of-task-007", title="Refactor legacy module",
                     duration=90,  priority=3),
        FlexibleTask(id="of-task-008", title="Read engineering blog posts",
                     duration=90,  priority=2),
    ]

    return DaySchedule(
        date="2026-09-25",
        day_start=day_start,
        day_end=day_end,
        fixed_events=fixed_events,
        flexible_tasks=flexible_tasks,
    )


# ---------------------------------------------------------------------------
# Week fixture
# ---------------------------------------------------------------------------

def get_dummy_week_schedule() -> WeekSchedule:
    """
    Returns a WeekSchedule for the week of 2026-09-28 (Mon) – 2026-10-04 (Sun).

    Structure per day type
    ----------------------
    Mon–Fri  6:00 AM–11:00 PM  2 fixed events (class/meeting + dinner)
             work/study tasks, progressively lighter towards Friday
    Saturday 8:00 AM–11:00 PM  1 fixed event (gym), leisure tasks
    Sunday   9:00 AM–10:00 PM  1 fixed event (family lunch), very light tasks
    """

    # ------------------------------------------------------------------
    # Monday 2026-09-28 — heavy study day
    # ------------------------------------------------------------------
    mon = DaySchedule(
        date="2026-09-28",
        day_start=360,   # 6:00 AM
        day_end=1380,    # 11:00 PM
        fixed_events=[
            FixedEvent(id="mon-evt-001", title="Lecture",
                       start_time=540, end_time=660),    # 9:00–11:00 AM
            FixedEvent(id="mon-evt-002", title="Dinner",
                       start_time=1140, end_time=1200),  # 7:00–8:00 PM
        ],
        flexible_tasks=[
            FlexibleTask(id="mon-t-001", title="Review Monday lecture notes",
                         duration=45, priority=9, deadline=780),   # by 1 PM
            FlexibleTask(id="mon-t-002", title="Complete problem set",
                         duration=120, priority=8, deadline=1080),  # by 6 PM
            FlexibleTask(id="mon-t-003", title="Read assigned chapter",
                         duration=60, priority=6),
            FlexibleTask(id="mon-t-004", title="Reply to professor email",
                         duration=15, priority=7, deadline=1020),   # by 5 PM
            FlexibleTask(id="mon-t-005", title="Gym workout",
                         duration=60, priority=4),
        ],
    )

    # ------------------------------------------------------------------
    # Tuesday 2026-09-29 — lab + group work
    # ------------------------------------------------------------------
    tue = DaySchedule(
        date="2026-09-29",
        day_start=360,
        day_end=1380,
        fixed_events=[
            FixedEvent(id="tue-evt-001", title="Lab Session",
                       start_time=600, end_time=750),    # 10:00 AM–12:30 PM
            FixedEvent(id="tue-evt-002", title="Dinner",
                       start_time=1140, end_time=1200),
        ],
        flexible_tasks=[
            FlexibleTask(id="tue-t-001", title="Write lab report intro",
                         duration=45, priority=9, deadline=1020),
            FlexibleTask(id="tue-t-002", title="Group project research",
                         duration=90, priority=8),
            FlexibleTask(id="tue-t-003", title="Flashcard review",
                         duration=30, priority=5, deadline=840),    # by 2 PM
            FlexibleTask(id="tue-t-004", title="Tidy notes from last week",
                         duration=30, priority=3),
            FlexibleTask(id="tue-t-005", title="Exercise — short run",
                         duration=45, priority=4),
        ],
    )

    # ------------------------------------------------------------------
    # Wednesday 2026-09-30 — mid-week, lighter class load
    # ------------------------------------------------------------------
    wed = DaySchedule(
        date="2026-09-30",
        day_start=360,
        day_end=1380,
        fixed_events=[
            FixedEvent(id="wed-evt-001", title="Tutorial",
                       start_time=660, end_time=750),    # 11:00 AM–12:30 PM
            FixedEvent(id="wed-evt-002", title="Dinner",
                       start_time=1140, end_time=1200),
        ],
        flexible_tasks=[
            FlexibleTask(id="wed-t-001", title="Assignment draft — section 2",
                         duration=90, priority=9, deadline=1080),
            FlexibleTask(id="wed-t-002", title="Read research paper",
                         duration=60, priority=6),
            FlexibleTask(id="wed-t-003", title="Reply to emails",
                         duration=20, priority=7, deadline=900),    # by 3 PM
            FlexibleTask(id="wed-t-004", title="Work on side project",
                         duration=60, priority=3),
            FlexibleTask(id="wed-t-005", title="Meditation / break",
                         duration=20, priority=2),
        ],
    )

    # ------------------------------------------------------------------
    # Thursday 2026-10-01 — presentation prep day
    # ------------------------------------------------------------------
    thu = DaySchedule(
        date="2026-10-01",
        day_start=360,
        day_end=1380,
        fixed_events=[
            FixedEvent(id="thu-evt-001", title="Study Group",
                       start_time=780, end_time=900),    # 1:00–3:00 PM
            FixedEvent(id="thu-evt-002", title="Dinner",
                       start_time=1140, end_time=1200),
        ],
        flexible_tasks=[
            FlexibleTask(id="thu-t-001", title="Finalise presentation slides",
                         duration=90, priority=10, deadline=1080),
            FlexibleTask(id="thu-t-002", title="Practise presentation",
                         duration=45, priority=9, deadline=1140),
            FlexibleTask(id="thu-t-003", title="Complete lab report",
                         duration=60, priority=8, deadline=1020),
            FlexibleTask(id="thu-t-004", title="Review classmate's draft",
                         duration=30, priority=5),
            FlexibleTask(id="thu-t-005", title="Gym workout",
                         duration=60, priority=3),
        ],
    )

    # ------------------------------------------------------------------
    # Friday 2026-10-02 — presentation day, lighter afternoon
    # ------------------------------------------------------------------
    fri = DaySchedule(
        date="2026-10-02",
        day_start=360,
        day_end=1380,
        fixed_events=[
            FixedEvent(id="fri-evt-001", title="Group Presentation",
                       start_time=600, end_time=720),    # 10:00 AM–12:00 PM
            FixedEvent(id="fri-evt-002", title="Dinner",
                       start_time=1140, end_time=1200),
        ],
        flexible_tasks=[
            FlexibleTask(id="fri-t-001", title="Submit final assignment",
                         duration=30, priority=10, deadline=840),   # by 2 PM
            FlexibleTask(id="fri-t-002", title="Catch up on reading",
                         duration=60, priority=5),
            FlexibleTask(id="fri-t-003", title="Plan next week",
                         duration=30, priority=6),
            FlexibleTask(id="fri-t-004", title="Watch lecture recording",
                         duration=45, priority=4),
            FlexibleTask(id="fri-t-005", title="Social / wind-down",
                         duration=60, priority=2),
        ],
    )

    # ------------------------------------------------------------------
    # Saturday 2026-10-03 — rest and leisure, later start
    # ------------------------------------------------------------------
    sat = DaySchedule(
        date="2026-10-03",
        day_start=480,   # 8:00 AM
        day_end=1380,    # 11:00 PM
        fixed_events=[
            FixedEvent(id="sat-evt-001", title="Gym",
                       start_time=540, end_time=660),    # 9:00–11:00 AM
        ],
        flexible_tasks=[
            FlexibleTask(id="sat-t-001", title="Grocery shopping",
                         duration=60, priority=8, deadline=780),    # by 1 PM
            FlexibleTask(id="sat-t-002", title="Meal prep",
                         duration=60, priority=6),
            FlexibleTask(id="sat-t-003", title="Read for pleasure",
                         duration=90, priority=4),
            FlexibleTask(id="sat-t-004", title="Work on side project",
                         duration=90, priority=5),
            FlexibleTask(id="sat-t-005", title="Watch a film",
                         duration=120, priority=2),
        ],
    )

    # ------------------------------------------------------------------
    # Sunday 2026-10-04 — rest day, latest start
    # ------------------------------------------------------------------
    sun = DaySchedule(
        date="2026-10-04",
        day_start=540,   # 9:00 AM
        day_end=1320,    # 10:00 PM
        fixed_events=[
            FixedEvent(id="sun-evt-001", title="Family Lunch",
                       start_time=720, end_time=840),    # 12:00–2:00 PM
        ],
        flexible_tasks=[
            FlexibleTask(id="sun-t-001", title="Light review of week ahead",
                         duration=30, priority=7, deadline=1020),
            FlexibleTask(id="sun-t-002", title="Journaling",
                         duration=20, priority=5),
            FlexibleTask(id="sun-t-003", title="Walk outside",
                         duration=45, priority=6),
            FlexibleTask(id="sun-t-004", title="Call a friend",
                         duration=30, priority=4),
            FlexibleTask(id="sun-t-005", title="Read for pleasure",
                         duration=60, priority=3),
        ],
    )

    return WeekSchedule(
        week_start_date="2026-09-28",
        days=[mon, tue, wed, thu, fri, sat, sun],
    )


# ---------------------------------------------------------------------------
# __main__
# ---------------------------------------------------------------------------

def get_deadline_today_schedule() -> DaySchedule:
    """
    Fixture for testing the is_deadline_today flag on backlog tasks.

    Scenario
    --------
    Day window: 9:00 AM – 12:30 PM  (540 – 750 min)  →  210 min total.
    Fixed event blocks 60 min → 150 min available for flexible tasks.

    Tasks are intentionally over-capacity so some go to backlog:
      - "Urgent report"    (dt-001): 90 min, priority=9, deadline=750 (12:30 PM today)
      - "Critical review"  (dt-002): 90 min, priority=9, deadline=750 (12:30 PM today)
        Both have the same priority and deadline. Only ONE 90-min slot exists
        after the fixed event (10:00–11:30 is the only 90-min gap).
        The other must go to backlog with is_deadline_today=True.
      - "Someday reading"  (dt-003): 60 min, priority=3, no deadline
        → low priority, no deadline → backlog with is_deadline_today=False
      - "Tomorrow's prep"  (dt-004): 60 min, priority=5, deadline=1020 (5:00 PM)
        → deadline is outside today's window (day_end=750) → is_deadline_today=False

    Available gaps after fixed event (10:00–11:30 is fixed, so only one 90-min gap):
      600–690: only 90 min — fits exactly ONE of dt-001/dt-002

    Expected backlog:
      One of dt-001/dt-002: is_deadline_today=True   (deadline within day window)
      dt-003:               is_deadline_today=False  (no deadline)
      dt-004:               is_deadline_today=False  (deadline outside day window)
    """

    day_start = 540   # 9:00 AM
    day_end   = 750   # 12:30 PM  →  210 min total

    return DaySchedule(
        date="2026-10-06",
        day_start=day_start,
        day_end=day_end,
        fixed_events=[
            FixedEvent(
                id="dt-evt-001",
                title="Morning standup",
                start_time=540,   # 9:00 AM
                end_time=600,     # 10:00 AM  (60 min)
            ),
            FixedEvent(
                id="dt-evt-002",
                title="Team sync",
                start_time=660,   # 11:00 AM
                end_time=750,     # 12:30 PM  (90 min — blocks the second slot)
            ),
        ],
        flexible_tasks=[
            # Only one 90-min window exists (9:00–10:00 is 60 min, 10:00–11:00 is 60 min)
            # Wait — with the two fixed events, free time = 540–600 (60 min) + nothing else
            # Actually: 10:00–11:00 = 60 min free between the two fixed events
            # Neither 90-min task can fit! Both go to backlog with is_deadline_today=True.
            FlexibleTask(
                id="dt-001",
                title="Urgent report",
                duration=90,
                priority=9,
                deadline=750,     # 12:30 PM today
            ),
            FlexibleTask(
                id="dt-002",
                title="Critical review",
                duration=90,
                priority=9,
                deadline=750,     # 12:30 PM today
            ),
            FlexibleTask(
                id="dt-003",
                title="Someday reading",
                duration=60,
                priority=3,
                deadline=None,    # no deadline
            ),
            FlexibleTask(
                id="dt-004",
                title="Tomorrow's prep",
                duration=60,
                priority=5,
                deadline=1020,    # 5:00 PM — outside day_end (750)
            ),
        ],
    )


def get_dependency_schedule() -> DaySchedule:
    """
    Fixture for testing task precedence (depends_on).

    Scenario A — normal fit
    -----------------------
    Day 09:00-13:00 (240 min), no fixed events.
    Task A: 60 min, p=7
    Task B: 60 min, p=8, depends_on="dep-a"
    Both fit. Expected: B is scheduled AFTER A finishes.

    Scenario B — dependency forced to backlog
    -----------------------------------------
    See get_dependency_overflow_schedule().
    """
    return DaySchedule(
        date="2026-10-07",
        day_start=540,   # 09:00
        day_end=780,     # 13:00
        fixed_events=[],
        flexible_tasks=[
            FlexibleTask(
                id="dep-a",
                title="Task A (prerequisite)",
                duration=60,
                priority=7,
            ),
            FlexibleTask(
                id="dep-b",
                title="Task B (depends on A)",
                duration=60,
                priority=8,
                depends_on="dep-a",
            ),
        ],
    )


def get_dependency_overflow_schedule() -> DaySchedule:
    """
    Fixture where the dependency task (A) is forced to backlog due to
    overflow, which must also force its dependent (B) to backlog.

    Day 09:00-10:00 (60 min), no fixed events.
    Three tasks, only ONE can fit:
      - Task A: 60 min, p=5  (medium priority — may or may not win)
      - Task C: 60 min, p=9  (highest priority — will win the slot)
      - Task B: 60 min, p=8, depends_on="dep-ov-a"

    C wins the only 60-min slot.
    A goes to backlog (lower priority than C).
    B must also go to backlog because its dependency A is unscheduled.
    """
    return DaySchedule(
        date="2026-10-08",
        day_start=540,   # 09:00
        day_end=600,     # 10:00 — only 60 min
        fixed_events=[],
        flexible_tasks=[
            FlexibleTask(
                id="dep-ov-c",
                title="Task C (independent, highest priority)",
                duration=60,
                priority=9,
            ),
            FlexibleTask(
                id="dep-ov-a",
                title="Task A (prerequisite, medium priority)",
                duration=60,
                priority=5,
            ),
            FlexibleTask(
                id="dep-ov-b",
                title="Task B (depends on A)",
                duration=60,
                priority=8,
                depends_on="dep-ov-a",
            ),
        ],
    )


def get_tiebreak_schedule() -> DaySchedule:
    """
    Fixture for testing deterministic tie-breaking in the solver objective.

    Scenario
    --------
    Day window: 9:00 AM – 11:00 AM  (540 – 660 min)  →  120 min free.
    No fixed events.

    Two tasks share identical priority (7) and deadline (660 = 11:00 AM),
    but have different durations:
      - "Short task"  (tb-001): 60 min
      - "Long task"   (tb-002): 90 min

    Only ONE can fit in the 120-minute window alongside each other, because
    60 + 90 = 150 > 120.  The solver must drop one.

    Expected outcome (secondary tie-break: prefer shorter):
      → "Short task"  (60 min)  scheduled
      → "Long task"   (90 min)  backlog

    A third task with identical priority, deadline, AND duration tests the
    tertiary tie-break (lexicographically smaller id wins):
      - "Short task A" (tb-aaa): 60 min
      - "Short task B" (tb-zzz): 60 min
    Only one of the two 60-min tasks fits alongside the already-dropped 90-min
    scenario. tb-aaa < tb-zzz lexicographically, so tb-aaa is preferred.
    """

    day_start = 540   # 9:00 AM
    day_end   = 660   # 11:00 AM  (120 min window)

    return DaySchedule(
        date="2026-10-05",
        day_start=day_start,
        day_end=day_end,
        fixed_events=[],
        flexible_tasks=[
            # Primary pair: same priority + deadline, different duration
            FlexibleTask(
                id="tb-001",
                title="Short task (60 min)",
                duration=60,
                priority=7,
                deadline=660,   # 11:00 AM
            ),
            FlexibleTask(
                id="tb-002",
                title="Long task (90 min)",
                duration=90,
                priority=7,
                deadline=660,   # 11:00 AM — can't fit if short task is scheduled
            ),
            # Secondary pair: same priority + deadline + duration, different id
            FlexibleTask(
                id="tb-aaa",
                title="Short task A — lex-smaller id",
                duration=60,
                priority=7,
                deadline=660,
            ),
            FlexibleTask(
                id="tb-zzz",
                title="Short task B — lex-larger id",
                duration=60,
                priority=7,
                deadline=660,
            ),
        ],
    )


if __name__ == "__main__":
    import json

    print("--- get_dummy_schedule() ---")
    print(json.dumps(get_dummy_schedule().model_dump(), indent=2))

    print("\n--- get_overflow_schedule() ---")
    print(json.dumps(get_overflow_schedule().model_dump(), indent=2))

    print("\n--- get_dummy_week_schedule() ---")
    week = get_dummy_week_schedule()
    print(f"Week start : {week.week_start_date}")
    print(f"Days       : {len(week.days)}")
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for name, day in zip(day_names, week.days):
        n_fixed = len(day.fixed_events)
        n_tasks = len(day.flexible_tasks)
        print(f"  {name:10s}  {day.date}  "
              f"{n_fixed} fixed event{'s' if n_fixed != 1 else ''}  "
              f"{n_tasks} flexible task{'s' if n_tasks != 1 else ''}")
