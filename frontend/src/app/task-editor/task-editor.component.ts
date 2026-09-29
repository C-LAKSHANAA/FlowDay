import {
  Component,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  Output,
  SimpleChanges,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject, Subscription } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap, catchError } from 'rxjs/operators';
import { EMPTY } from 'rxjs';
import { ScheduleService } from '../services/schedule.service';
import { DurationPrediction, FlexibleTask } from '../models/schedule.models';

export interface TaskSaveEvent {
  task: Omit<FlexibleTask, 'is_deadline_today' | 'actual_duration'>;
  dayDate: string;
}

@Component({
  selector: 'app-task-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './task-editor.component.html',
  styleUrls: ['./task-editor.component.css'],
})
export class TaskEditorComponent implements OnChanges, OnDestroy {
  @Input() editTask: FlexibleTask | null = null;
  @Input() dayTasks: FlexibleTask[] = [];
  @Input() dayDate = '';
  @Output() save   = new EventEmitter<TaskSaveEvent>();
  @Output() cancel = new EventEmitter<void>();

  // ── Form fields ───────────────────────────────────────────────────────
  id             = '';
  title          = '';
  taskDate       = '';
  duration       = 60;
  category       = '';
  dependsOn      = '';
  scheduleMode: 'auto' | 'specific' | 'backlog' = 'auto';
  startTimeInput = '';
  deadlineInput      = '';
  earliestStartInput = '';
  latestEndInput     = '';

  // ── Natural-language parse ────────────────────────────────────────────
  parseText  = '';
  parsing    = false;
  parseError = '';

  // ── Duration suggestion ───────────────────────────────────────────────
  prediction: DurationPrediction | null = null;
  predicting         = false;
  suggestionDismissed = false;

  get showSuggestion(): boolean {
    return (
      !!this.prediction &&
      !this.suggestionDismissed &&
      this.prediction.predicted_duration !== this.duration
    );
  }

  private readonly suggest$ = new Subject<{ category: string; duration: number }>();
  private subs = new Subscription();

  constructor(private svc: ScheduleService) {
    this.subs.add(
      this.suggest$.pipe(
        debounceTime(600),
        distinctUntilChanged((a, b) => a.category === b.category && a.duration === b.duration),
        switchMap(({ category, duration }) => {
          this.predicting = true;
          return this.svc.predictDuration(category, duration).pipe(
            catchError(() => { this.predicting = false; return EMPTY; }),
          );
        }),
      ).subscribe(pred => {
        this.predicting = false;
        this.prediction = pred;
        this.suggestionDismissed = false;
      })
    );
  }

  ngOnChanges(c: SimpleChanges): void {
    if (c['editTask'] || c['dayDate']) this.reset();
  }

  ngOnDestroy(): void { this.subs.unsubscribe(); }

  // ── NL parse ─────────────────────────────────────────────────────────

  parseDescription(): void {
    if (!this.parseText.trim()) return;
    this.parsing = true;
    this.parseError = '';
    this.svc.parseTask(this.parseText).subscribe({
      next: (parsed) => {
        this.parsing = false;
        if (parsed.title)    this.title    = parsed.title;
        if (parsed.priority) this.priority = parsed.priority;
        if (parsed.category) this.category = parsed.category;

        // If a time range was parsed (earliest_start + latest_end),
        // compute duration from them and switch to Fixed Time mode.
        if (parsed.earliest_start != null && parsed.latest_end != null) {
          const computed = parsed.latest_end - parsed.earliest_start;
          this.duration           = computed > 0 ? computed : (parsed.duration ?? this.duration);
          this.scheduleMode       = 'specific';
          this.startTimeInput     = this.toHHMM(parsed.earliest_start);
          this.earliestStartInput = this.toHHMM(parsed.earliest_start);
          this.latestEndInput     = this.toHHMM(parsed.latest_end);
        } else {
          // No range — use explicit duration if provided
          if (parsed.duration)       this.duration = parsed.duration;
          if (parsed.earliest_start) {
            this.scheduleMode       = 'specific';
            this.startTimeInput     = this.toHHMM(parsed.earliest_start);
            this.earliestStartInput = this.toHHMM(parsed.earliest_start);
          }
          if (parsed.latest_end) this.latestEndInput = this.toHHMM(parsed.latest_end);
        }

        if (parsed.deadline) this.deadlineInput = this.toHHMM(parsed.deadline);
        this.onCategoryOrDurationChange();
        this.parseText = '';
      },
      error: (e) => {
        this.parsing  = false;
        this.parseError = e.error?.detail ?? 'Could not parse description.';
      },
    });
  }

  // ── Duration suggestion ───────────────────────────────────────────────

  onCategoryOrDurationChange(): void {
    this.suggestionDismissed = false;
    this.suggest$.next({ category: this.category, duration: this.duration });
  }

  acceptSuggestion(): void {
    if (this.prediction) {
      this.duration = this.prediction.predicted_duration;
      this.suggestionDismissed = true;
    }
  }

  dismissSuggestion(): void { this.suggestionDismissed = true; }

  // ── Reset ─────────────────────────────────────────────────────────────

  priorityLevel: 'high' | 'med' | 'low' = 'high';

  get priority(): number {
    return this.priorityLevel === 'high' ? 9 : this.priorityLevel === 'med' ? 5 : 2;
  }

  set priority(val: number) {
    if (val >= 8) this.priorityLevel = 'high';
    else if (val >= 4) this.priorityLevel = 'med';
    else this.priorityLevel = 'low';
  }

  // ── Reset ─────────────────────────────────────────────────────────────

  private reset(): void {
    this.prediction = null; this.predicting = false;
    this.suggestionDismissed = false;
    this.parseText = ''; this.parseError = '';
    this.taskDate = this.dayDate || this.getTodayIso();
    const t = this.editTask;
    if (t) {
      this.id = t.id; this.title = t.title; this.duration = t.duration;
      this.priority = t.priority; this.category = ''; this.dependsOn = t.depends_on ?? '';
      if (t.start_time !== null) {
        this.scheduleMode = 'specific';
        this.startTimeInput = this.toHHMM(t.start_time);
      } else {
        this.scheduleMode = 'auto';
        this.startTimeInput = '';
      }
      this.deadlineInput      = t.deadline       ? this.toHHMM(t.deadline)       : '';
      this.earliestStartInput = t.earliest_start ? this.toHHMM(t.earliest_start) : '';
      this.latestEndInput     = t.latest_end     ? this.toHHMM(t.latest_end)     : '';
    } else {
      this.id = `task-${Date.now()}`; this.title = ''; this.duration = 60;
      this.priorityLevel = 'high'; this.category = ''; this.dependsOn = '';
      this.scheduleMode = 'auto'; this.startTimeInput = '09:00';
      this.deadlineInput = ''; this.earliestStartInput = ''; this.latestEndInput = '';
    }
  }

  pastTimeError = '';

  private getTodayIso(): string {
    const d = new Date();
    const y = d.getFullYear();
    const m = (d.getMonth() + 1).toString().padStart(2, '0');
    const day = d.getDate().toString().padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  get isPastDate(): boolean {
    if (!this.taskDate) return false;
    return this.taskDate < this.getTodayIso();
  }

  // ── Past time validation against current system clock ──────────────────
  get isPastTime(): boolean {
    if (this.isPastDate) return true;
    if (!this.taskDate || this.taskDate !== this.getTodayIso()) return false;
    if (this.scheduleMode !== 'specific' || !this.startTimeInput) return false;

    const now = new Date();
    const currentMin = now.getHours() * 60 + now.getMinutes();
    const startMin = this.toMinutes(this.startTimeInput);
    return startMin < currentMin;
  }

  get systemTimeString(): string {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  setCurrentTime(): void {
    const now = new Date();
    this.startTimeInput = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
  }

  get eligibleDependencies(): FlexibleTask[] {
    return this.dayTasks.filter(t => t.id !== this.id);
  }

  submit(): void {
    if (!this.title.trim() || this.duration <= 0) return;

    const isFixed = this.scheduleMode === 'specific';

    // Only validate past date/time when the user explicitly picks a fixed start time.
    if (isFixed) {
      if (this.isPastDate) {
        this.pastTimeError = `Cannot schedule task on a past date (${this.taskDate})! Please select today or a future date.`;
        return;
      }
      if (this.isPastTime) {
        this.pastTimeError = `Selected start time has already passed according to system clock (${this.systemTimeString}). Please choose a future time.`;
        return;
      }
    }

    this.pastTimeError = '';

    let startTime: number | null = null;
    if (isFixed && this.startTimeInput) {
      startTime = this.toMinutes(this.startTimeInput);
    }

    // For backlog tasks, no start time — let the solver place them later.
    const isBacklog = this.scheduleMode === 'backlog' || (!isFixed && startTime === null);

    const earliestStart = startTime !== null
      ? startTime
      : (this.earliestStartInput ? this.toMinutes(this.earliestStartInput) : null);
    const latestEnd = startTime !== null
      ? startTime + this.duration
      : (this.latestEndInput ? this.toMinutes(this.latestEndInput) : null);

    const targetDate = this.taskDate || this.dayDate || this.getTodayIso();

    this.save.emit({
      dayDate: targetDate,
      task: {
        id: this.id,
        title: this.title.trim(),
        duration: this.duration,
        priority: this.priority,
        status: isBacklog ? 'backlog' : 'scheduled',
        start_time: startTime,
        is_fixed: isFixed,
        depends_on: this.dependsOn || null,
        deadline:       this.deadlineInput ? this.toMinutes(this.deadlineInput) : null,
        earliest_start: earliestStart,
        latest_end:     latestEnd,
      },
    });
  }

  private toMinutes(t: string): number {
    const [h, m] = t.split(':').map(Number); return h * 60 + m;
  }
  private toHHMM(m: number): string {
    return `${Math.floor(m/60).toString().padStart(2,'0')}:${(m%60).toString().padStart(2,'0')}`;
  }
}
