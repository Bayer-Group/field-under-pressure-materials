import { httpClient } from './httpClient';

export interface CalendarSuggestion {
  id: string;
  text: string;
}

export interface CalendarDevelopment {
  id: string;
  text: string;
  startDate: string; // YYYY-MM-DD
  endDate: string;   // YYYY-MM-DD
}

export interface CalendarTask {
  id: string;
  text: string;
  completed: boolean;
  suggestionId: string | null;
}

export interface CalendarNote {
  id: string;
  text: string;
  createdAt: string | null;
}

export interface CalendarDay {
  day: number;
  date: string; // YYYY-MM-DD
  tasks: CalendarTask[];
  notes: CalendarNote[];
}

export interface CalendarMonth {
  monthIndex: number; // 0..11
  name: string;
  suggestions: CalendarSuggestion[];
  development: CalendarDevelopment[];
  days: CalendarDay[];
}

export interface CalendarDocument {
  id: string;
  year: number;
  availableYears: number[];
  months: CalendarMonth[];
  updatedAt: string | null;
}

const BASE_PATH = '/api/v1/calendar';

export function fetchCalendar(year?: number, signal?: AbortSignal): Promise<CalendarDocument> {
  return httpClient.get<CalendarDocument>(BASE_PATH, {
    params: year !== undefined ? { year } : undefined,
    signal,
  });
}

export function addCalendarTask(
  monthIndex: number,
  day: number,
  text: string,
  options?: { suggestionId?: string | null; year?: number },
): Promise<CalendarDocument> {
  return httpClient.post<CalendarDocument>(
    `${BASE_PATH}/months/${monthIndex}/days/${day}/tasks`,
    {
      text,
      suggestionId: options?.suggestionId ?? null,
      year: options?.year ?? 2026,
    },
  );
}

export function updateCalendarTask(
  monthIndex: number,
  day: number,
  taskId: string,
  patch: { completed?: boolean; text?: string; year?: number },
): Promise<CalendarDocument> {
  return httpClient.patch<CalendarDocument>(
    `${BASE_PATH}/months/${monthIndex}/days/${day}/tasks/${encodeURIComponent(taskId)}`,
    {
      completed: patch.completed,
      text: patch.text,
      year: patch.year ?? 2026,
    },
  );
}

export function deleteCalendarTask(
  monthIndex: number,
  day: number,
  taskId: string,
  year = 2026,
): Promise<CalendarDocument> {
  return httpClient.delete<CalendarDocument>(
    `${BASE_PATH}/months/${monthIndex}/days/${day}/tasks/${encodeURIComponent(taskId)}`,
    { params: { year } },
  );
}

export function addCalendarNote(
  monthIndex: number,
  day: number,
  text: string,
  year = 2026,
): Promise<CalendarDocument> {
  return httpClient.post<CalendarDocument>(
    `${BASE_PATH}/months/${monthIndex}/days/${day}/notes`,
    { text, year },
  );
}

export function deleteCalendarNote(
  monthIndex: number,
  day: number,
  noteId: string,
  year = 2026,
): Promise<CalendarDocument> {
  return httpClient.delete<CalendarDocument>(
    `${BASE_PATH}/months/${monthIndex}/days/${day}/notes/${encodeURIComponent(noteId)}`,
    { params: { year } },
  );
}
