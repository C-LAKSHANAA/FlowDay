# FlowDay — Automatic Schedule Reflow

## Feature

Automatic Schedule Reflow — when a fixed event runs long or shifts, FlowDay automatically
re-arranges the rest of the day's flexible tasks (respecting priorities, deadlines, and
remaining time) without the user manually replanning anything.

> For this 3-week scope, disruptions are manually reported by the user.

---

## Week 1 — Foundation

- **Reflow Backlog:** define disruption types and task fields (duration, priority, deadline),
  represent fixed events and flexible tasks with the attributes the solver needs.
- **Sprint Planning:** design the constraint model and data schema, visualize how the schedule
  should look (calendar format / to-do list) and select the most user-friendly format.
  Currently choosing the calendar layout (grids) for better accessibility.
  *(Can be altered based on review feedback.)*
- **Sprint:** implement the data model and an OR-Tools solver skeleton against dummy data.
  Check that the schedule is formed properly — fixed tasks stay at their start time,
  flexible tasks are allotted time based on availability.
- **Sprint Review/Demo:** demo the process of generating a static schedule from dummy input
  *(end of week — Sunday)*.
- **Sprint Retrospective:** review what went well, identify areas for improvement, and
  update/prioritize the backlog for the next sprint.

---

## Week 2 — Core Reflow Logic

- **Reflow Backlog:** define disruption trigger scenarios (late meeting, task overrun),
  decide when the trigger should be called, incorporate feedback from the previous sprint
  review, and carry over any unfinished tasks.
- **Sprint Planning:** map constraints — locked fixed events, deadline preservation, priority
  ordering. Flexible tasks are re-slotted respecting priority and deadline constraints.
  - Priority is used as an optimization criterion.
  - Deadlines act as hard constraints where applicable.
  - If all tasks cannot fit, higher-priority tasks are scheduled first; lower-priority /
    infeasible tasks are deferred to the backlog.
- **Sprint:** implement the reflow trigger, solver invocation, and a manual
  "mark disruption" action.
- **Sprint Review/Demo:** trigger a disruption and show the end-to-end reflowed schedule
  *(end of week — Sunday)*.
- **Sprint Retrospective:** review the reflow implementation, identify issues and edge cases,
  and prioritize improvements for the final sprint.

---

## Week 3 — Validation & Polish

- **Reflow Backlog:** catalogue edge cases — infeasible tasks *(a task is infeasible when
  its required duration cannot be accommodated within the remaining available time while
  satisfying its deadline and other locked constraints)*, cascading disruptions, feedback
  from the previous sprint, and unfinished items.
- **Sprint Planning:** design the correctness test suite and plan UI polish.
- **Sprint:** implement the test suite, integrate reflow into the UI, add basic
  explainability text.
- **Sprint Review/Demo:** full end-to-end demo — scripted day, manually reported disruption,
  auto-reflow, and passing correctness tests.
  An interim review will be conducted on Thursday, allowing applicable feedback to be
  incorporated before the final Sunday review.
- **Sprint Retrospective:** final review, note stretch goals (auto-detection, ML duration
  prediction) *(after mid-week review)*.

> If the sprint review provides further feedback or any task remains incomplete, the team
> should document the feedback, prioritize the remaining work, and clearly communicate what
> can be completed within the remaining time. Any unfinished items should be documented as
> pending work or future enhancements.

---

## Outcome at End of 3 Weeks

A working demonstration of automatic schedule reflow:
- Fixed events remain locked.
- Flexible tasks are re-slotted respecting priority and deadline constraints.
- Infeasible tasks are deferred to the backlog.
- The reflow is validated by a passing correctness test suite.

For the 3-week implementation, disruptions are manually reported by the user.
Automatic detection of overruns is considered a future enhancement.

---

## Edge Cases / Scenarios to Validate

Edge cases to be addressed by end of Week 3 before the review:

1. What if a task must be completed today (by 11:59 pm) but another task has exceeded its
   duration and no available slots remain — how is the task accommodated?
2. What if two tasks have the same deadline and are equally important?
3. A task is already in progress when a disruption hits.
4. Dependent tasks (task B cannot start until task A finishes).
5. Two fixed events overlap.
6. The plannable day itself shrinks mid-day.
