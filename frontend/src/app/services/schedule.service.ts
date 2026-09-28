import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  CheckRequest,
  DaySchedule,
  DisruptDayResponse,
  DisruptWeekResponse,
  EventOverrunDisruption,
  WeekDisruption,
  WeekSchedule,
} from '../models/schedule.models';

const API = 'http://localhost:5000';

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
}
