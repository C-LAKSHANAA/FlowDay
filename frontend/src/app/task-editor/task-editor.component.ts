import {
  Component,
  EventEmitter,
  Input,
  OnChanges,
  Output,
  SimpleChanges,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { FlexibleTask } from '../models/schedule.models';

/** Emitted when the user saves a task (new or edited). */
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
export class TaskEditorComponent implements OnChanges {
  /** The task being edited, or null for a new task. */
  @Input() editTask: FlexibleTask | null = null;

  /** All tasks in the same day — used to populate the dependency dropdown. */
  @Input() dayTasks: FlexibleTask[] = [];

  /** ISO date of the day this task belongs to. */
  @Input() dayDate = '';

  @Output() save   = new EventEmitter<TaskSaveEvent>();
  @Output() cancel = new EventEmitter<void>();

  // ── Form state ────────────────────────────────────────────────────────
  id        = '';
  title     = '';
  duration  = 60;
  priority  = 5;
  dependsOn = '';   // '' means no dependency

  // Optional constraint fields (HH:MM strings)
  deadlineInput      = '';
  earliestStartInput = '';
  latestEndInput     = '';

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['editTask']) {
      this.reset();
    }
  }

  private reset(): void {
    const t = this.editTask;
    if (t) {
      this.id        = t.id;
      this.title     = t.title;
      this.duration  = t.duration;
      this.priority  = t.priority;
      this.dependsOn = t.depends_on ?? '';
      this.deadlineInput      = t.deadline       ? this.toHHMM(t.deadline)       : '';
      this.earliestStartInput = t.earliest_start ? this.toHHMM(t.earliest_start) : '';
      this.latestEndInput     = t.latest_end     ? this.toHHMM(t.latest_end)     : '';
    } else {
      this.id        = `task-${Date.now()}`;
      this.title     = '';
      this.duration  = 60;
      this.priority  = 5;
      this.dependsOn = '';
      this.deadlineInput      = '';
      this.earliestStartInput = '';
      this.latestEndInput     = '';
    }
  }

  /** Tasks that can be chosen as a dependency (exclude self). */
  get eligibleDependencies(): FlexibleTask[] {
    return this.dayTasks.filter(t => t.id !== this.id);
  }

  submit(): void {
    if (!this.title.trim() || this.duration <= 0) return;

    this.save.emit({
      dayDate: this.dayDate,
      task: {
        id:             this.id,
        title:          this.title.trim(),
        duration:       this.duration,
        priority:       this.priority,
        depends_on:     this.dependsOn || null,
        deadline:       this.deadlineInput       ? this.toMinutes(this.deadlineInput)       : null,
        earliest_start: this.earliestStartInput  ? this.toMinutes(this.earliestStartInput)  : null,
        latest_end:     this.latestEndInput       ? this.toMinutes(this.latestEndInput)       : null,
      },
    });
  }

  private toMinutes(t: string): number {
    const [h, m] = t.split(':').map(Number);
    return h * 60 + m;
  }

  private toHHMM(minutes: number): string {
    return `${Math.floor(minutes / 60).toString().padStart(2, '0')}:${(minutes % 60).toString().padStart(2, '0')}`;
  }
}
