// Mirrors the Pydantic models from backend/app/models.py

export interface FixedEvent {
  id: string;
  title: string;
  start_time: number;  // minutes since midnight
  end_time: number;
}

export interface FlexibleTask {
  id: string;
  title: string;
  duration: number;
  priority: number;
  deadline: number | null;
  earliest_start: number | null;
  latest_end: number | null;
  status: 'scheduled' | 'backlog';
  start_time: number | null;
  is_deadline_today: boolean;
  actual_duration: number | null;
  depends_on: string | null;
  is_fixed?: boolean;
}

export interface DaySchedule {
  date: string;
  day_start: number;
  day_end: number;
  fixed_events: FixedEvent[];
  flexible_tasks: FlexibleTask[];
}

export interface WeekSchedule {
  week_start_date: string;
  days: DaySchedule[];
}

export interface EventOverrunDisruption {
  type: 'event_overrun';
  event_id: string;
  new_end_time: number;
}

export interface WeekDisruption {
  day_date: string;
  type: 'event_overrun' | 'event_reschedule' | 'event_cancelled';
  event_id: string;
  new_start_time?: number | null;
  new_end_time?: number | null;
}

// A positioned block rendered inside a day column
export interface CalendarBlock {
  id: string;
  title: string;
  start_time: number;
  end_time: number;
  kind: 'fixed' | 'task';
  priority?: number;
  is_fixed?: boolean;
  depends_on?: string | null;
  deadline?: number | null;
  deadlineAtRisk?: boolean;  // true if end_time > deadline
  // CSS values, computed from time
  topPct: number;
  heightPct: number;
  leftPct?: number;
  widthPct?: number;
}

// A dependency arrow connecting two task blocks within the same day column
export interface DependencyArrow {
  fromId: string;   // prerequisite task id
  toId:   string;   // dependent task id
  // SVG y-coords in percentage of column height (centre of each block)
  fromMidPct: number;
  toTopPct:   number;
}

// Response from POST /schedule/disrupt
export interface DisruptDayResponse {
  schedule: DaySchedule;
  explanations: string[];
}

// Response from POST /schedule/week/disrupt
export interface DisruptWeekResponse {
  schedule: WeekSchedule;
  explanations: string[];
}

// Request body for POST /schedule/check
export interface CheckRequest {
  schedule: DaySchedule;
  current_time: number;  // minutes since midnight
}

// Response from GET /tasks/predict-duration
export interface DurationPrediction {
  predicted_duration: number;
  is_model_based: boolean;
  message: string;
}

// Response from POST /tasks/parse
export interface ParsedTask {
  title:          string | null;
  duration:       number | null;
  deadline:       number | null;
  priority:       number | null;
  category:       string | null;
  earliest_start: number | null;
  latest_end:     number | null;
  parser_used:    string;
}

// Unified row type for the simple list view (ScheduleViewComponent)
export interface ScheduleRow {
  id: string;
  title: string;
  start_time: number;
  end_time: number;
  kind: 'fixed' | 'task';
  priority?: number;
}
