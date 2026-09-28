import { Component } from '@angular/core';
import { WeeklyCalendarComponent } from './weekly-calendar/weekly-calendar.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [WeeklyCalendarComponent],
  template: '<app-weekly-calendar />',
})
export class AppComponent {}
