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
  task: Omit<FlexibleTask, 'status' | 'start_time' | 'is_deadline_today' | 'actual_duration'>;
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
  id        = '';
  title     = '';
  duration  = 60;
  priority  = 5;
  category  = '';
  dependsOn = '';
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
    if (c['editTask']) this.reset();
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
        if (parsed.title)          this.title    = parsed.title;
        if (parsed.duration)       this.duration = parsed.duration;
        if (parsed.priority)       this.priority = parsed.priority;
        if (parsed.category)       this.category = parsed.category;
        if (parsed.deadline)       this.deadlineInput      = this.toHHMM(parsed.deadline);
        if (parsed.earliest_start) this.earliestStartInput = this.toHHMM(parsed.earliest_start);
        if (parsed.latest_end)     this.latestEndInput     = this.toHHMM(parsed.latest_end);
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

  private reset(): void {
    this.prediction = null; this.predicting = false;
    this.suggestionDismissed = false;
    this.parseText = ''; this.parseError = '';
    const t = this.editTask;
    if (t) {
      this.id = t.id; this.title = t.title; this.duration = t.duration;
      this.priority = t.priority; this.category = ''; this.dependsOn = t.depends_on ?? '';
      this.deadlineInput      = t.deadline       ? this.toHHMM(t.deadline)       : '';
      this.earliestStartInput = t.earliest_start ? this.toHHMM(t.earliest_start) : '';
      this.latestEndInput     = t.latest_end     ? this.toHHMM(t.latest_end)     : '';
    } else {
      this.id = `task-${Date.now()}`; this.title = ''; this.duration = 60;
      this.priority = 5; this.category = ''; this.dependsOn = '';
      this.deadlineInput = ''; this.earliestStartInput = ''; this.latestEndInput = '';
    }
  }

  get eligibleDependencies(): FlexibleTask[] {
    return this.dayTasks.filter(t => t.id !== this.id);
  }

  submit(): void {
    if (!this.title.trim() || this.duration <= 0) return;
    this.save.emit({
      dayDate: this.dayDate,
      task: {
        id: this.id, title: this.title.trim(), duration: this.duration,
        priority: this.priority, depends_on: this.dependsOn || null,
        deadline:       this.deadlineInput       ? this.toMinutes(this.deadlineInput)       : null,
        earliest_start: this.earliestStartInput  ? this.toMinutes(this.earliestStartInput)  : null,
        latest_end:     this.latestEndInput       ? this.toMinutes(this.latestEndInput)       : null,
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
