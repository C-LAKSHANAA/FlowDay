import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ScheduleService } from '../services/schedule.service';
import {
  DaySchedule,
  FixedEvent,
  ScheduleRow,
} from '../models/schedule.models';

@Component({
  selector: 'app-schedule-view',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './schedule-view.component.html',
  styleUrls: ['./schedule-view.component.css'],
})
export class ScheduleViewComponent implements OnInit {
  schedule: DaySchedule | null = null;
  rows: ScheduleRow[] = [];
  loading = false;
  error = '';

  // IDs of rows whose start_time changed in the last disruption (for highlight)
  changedIds = new Set<string>();

  // Disruption form state
  selectedEventId = '';
  newEndTimeInput = '';   // HH:MM string from <input type="time">
  disrupting = false;
  disruptError = '';

  constructor(private svc: ScheduleService) {}

  ngOnInit(): void {
    this.loadDemo();
  }

  loadDemo(): void {
    this.loading = true;
    this.error = '';
    this.svc.getDemo().subscribe({
      next: (s) => {
        this.applySchedule(s, null);
        this.loading = false;
      },
      error: (e) => {
        this.error = `Failed to load schedule: ${e.message}`;
        this.loading = false;
      },
    });
  }

  // -------------------------------------------------------------------------
  // Disruption form
  // -------------------------------------------------------------------------

  get fixedEvents(): FixedEvent[] {
    return this.schedule?.fixed_events ?? [];
  }

  submitDisruption(): void {
    if (!this.selectedEventId || !this.newEndTimeInput) return;

    const newEndMinutes = this.timeToMinutes(this.newEndTimeInput);
    this.disrupting = true;
    this.disruptError = '';

    this.svc
      .disrupt({
        type: 'event_overrun',
        event_id: this.selectedEventId,
        new_end_time: newEndMinutes,
      })
      .subscribe({
        next: (resp) => {
          this.applySchedule(resp.schedule, this.rows);
          this.disrupting = false;
        },
        error: (e) => {
          const detail = e.error?.detail ?? e.message;
          this.disruptError = `Disruption failed: ${detail}`;
          this.disrupting = false;
        },
      });
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  /** Build sorted rows from a new schedule, diff against previous to find shifts. */
  private applySchedule(schedule: DaySchedule, previousRows: ScheduleRow[] | null): void {
    const prevMap = new Map(previousRows?.map((r) => [r.id, r.start_time]) ?? []);

    const newRows: ScheduleRow[] = [
      ...schedule.fixed_events.map((e) => ({
        id: e.id,
        title: e.title,
        start_time: e.start_time,
        end_time: e.end_time,
        kind: 'fixed' as const,
      })),
      ...schedule.flexible_tasks
        .filter((t) => t.status === 'scheduled' && t.start_time !== null)
        .map((t) => ({
          id: t.id,
          title: t.title,
          start_time: t.start_time!,
          end_time: t.start_time! + t.duration,
          kind: 'task' as const,
          priority: t.priority,
        })),
    ].sort((a, b) => a.start_time - b.start_time);

    // Detect which rows shifted
    this.changedIds = new Set(
      newRows
        .filter((r) => prevMap.has(r.id) && prevMap.get(r.id) !== r.start_time)
        .map((r) => r.id)
    );

    // Clear highlight after 2 seconds
    if (this.changedIds.size > 0) {
      setTimeout(() => (this.changedIds = new Set()), 2000);
    }

    this.schedule = schedule;
    this.rows = newRows;

    // Pre-select first fixed event in dropdown if nothing selected yet
    if (!this.selectedEventId && schedule.fixed_events.length > 0) {
      this.selectedEventId = schedule.fixed_events[0].id;
    }
  }

  /** "HH:MM" → minutes since midnight */
  timeToMinutes(t: string): number {
    const [h, m] = t.split(':').map(Number);
    return h * 60 + m;
  }

  /** minutes since midnight → "HH:MM" */
  fmt(minutes: number): string {
    const h = Math.floor(minutes / 60).toString().padStart(2, '0');
    const m = (minutes % 60).toString().padStart(2, '0');
    return `${h}:${m}`;
  }

  backlogTasks() {
    return this.schedule?.flexible_tasks.filter((t) => t.status === 'backlog') ?? [];
  }
}
