import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { interval, Subscription } from 'rxjs';
import { switchMap, catchError } from 'rxjs/operators';
import { EMPTY } from 'rxjs';
import { ScheduleService } from '../services/schedule.service';
import {
  CalendarBlock,
  DaySchedule,
  DependencyArrow,
  FixedEvent,
  FlexibleTask,
  WeekSchedule,
} from '../models/schedule.models';
import { TaskEditorComponent, TaskSaveEvent } from '../task-editor/task-editor.component';

const GRID_START_MIN  = 360;
const GRID_END_MIN    = 1380;
const GRID_SPAN       = GRID_END_MIN - GRID_START_MIN;
const DAY_NAMES       = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** Manual disruption toast — stays visible while user reads it. */
const MANUAL_TOAST_MS = 6000;

/** Passive auto-update banner — shorter, unobtrusive. */
const PASSIVE_BANNER_MS = 5000;

/** Poll every 60 seconds. */
const POLL_INTERVAL_MS = 60_000;

interface DisruptionPanel {
  dayDate: string;
  eventId: string;
  fixedEvents: FixedEvent[];
  newEndTimeInput: string;
  submitting: boolean;
  error: string;
}

/** A passive notification shown when the poller auto-updates the schedule. */
interface PassiveBanner {
  lines: string[];
}

@Component({
  selector: 'app-weekly-calendar',
  standalone: true,
  imports: [CommonModule, FormsModule, TaskEditorComponent],
  templateUrl: './weekly-calendar.component.html',
  styleUrls: ['./weekly-calendar.component.css'],
})
export class WeeklyCalendarComponent implements OnInit, OnDestroy {
  week: WeekSchedule | null = null;
  loading = true;
  error = '';

  dayColumns: DayColumn[] = [];
  changedBlockIds = new Set<string>();

  // ── Manual disruption toast (explicit user action) ─────────────────────
  explanations: string[] = [];
  toastVisible = false;
  private toastTimer: ReturnType<typeof setTimeout> | null = null;

  // ── Passive auto-update banner (poller detected change) ────────────────
  banner: PassiveBanner | null = null;
  private bannerTimer: ReturnType<typeof setTimeout> | null = null;

  // ── Disruption panel ───────────────────────────────────────────────────
  panel: DisruptionPanel | null = null;

  // ── Task editor ────────────────────────────────────────────────────────
  taskEditorDay: string | null = null;
  taskEditorTask: FlexibleTask | null = null;

  // ── Polling ────────────────────────────────────────────────────────────
  private pollSub: Subscription | null = null;

  /** The day index we are currently polling (cycles through the week's days). */
  private pollDayIndex = 0;

  readonly hourLabels: { label: string; topPct: number }[] = this.buildHourLabels();

  constructor(private svc: ScheduleService) {}

  ngOnInit(): void {
    this.svc.getWeekDemo().subscribe({
      next: (w) => {
        this.week = w;
        this.dayColumns = w.days.map((day, i) => this.buildColumn(day, i));
        this.loading = false;
        this.startPolling();
      },
      error: (e) => {
        this.error = `Failed to load week: ${e.message}`;
        this.loading = false;
      },
    });
  }

  ngOnDestroy(): void {
    this.stopPolling();
    if (this.toastTimer)  clearTimeout(this.toastTimer);
    if (this.bannerTimer) clearTimeout(this.bannerTimer);
  }

  // ── Polling ────────────────────────────────────────────────────────────

  private startPolling(): void {
    this.pollSub = interval(POLL_INTERVAL_MS).pipe(
      switchMap(() => {
        if (!this.week) return EMPTY;

        // Rotate through days so each poll checks a different day.
        // The demo week uses fixture dates, so we use today's wall-clock time
        // as current_time but apply it to each day in turn.
        const day = this.week.days[this.pollDayIndex % this.week.days.length];
        this.pollDayIndex++;

        const now = new Date();
        const currentTime = now.getHours() * 60 + now.getMinutes();

        return this.svc.checkSchedule({ schedule: day, current_time: currentTime }).pipe(
          catchError(() => EMPTY)   // swallow network errors silently
        );
      }),
    ).subscribe((resp) => {
      if (!resp || !this.week) return;

      // Only act when the server detected and applied changes
      if (!resp.explanations.length) return;

      // Find which day this updated schedule belongs to
      const updatedDay = resp.schedule;
      const dayIndex = this.week.days.findIndex(d => d.date === updatedDay.date);
      if (dayIndex === -1) return;

      // Diff old vs new to find changed block ids
      const oldCol = this.dayColumns[dayIndex];
      const prevStarts = new Map<string, number>(
        oldCol?.blocks.map(b => [b.id, b.start_time]) ?? []
      );

      const newColumns = this.week.days.map((d, i) =>
        this.buildColumn(i === dayIndex ? updatedDay : d, i)
      );
      const newCol = newColumns[dayIndex];
      const shifted = (newCol?.blocks ?? []).filter(
        b => prevStarts.has(b.id) && prevStarts.get(b.id) !== b.start_time
      );

      // No visual change at all — don't notify
      if (shifted.length === 0 && resp.explanations.length === 0) return;

      // Apply update
      this.changedBlockIds = new Set(shifted.map(b => b.id));
      if (this.changedBlockIds.size > 0) {
        setTimeout(() => (this.changedBlockIds = new Set()), 2500);
      }

      const finalDays = this.week.days.map((d, i) => i === dayIndex ? updatedDay : d);
      this.week = { ...this.week, days: finalDays };
      this.dayColumns = newColumns;

      // Show passive banner (separate from manual toast)
      this.showBanner(resp.explanations);
    });
  }

  private stopPolling(): void {
    this.pollSub?.unsubscribe();
    this.pollSub = null;
  }

  // ── Passive banner ─────────────────────────────────────────────────────

  private showBanner(lines: string[]): void {
    this.banner = { lines };
    if (this.bannerTimer) clearTimeout(this.bannerTimer);
    this.bannerTimer = setTimeout(() => (this.banner = null), PASSIVE_BANNER_MS);
  }

  dismissBanner(): void {
    this.banner = null;
    if (this.bannerTimer) clearTimeout(this.bannerTimer);
  }

  // ── Manual toast ───────────────────────────────────────────────────────

  private showToast(lines: string[]): void {
    if (!lines.length) return;
    this.explanations = lines;
    this.toastVisible = true;
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => (this.toastVisible = false), MANUAL_TOAST_MS);
  }

  dismissToast(): void {
    this.toastVisible = false;
    if (this.toastTimer) clearTimeout(this.toastTimer);
  }

  // ── Task editor ────────────────────────────────────────────────────────

  openTaskEditor(dayDate: string, existingTask: FlexibleTask | null = null): void {
    this.taskEditorDay  = dayDate;
    this.taskEditorTask = existingTask;
    this.panel = null;
  }

  closeTaskEditor(): void {
    this.taskEditorDay  = null;
    this.taskEditorTask = null;
  }

  editorDayTasks(): FlexibleTask[] {
    if (!this.taskEditorDay || !this.week) return [];
    const day = this.week.days.find(d => d.date === this.taskEditorDay);
    return day?.flexible_tasks ?? [];
  }

  onTaskSave(event: TaskSaveEvent): void {
    if (!this.week) return;
    const dayIndex = this.week.days.findIndex(d => d.date === event.dayDate);
    if (dayIndex === -1) return;

    const day = this.week.days[dayIndex];
    const newTask: FlexibleTask = {
      ...event.task,
      status:            'backlog',
      start_time:        null,
      is_deadline_today: false,
      actual_duration:   null,
    };

    const existing = day.flexible_tasks.findIndex(t => t.id === newTask.id);
    const updatedTasks = existing >= 0
      ? day.flexible_tasks.map((t, i) => i === existing ? newTask : t)
      : [...day.flexible_tasks, newTask];

    const updatedDay = { ...day, flexible_tasks: updatedTasks };
    const updatedDays = this.week.days.map((d, i) => i === dayIndex ? updatedDay : d);
    this.week = { ...this.week, days: updatedDays };
    this.dayColumns = this.week.days.map((d, i) => this.buildColumn(d, i));
    this.closeTaskEditor();

    this.svc.solveDay(updatedDay).subscribe({
      next: (solved) => {
        const finalDays = this.week!.days.map((d, i) => i === dayIndex ? solved : d);
        this.week = { ...this.week!, days: finalDays };
        this.dayColumns = this.week.days.map((d, i) => this.buildColumn(d, i));
      },
      error: (e) => console.error('Solve failed:', e.error?.detail ?? e.message),
    });
  }

  // ── Disruption panel ───────────────────────────────────────────────────

  openDisruptPanel(event: MouseEvent, col: DayColumn, block: CalendarBlock): void {
    event.stopPropagation();
    if (block.kind !== 'fixed') return;
    const dayData = this.week!.days.find(d => d.date === col.date)!;
    this.panel = {
      dayDate:         col.date,
      eventId:         block.id,
      fixedEvents:     dayData.fixed_events,
      newEndTimeInput: '',
      submitting:      false,
      error:           '',
    };
    this.closeTaskEditor();
  }

  closePanel(): void { this.panel = null; }

  submitDisruption(): void {
    if (!this.panel || !this.panel.newEndTimeInput) return;
    const newEndMin = this.timeToMinutes(this.panel.newEndTimeInput);
    this.panel.submitting = true;
    this.panel.error = '';

    this.svc.disruptWeek({
      day_date:     this.panel.dayDate,
      type:         'event_overrun',
      event_id:     this.panel.eventId,
      new_end_time: newEndMin,
    }).subscribe({
      next: (resp) => {
        this.applyUpdatedWeek(resp.schedule, this.panel!.dayDate);
        this.showToast(resp.explanations);
        this.panel = null;
      },
      error: (e) => {
        const detail = e.error?.detail ?? e.message;
        if (this.panel) {
          this.panel.error = `Failed: ${detail}`;
          this.panel.submitting = false;
        }
      },
    });
  }

  // ── Week update (manual disruption) ───────────────────────────────────

  private applyUpdatedWeek(newWeek: WeekSchedule, disruptedDate: string): void {
    const oldCol = this.dayColumns.find(c => c.date === disruptedDate);
    const prevStarts = new Map<string, number>(
      oldCol?.blocks.map(b => [b.id, b.start_time]) ?? []
    );
    const newColumns = newWeek.days.map((day, i) => this.buildColumn(day, i));
    const newDisruptedCol = newColumns.find(c => c.date === disruptedDate);
    this.changedBlockIds = new Set(
      (newDisruptedCol?.blocks ?? [])
        .filter(b => prevStarts.has(b.id) && prevStarts.get(b.id) !== b.start_time)
        .map(b => b.id)
    );
    if (this.changedBlockIds.size > 0) {
      setTimeout(() => (this.changedBlockIds = new Set()), 2500);
    }
    this.week = newWeek;
    this.dayColumns = newColumns;
  }

  // ── Column builder ─────────────────────────────────────────────────────

  private buildColumn(day: DaySchedule, index: number): DayColumn {
    const blocks: CalendarBlock[] = [];
    const backlog: FlexibleTask[] = [];

    for (const evt of day.fixed_events) {
      blocks.push({
        id: evt.id, title: evt.title,
        start_time: evt.start_time, end_time: evt.end_time,
        kind: 'fixed',
        ...this.toPosition(evt.start_time, evt.end_time),
      });
    }

    for (const task of day.flexible_tasks) {
      if (task.status === 'scheduled' && task.start_time !== null) {
        const dur = task.actual_duration ?? task.duration;
        const end = task.start_time + dur;
        blocks.push({
          id: task.id, title: task.title,
          start_time: task.start_time, end_time: end,
          kind: 'task', priority: task.priority,
          depends_on: task.depends_on,
          ...this.toPosition(task.start_time, end),
        });
      } else {
        backlog.push(task);
      }
    }

    blocks.sort((a, b) => a.start_time - b.start_time);

    const blockMap = new Map(blocks.map(b => [b.id, b]));
    const arrows: DependencyArrow[] = [];
    for (const block of blocks) {
      if (block.kind !== 'task' || !block.depends_on) continue;
      const fromBlock = blockMap.get(block.depends_on);
      if (!fromBlock) continue;
      arrows.push({
        fromId:      fromBlock.id,
        toId:        block.id,
        fromMidPct:  fromBlock.topPct + fromBlock.heightPct,
        toTopPct:    block.topPct,
      });
    }

    return { date: day.date, dayName: DAY_NAMES[index], blocks, backlog, arrows };
  }

  private toPosition(startMin: number, endMin: number) {
    const cs = Math.max(startMin, GRID_START_MIN);
    const ce = Math.min(endMin, GRID_END_MIN);
    return {
      topPct:    ((cs - GRID_START_MIN) / GRID_SPAN) * 100,
      heightPct: Math.max(((ce - cs) / GRID_SPAN) * 100, 1.5),
    };
  }

  private buildHourLabels() {
    const labels = [];
    for (let m = GRID_START_MIN; m <= GRID_END_MIN; m += 60) {
      const h = Math.floor(m / 60);
      const label = h === 0 ? '12am' : h < 12 ? `${h}am` : h === 12 ? '12pm' : `${h - 12}pm`;
      labels.push({ label, topPct: ((m - GRID_START_MIN) / GRID_SPAN) * 100 });
    }
    return labels;
  }

  // ── Template helpers ───────────────────────────────────────────────────

  fmt(minutes: number): string {
    return `${Math.floor(minutes / 60).toString().padStart(2, '0')}:${(minutes % 60).toString().padStart(2, '0')}`;
  }

  shortDate(iso: string): string {
    return new Date(iso + 'T00:00:00')
      .toLocaleDateString('en-GB', { month: 'short', day: 'numeric' });
  }

  timeToMinutes(t: string): number {
    const [h, m] = t.split(':').map(Number);
    return h * 60 + m;
  }

  closeAll(): void {
    this.panel = null;
    this.closeTaskEditor();
  }

  allBacklog(): BacklogEntry[] {
    const result: BacklogEntry[] = [];
    for (const col of this.dayColumns) {
      for (const t of col.backlog) {
        result.push({ day: col.dayName, task: t, missed: t.is_deadline_today === true });
      }
    }
    result.sort((a, b) => {
      if (a.missed !== b.missed) return a.missed ? -1 : 1;
      return b.task.priority - a.task.priority;
    });
    return result;
  }

  missedCount(): number {
    return this.allBacklog().filter(e => e.missed).length;
  }

  dependsOnTitle(task: FlexibleTask): string | null {
    if (!task.depends_on || !this.week) return null;
    for (const day of this.week.days) {
      const dep = day.flexible_tasks.find(t => t.id === task.depends_on);
      if (dep) return dep.title;
    }
    return task.depends_on;
  }
}

interface DayColumn {
  date: string;
  dayName: string;
  blocks: CalendarBlock[];
  backlog: FlexibleTask[];
  arrows: DependencyArrow[];
}

interface BacklogEntry {
  day: string;
  task: FlexibleTask;
  missed: boolean;
}
