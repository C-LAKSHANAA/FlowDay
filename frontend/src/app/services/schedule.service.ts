import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  CheckRequest,
  DaySchedule,
  DisruptDayResponse,
  DisruptWeekResponse,
  DurationPrediction,
  EventOverrunDisruption,
  ParsedTask,
  WeekDisruption,
  WeekSchedule,
} from '../models/schedule.models';
import { environment } from '../../environments/environment';

const API = environment.apiUrl;

@Injectable({ providedIn: 'root' })
export class ScheduleService {
  constructor(private http: HttpClient) {}

  getDemo(): Observable<DaySchedule> {
    return this.http.get<DaySchedule>(`${API}/schedule/demo`);
  }

  getWeekDemo(): Observable<WeekSchedule> {
    return this.http.get<WeekSchedule>(`${API}/schedule/week/demo`);
  }

  disrupt(disruption: EventOverrunDisruption): Observable<DisruptDayResponse> {
    return this.http.post<DisruptDayResponse>(`${API}/schedule/disrupt`, disruption);
  }

  disruptWeek(disruption: WeekDisruption): Observable<DisruptWeekResponse> {
    return this.http.post<DisruptWeekResponse>(`${API}/schedule/week/disrupt`, disruption);
  }

  solveDay(schedule: DaySchedule): Observable<DaySchedule> {
    return this.http.post<DaySchedule>(`${API}/schedule/solve`, schedule);
  }

  checkSchedule(req: CheckRequest): Observable<DisruptDayResponse> {
    return this.http.post<DisruptDayResponse>(`${API}/schedule/check`, req);
  }

  predictDuration(category: string, estimatedDuration: number): Observable<DurationPrediction> {
    const params = new URLSearchParams({
      category,
      estimated_duration: String(estimatedDuration),
    });
    return this.http.get<DurationPrediction>(`${API}/tasks/predict-duration?${params}`);
  }

  parseTask(text: string): Observable<ParsedTask> {
    return this.http.post<ParsedTask>(`${API}/tasks/parse`, { text });
  }
}
