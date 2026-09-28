import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
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

const GRID_START_MIN  = 0;     // 12:00 AM (00:00)
const GRID_END_MIN    = 1440;  // 12:00 AM next day (24:00)
const GRID_SPAN       = GRID_END_MIN - GRID_START_MIN;
const DAY_NAMES       = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** Storage Key for Persistence */
const LOCAL_STORAGE_KEY = 'flowday_week_schedule_v2';
const MANUAL_TOAST_MS = 5000;

interface DisruptionPanel {
  dayDate: string;
  eventId: string;
  fixedEvents: FixedEvent[];
  newEndTimeInput: string;
  submitting: boolean;
  error: string;
}

interface BacklogEntry {
  dayDate: string;
  dayName: string;
  task: FlexibleTask;
  missed: boolean;
  priorityLabel: string;
}

export interface MiniCalendarDay {
  date: Date;
  dateStr: string;
  dayNum: number;
  isCurrentMonth: boolean;
  isToday: boolean;
  isSelected: boolean;
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

  // ── Mini Month Calendar (Sidebar) ───────────────────────────────────────
  activeMiniMonth = new Date();
  miniMonthTitle = '';
  miniCalendarDays: MiniCalendarDay[] = [];
  selectedDateStr = '';
  todayDateStr = '';

  // ── System Clock Sync & Time Line ──────────────────────────────────────
  currentTimeTopPct = 0;
  currentTimeString = '';
  currentMin = 0;
  private clockInterval: any = null;

  // ── Manual disruption toast ─────────────────────────────────────────────
  explanations: string[] = [];
  toastVisible = false;
  private toastTimer: ReturnType<typeof setTimeout> | null = null;

  // ── Disruption panel ───────────────────────────────────────────────────
  panel: DisruptionPanel | null = null;

  // ── Task editor ────────────────────────────────────────────────────────
  taskEditorDay: string | null = null;
  taskEditorTask: FlexibleTask | null = null;

  readonly hourLabels: { label: string; topPct: number }[] = this.buildHourLabels();

  constructor(private svc: ScheduleService) {}

  ngOnInit(): void {
    const now = new Date();
    this.todayDateStr = this.formatIsoDate(now);
    this.selectedDateStr = this.todayDateStr;

    this.buildMiniCalendar();
    this.updateClock();
    this.clockInterval = setInterval(() => this.updateClock(), 30000);

    this.loadWeek();
  }

  ngOnDestroy(): void {
    if (this.toastTimer) clearTimeout(this.toastTimer);
    if (this.clockInterval) clearInterval(this.clockInterval);
  }

  // ── Persistence (Master Storage per Date) ─────────────────────────────────────────

  private loadMasterStorage(): Record<string, DaySchedule> {
    try {
      const data = localStorage.getItem(LOCAL_STORAGE_KEY);
      if (data) return JSON.parse(data) as Record<string, DaySchedule>;
    } catch (e) {
      console.warn('Failed to parse master schedule store from localStorage:', e);
    }
    return {};
  }

  private saveMasterStorage(): void {
    if (!this.week) return;
    try {
      const store = this.loadMasterStorage();
      for (const day of this.week.days) {
        store[day.date] = day;
      }
      localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(store));
    } catch (e) {
      console.warn('Failed to save master schedule store to localStorage:', e);
    }
  }

  // ── System Clock Sync ──────────────────────────────────────────────────

  private updateClock(): void {
    const now = new Date();
    this.currentTimeString = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    this.currentMin = now.getHours() * 60 + now.getMinutes();
    this.currentTimeTopPct = (this.currentMin / 1440) * 100;
  }

  // ── Mini Month Calendar Logic ──────────────────────────────────────────

  getMondayDate(d: Date): Date {
    const target = new Date(d);
    const dayOfWeek = target.getDay();
    const diffToMon = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;
    const monday = new Date(target);
    monday.setDate(target.getDate() + diffToMon);
    return monday;
  }

  buildMiniCalendar(): void {
    const year = this.activeMiniMonth.getFullYear();
    const month = this.activeMiniMonth.getMonth();

    this.miniMonthTitle = this.activeMiniMonth.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });

    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);

    const startingDayOfWeek = firstDay.getDay(); // 0 = Sun, 1 = Mon...
    const daysInMonth = lastDay.getDate();

    const activeWeekStartDates = new Set<string>();
    if (this.week) {
      for (const d of this.week.days) activeWeekStartDates.add(d.date);
    }

    const days: MiniCalendarDay[] = [];

    // Trailing days from previous month
    const prevMonthLastDay = new Date(year, month, 0).getDate();
    for (let i = startingDayOfWeek - 1; i >= 0; i--) {
      const d = new Date(year, month - 1, prevMonthLastDay - i);
      const dateStr = this.formatIsoDate(d);
      days.push({
        date: d,
        dateStr,
        dayNum: d.getDate(),
        isCurrentMonth: false,
        isToday: dateStr === this.todayDateStr,
        isSelected: activeWeekStartDates.has(dateStr) || dateStr === this.selectedDateStr,
      });
    }

    // Days in current month
    for (let i = 1; i <= daysInMonth; i++) {
      const d = new Date(year, month, i);
      const dateStr = this.formatIsoDate(d);
      days.push({
        date: d,
        dateStr,
        dayNum: i,
        isCurrentMonth: true,
        isToday: dateStr === this.todayDateStr,
        isSelected: activeWeekStartDates.has(dateStr) || dateStr === this.selectedDateStr,
      });
    }

    // Leading days from next month
    const targetSize = days.length > 35 ? 42 : 35;
    const remaining = targetSize - days.length;
    for (let i = 1; i <= remaining; i++) {
      const d = new Date(year, month + 1, i);
      const dateStr = this.formatIsoDate(d);
      days.push({
        date: d,
        dateStr,
        dayNum: i,
        isCurrentMonth: false,
        isToday: dateStr === this.todayDateStr,
        isSelected: activeWeekStartDates.has(dateStr) || dateStr === this.selectedDateStr,
      });
    }

    this.miniCalendarDays = days;
  }

  prevMiniMonth(): void {
    this.activeMiniMonth = new Date(this.activeMiniMonth.getFullYear(), this.activeMiniMonth.getMonth() - 1, 1);
    this.buildMiniCalendar();
  }

  nextMiniMonth(): void {
    this.activeMiniMonth = new Date(this.activeMiniMonth.getFullYear(), this.activeMiniMonth.getMonth() + 1, 1);
    this.buildMiniCalendar();
  }

  selectMiniDate(day: MiniCalendarDay): void {
    this.selectedDateStr = day.dateStr;
    this.loadWeekForDate(day.date);
  }

  goToToday(): void {
    const now = new Date();
    this.activeMiniMonth = new Date(now.getFullYear(), now.getMonth(), 1);
    this.selectedDateStr = this.todayDateStr;
    this.loadWeekForDate(now);
  }

  // ── Schedule Operations ────────────────────────────────────────────────

  loadWeek(): void {
    this.loadWeekForDate(new Date());
  }

  loadWeekForDate(targetDate: Date): void {
    this.loading = true;
    const monday = this.getMondayDate(targetDate);
    const mondayStr = this.formatIsoDate(monday);

    const weekDates: string[] = [];
    for (let i = 0; i < 7; i++) {
      const d = new Date(monday);
      d.setDate(monday.getDate() + i);
      weekDates.push(this.formatIsoDate(d));
    }

    const masterStore = this.loadMasterStorage();

    const days: DaySchedule[] = weekDates.map(dateStr => {
      if (masterStore[dateStr]) {
        return masterStore[dateStr];
      }
      return {
        date: dateStr,
        day_start: 0,
        day_end: 1440,
        fixed_events: [],
        flexible_tasks: [],
      };
    });

    this.week = {
      week_start_date: mondayStr,
      days,
    };

    this.saveMasterStorage();
    this.buildMiniCalendar();
    this.dayColumns = this.week.days.map((d, i) => this.buildColumn(d, i));
    this.loading = false;
  }

  resetWeek(): void {
    localStorage.removeItem(LOCAL_STORAGE_KEY);
    this.svc.getWeekDemo().subscribe({
      next: (w) => {
        this.week = w;
        this.saveMasterStorage();
        this.dayColumns = w.days.map((day, i) => this.buildColumn(day, i));
        this.showToast(['Schedule reset to clean empty state.']);
      },
    });
  }

  clearSchedule(): void {
    if (!this.week) return;
    const clearedDays = this.week.days.map(d => ({
      ...d,
      fixed_events: [],
      flexible_tasks: [],
    }));
    this.week = { ...this.week, days: clearedDays };
    this.saveMasterStorage();
    this.dayColumns = this.week.days.map((d, i) => this.buildColumn(d, i));
    this.showToast(['Schedule cleared of all tasks and events!']);
  }

  // ── Toast ───────────────────────────────────────────────────────────────

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

  // ── Task Editor ────────────────────────────────────────────────────────

  openTaskEditor(dayDate: string, existingTask: FlexibleTask | null = null): void {
    this.taskEditorDay  = dayDate;
    this.taskEditorTask = existingTask;
    this.panel = null;
  }

  openGlobalTaskEditor(): void {
    if (!this.week || this.week.days.length === 0) return;
    this.openTaskEditor(this.week.days[0].date, null);
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

    // Fixed task -> added to fixed_events so solver NEVER shifts it!
    if (event.task.is_fixed && event.task.start_time !== null) {
      const fixedEvent: FixedEvent = {
        id: event.task.id,
        title: event.task.title,
        start_time: event.task.start_time,
        end_time: event.task.start_time + event.task.duration,
      };

      const updatedFixed = [...day.fixed_events.filter(e => e.id !== fixedEvent.id), fixedEvent];
      const updatedFlexible = day.flexible_tasks.filter(t => t.id !== event.task.id);
      const updatedDay = { ...day, fixed_events: updatedFixed, flexible_tasks: updatedFlexible };

      this.svc.solveDay(updatedDay).subscribe({
        next: (solved) => {
          const finalDays = this.week!.days.map((d, i) => i === dayIndex ? solved : d);
          this.week = { ...this.week!, days: finalDays };
          this.saveMasterStorage();
          this.dayColumns = this.week.days.map((d, i) => this.buildColumn(d, i));
          this.closeTaskEditor();
        },
        error: () => {
          const finalDays = this.week!.days.map((d, i) => i === dayIndex ? updatedDay : d);
          this.week = { ...this.week!, days: finalDays };
          this.saveMasterStorage();
          this.dayColumns = this.week.days.map((d, i) => this.buildColumn(d, i));
          this.closeTaskEditor();
        },
      });
      return;
    }

    // Flexible Task path
    let taskPriority = event.task.priority;
    // Dynamic Priority Escalation: If task deadline is nearing (within 2 hours), escalate priority to High (9)!
    if (event.task.deadline !== null && (event.task.deadline - this.currentMin) <= 120 && (event.task.deadline - this.currentMin) >= 0) {
      taskPriority = 9; // Escalate to High
    }

    const newTask: FlexibleTask = {
      ...event.task,
      priority: taskPriority,
      is_deadline_today: false,
      actual_duration:   null,
    };

    const existingIndex = day.flexible_tasks.findIndex(t => t.id === newTask.id);
    const updatedTasks = existingIndex >= 0
      ? day.flexible_tasks.map((t, i) => i === existingIndex ? newTask : t)
      : [...day.flexible_tasks, newTask];

    const updatedDay = { ...day, flexible_tasks: updatedTasks };

    this.svc.solveDay(updatedDay).subscribe({
      next: (solved) => {
        const finalDays = this.week!.days.map((d, i) => i === dayIndex ? solved : d);
        this.week = { ...this.week!, days: finalDays };
        this.saveMasterStorage();
        this.dayColumns = this.week.days.map((d, i) => this.buildColumn(d, i));
        this.closeTaskEditor();
      },
      error: (e) => {
        console.error('Solve failed:', e.error?.detail ?? e.message);
        const finalDays = this.week!.days.map((d, i) => i === dayIndex ? updatedDay : d);
        this.week = { ...this.week!, days: finalDays };
        this.saveMasterStorage();
        this.dayColumns = this.week.days.map((d, i) => this.buildColumn(d, i));
        this.closeTaskEditor();
      },
    });
  }

  deleteBlock(dayDate: string, blockId: string): void {
    if (!this.week) return;
    const dayIndex = this.week.days.findIndex(d => d.date === dayDate);
    if (dayIndex === -1) return;

    const day = this.week.days[dayIndex];
    const updatedFixed = day.fixed_events.filter(e => e.id !== blockId);
    const updatedTasks = day.flexible_tasks.filter(t => t.id !== blockId);
    const updatedDay = { ...day, fixed_events: updatedFixed, flexible_tasks: updatedTasks };

    this.svc.solveDay(updatedDay).subscribe({
      next: (solved) => {
        const finalDays = this.week!.days.map((d, i) => i === dayIndex ? solved : d);
        this.week = { ...this.week!, days: finalDays };
        this.saveMasterStorage();
        this.dayColumns = this.week.days.map((d, i) => this.buildColumn(d, i));
      },
      error: () => {
        const finalDays = this.week!.days.map((d, i) => i === dayIndex ? updatedDay : d);
        this.week = { ...this.week!, days: finalDays };
        this.saveMasterStorage();
        this.dayColumns = this.week.days.map((d, i) => this.buildColumn(d, i));
      },
    });
  }

  // ── Disruption Panel ───────────────────────────────────────────────────

  openDisruptPanel(event: MouseEvent, col: DayColumn, block: CalendarBlock): void {
    event.stopPropagation();
    if (block.kind !== 'fixed') return;
    const dayData = this.week!.days.find(d => d.date === col.date)!;
    this.panel = {
      dayDate:         col.date,
      eventId:         block.id,
      fixedEvents:     dayData.fixed_events,
      newEndTimeInput: this.fmt(block.end_time + 30),
      submitting:      false,
      error:           '',
    };
    this.closeTaskEditor();
  }

  openGlobalDisruptModal(): void {
    if (!this.week || this.week.days.length === 0) return;
    const dayWithEvent = this.week.days.find(d => d.fixed_events.length > 0) || this.week.days[0];
    const evt = dayWithEvent.fixed_events[0];
    this.panel = {
      dayDate:         dayWithEvent.date,
      eventId:         evt ? evt.id : '',
      fixedEvents:     dayWithEvent.fixed_events,
      newEndTimeInput: evt ? this.fmt(evt.end_time + 30) : '10:00',
      submitting:      false,
      error:           '',
    };
    this.closeTaskEditor();
  }

  onPanelDayChange(dateStr: string): void {
    if (!this.week || !this.panel) return;
    const day = this.week.days.find(d => d.date === dateStr);
    if (day) {
      this.panel.dayDate = dateStr;
      this.panel.fixedEvents = day.fixed_events;
      if (day.fixed_events.length > 0) {
        this.panel.eventId = day.fixed_events[0].id;
        this.panel.newEndTimeInput = this.fmt(day.fixed_events[0].end_time + 30);
      } else {
        this.panel.eventId = '';
      }
    }
  }

  closePanel(): void { this.panel = null; }

  submitDisruption(): void {
    if (!this.panel || !this.panel.newEndTimeInput || !this.panel.eventId) return;
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
      setTimeout(() => (this.changedBlockIds = new Set()), 3000);
    }
    this.week = newWeek;
    this.saveMasterStorage();
    this.dayColumns = newColumns;
  }

  // ── Column builder & Overlap algorithm ─────────────────────────────────

  private buildColumn(day: DaySchedule, index: number): DayColumn {
    const blocks: CalendarBlock[] = [];
    const backlog: FlexibleTask[] = [];

    for (const evt of day.fixed_events) {
      blocks.push({
        id: evt.id, title: evt.title,
        start_time: evt.start_time, end_time: evt.end_time,
        kind: 'fixed',
        is_fixed: true,
        ...this.toPosition(evt.start_time, evt.end_time),
      });
    }

    for (const task of day.flexible_tasks) {
      if (task.status === 'scheduled' && task.start_time !== null) {
        const dur = task.actual_duration ?? task.duration;
        const end = task.start_time + dur;
        // Overdue check: if task end_time > deadline OR if deadline passed relative to system clock
        const deadlineAtRisk = task.deadline != null && (end > task.deadline || (day.date === this.todayDateStr && this.currentMin > task.deadline));
        blocks.push({
          id: task.id, title: task.title,
          start_time: task.start_time, end_time: end,
          kind: 'task', priority: task.priority,
          is_fixed: task.is_fixed,
          depends_on: task.depends_on,
          deadline: task.deadline,
          deadlineAtRisk,
          ...this.toPosition(task.start_time, end),
        });
      } else {
        backlog.push(task);
      }
    }

    blocks.sort((a, b) => a.start_time - b.start_time);
    this.computeOverlapPositions(blocks);

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

    const isToday = day.date === this.todayDateStr;

    return { date: day.date, dayName: DAY_NAMES[index], blocks, backlog, arrows, isToday };
  }

  private computeOverlapPositions(blocks: CalendarBlock[]): void {
    if (blocks.length === 0) return;

    const clusters: CalendarBlock[][] = [];
    let currentCluster: CalendarBlock[] = [blocks[0]];
    let currentMaxEnd = blocks[0].end_time;

    for (let i = 1; i < blocks.length; i++) {
      const b = blocks[i];
      if (b.start_time < currentMaxEnd) {
        currentCluster.push(b);
        currentMaxEnd = Math.max(currentMaxEnd, b.end_time);
      } else {
        clusters.push(currentCluster);
        currentCluster = [b];
        currentMaxEnd = b.end_time;
      }
    }
    clusters.push(currentCluster);

    for (const cluster of clusters) {
      if (cluster.length === 1) {
        cluster[0].leftPct = 0;
        cluster[0].widthPct = 100;
        continue;
      }

      const colEndTimes: number[] = [];
      const assignedCols: { block: CalendarBlock; col: number }[] = [];

      for (const b of cluster) {
        let placed = false;
        for (let c = 0; c < colEndTimes.length; c++) {
          if (colEndTimes[c] <= b.start_time) {
            colEndTimes[c] = b.end_time;
            assignedCols.push({ block: b, col: c });
            placed = true;
            break;
          }
        }
        if (!placed) {
          colEndTimes.push(b.end_time);
          assignedCols.push({ block: b, col: colEndTimes.length - 1 });
        }
      }

      const totalCols = colEndTimes.length;
      for (const item of assignedCols) {
        const width = Math.max(Math.floor(96 / totalCols), 25);
        const left = item.col * (100 / totalCols);
        item.block.leftPct = left;
        item.block.widthPct = width;
      }
    }
  }

  private toPosition(startMin: number, endMin: number) {
    const cs = Math.max(startMin, GRID_START_MIN);
    const ce = Math.min(endMin, GRID_END_MIN);
    return {
      topPct:    ((cs - GRID_START_MIN) / GRID_SPAN) * 100,
      heightPct: Math.max(((ce - cs) / GRID_SPAN) * 100, 2.5),
    };
  }

  private buildHourLabels() {
    const labels = [];
    for (let m = GRID_START_MIN; m <= GRID_END_MIN; m += 60) {
      const h = Math.floor(m / 60);
      const label = h === 0 ? '12 AM' : h < 12 ? `${h} AM` : h === 12 ? '12 PM' : `${h - 12} PM`;
      labels.push({ label, topPct: ((m - GRID_START_MIN) / GRID_SPAN) * 100 });
    }
    return labels;
  }

  // ── Metrics & Backlog ───────────────────────────────────────────────────

  allBacklog(): BacklogEntry[] {
    const result: BacklogEntry[] = [];
    for (const col of this.dayColumns) {
      for (const t of col.backlog) {
        result.push({
          dayDate: col.date,
          dayName: col.dayName,
          task: t,
          missed: t.is_deadline_today === true,
          priorityLabel: this.getPriorityLabel(t.priority),
        });
      }
    }
    // Sort backlog with HIGH priority first (priority >= 8), then Med (4-7), then Low (<4)
    result.sort((a, b) => {
      if (a.missed !== b.missed) return a.missed ? -1 : 1;
      return b.task.priority - a.task.priority;
    });
    return result;
  }

  getPriorityLabel(priority?: number): string {
    if (!priority) return 'Medium';
    if (priority >= 8) return 'High';
    if (priority >= 4) return 'Med';
    return 'Low';
  }

  get totalScheduledCount(): number {
    if (!this.week) return 0;
    return this.week.days.reduce((acc, d) =>
      acc + d.flexible_tasks.filter(t => t.status === 'scheduled').length, 0);
  }

  get totalFixedCount(): number {
    if (!this.week) return 0;
    return this.week.days.reduce((acc, d) => acc + d.fixed_events.length, 0);
  }

  missedCount(): number {
    return this.allBacklog().filter(e => e.missed).length;
  }

  // ── Template Helpers ───────────────────────────────────────────────────

  fmt(minutes: number): string {
    return `${Math.floor(minutes / 60).toString().padStart(2, '0')}:${(minutes % 60).toString().padStart(2, '0')}`;
  }

  shortDate(iso: string): string {
    return new Date(iso + 'T00:00:00')
      .toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  timeToMinutes(t: string): number {
    const [h, m] = t.split(':').map(Number);
    return h * 60 + m;
  }

  closeAll(): void {
    this.panel = null;
    this.closeTaskEditor();
  }

  dependsOnTitle(task: FlexibleTask): string | null {
    if (!task.depends_on || !this.week) return null;
    for (const day of this.week.days) {
      const dep = day.flexible_tasks.find(t => t.id === task.depends_on);
      if (dep) return dep.title;
    }
    return task.depends_on;
  }

  private formatIsoDate(d: Date): string {
    const y = d.getFullYear();
    const m = (d.getMonth() + 1).toString().padStart(2, '0');
    const day = d.getDate().toString().padStart(2, '0');
    return `${y}-${m}-${day}`;
  }
}

interface DayColumn {
  date: string;
  dayName: string;
  blocks: CalendarBlock[];
  backlog: FlexibleTask[];
  arrows: DependencyArrow[];
  isToday: boolean;
}
