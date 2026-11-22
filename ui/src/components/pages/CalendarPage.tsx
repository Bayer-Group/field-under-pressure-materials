import { useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  CalendarDays,
  Check,
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  Lightbulb,
  Loader2,
  Plus,
  Sprout,
  StickyNote,
  Trash2,
} from 'lucide-react';
import {
  addCalendarNote,
  addCalendarTask,
  deleteCalendarNote,
  deleteCalendarTask,
  fetchCalendar,
  updateCalendarTask,
  type CalendarDay,
  type CalendarDevelopment,
  type CalendarDocument,
} from '../../api/calendarApi';
import { ApiError } from '../../api/httpClient';
import { useLanguage } from '../../contexts/LanguageContext';
import { readPagePref, writePagePref } from '../../utils/pagePrefs';
import { Dropdown } from '../common/Dropdown';

interface DevColorToken {
  solid: string;
  tintLight: string;
  tintDark: string;
}

const DEVELOPMENT_PALETTE: DevColorToken[] = [
  { solid: '#10b981', tintLight: 'rgba(16, 185, 129, 0.13)', tintDark: 'rgba(16, 185, 129, 0.20)' },
  { solid: '#8b5cf6', tintLight: 'rgba(139, 92, 246, 0.13)', tintDark: 'rgba(139, 92, 246, 0.22)' },
  { solid: '#ec4899', tintLight: 'rgba(236, 72, 153, 0.13)', tintDark: 'rgba(236, 72, 153, 0.22)' },
  { solid: '#06b6d4', tintLight: 'rgba(6, 182, 212, 0.13)', tintDark: 'rgba(6, 182, 212, 0.22)' },
];

interface CalendarCell {
  key: string;
  dateIso: string;
  year: number;
  dayNumber: number;
  monthIndex: number;
  inCurrentMonth: boolean;
}

function pad2(value: number): string {
  return String(value).padStart(2, '0');
}

function formatDateIso(year: number, monthIndex: number, day: number): string {
  return `${year}-${pad2(monthIndex + 1)}-${pad2(day)}`;
}

function daysInMonth(year: number, monthIndex: number): number {
  return new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate();
}

function buildMonthGrid(year: number, monthIndex: number): CalendarCell[] {
  const firstDowUtc = new Date(Date.UTC(year, monthIndex, 1)).getUTCDay();
  // Monday-first offset: Mon=0 .. Sun=6
  const leading = (firstDowUtc + 6) % 7;
  const totalDays = daysInMonth(year, monthIndex);
  const totalCells = Math.ceil((leading + totalDays) / 7) * 7;

  const cells: CalendarCell[] = [];
  for (let i = 0; i < totalCells; i++) {
    const offsetDay = i - leading + 1;
    const dateObj = new Date(Date.UTC(year, monthIndex, offsetDay));
    const cellYear = dateObj.getUTCFullYear();
    const cellMonth = dateObj.getUTCMonth();
    const cellDay = dateObj.getUTCDate();
    const inCurrentMonth = cellYear === year && cellMonth === monthIndex;
    const dateIso = formatDateIso(cellYear, cellMonth, cellDay);
    cells.push({
      key: `${dateIso}-${i}`,
      dateIso,
      year: cellYear,
      dayNumber: cellDay,
      monthIndex: cellMonth,
      inCurrentMonth,
    });
  }
  return cells;
}

function formatShortRange(startIso: string, endIso: string): string {
  const fmt = (iso: string) => {
    const [, mm, dd] = iso.split('-');
    return `${dd}.${mm}`;
  };
  return `${fmt(startIso)} – ${fmt(endIso)}`;
}

export function CalendarPage() {
  const { t, language } = useLanguage();
  const now = useMemo(() => new Date(), []);
  const todayYear = now.getFullYear();
  const todayMonthIndex = now.getMonth();
  const todayDay = now.getDate();

  const initialCalPrefs = useMemo(() => {
    const saved = readPagePref<{ year?: unknown; monthIndex?: unknown; selectedDay?: unknown }>('calendar', {});
    const savedYear =
      typeof saved?.year === 'number' && Number.isInteger(saved.year) && saved.year >= 2000 && saved.year <= 2100
        ? saved.year
        : todayYear;
    const savedMonth =
      typeof saved?.monthIndex === 'number' && Number.isInteger(saved.monthIndex) && saved.monthIndex >= 0 && saved.monthIndex <= 11
        ? saved.monthIndex
        : todayMonthIndex;
    const maxDay = daysInMonth(savedYear, savedMonth);
    const savedDay =
      typeof saved?.selectedDay === 'number' && Number.isInteger(saved.selectedDay) && saved.selectedDay >= 1
        ? Math.min(saved.selectedDay, maxDay)
        : Math.min(todayDay, maxDay);
    return { year: savedYear, monthIndex: savedMonth, selectedDay: savedDay };
  }, [todayYear, todayMonthIndex, todayDay]);

  const [selectedYear, setSelectedYear] = useState<number>(initialCalPrefs.year);
  const [docsByYear, setDocsByYear] = useState<Record<number, CalendarDocument>>({});
  const [availableYears, setAvailableYears] = useState<number[]>([initialCalPrefs.year]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [monthIndex, setMonthIndex] = useState<number>(initialCalPrefs.monthIndex);
  const [selectedDay, setSelectedDay] = useState<number>(initialCalPrefs.selectedDay);
  const [hoveredDevId, setHoveredDevId] = useState<string | null>(null);

  useEffect(() => {
    writePagePref('calendar', { year: selectedYear, monthIndex, selectedDay });
  }, [selectedYear, monthIndex, selectedDay]);

  const [newTaskText, setNewTaskText] = useState('');
  const [newNoteText, setNewNoteText] = useState('');
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const calendarDoc = docsByYear[selectedYear] ?? null;

  useEffect(() => {
    if (docsByYear[selectedYear]) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    fetchCalendar(selectedYear, controller.signal)
      .then((doc) => {
        if (controller.signal.aborted) return;
        setDocsByYear((prev) => ({ ...prev, [doc.year]: doc }));
        const years = doc.availableYears?.length ? doc.availableYears : [doc.year];
        setAvailableYears(years);
        if (doc.year !== selectedYear) {
          setSelectedYear(doc.year);
        }
        setSelectedDay((prev) => Math.min(prev, daysInMonth(doc.year, monthIndex)));
        setLoading(false);

        // Prefetch any remaining available years in the background for instant Dec -> Jan switching
        for (const yr of years) {
          if (yr !== doc.year) {
            void fetchCalendar(yr, controller.signal)
              .then((otherDoc) => {
                if (!controller.signal.aborted) {
                  setDocsByYear((prev) => (prev[otherDoc.year] ? prev : { ...prev, [otherDoc.year]: otherDoc }));
                }
              })
              .catch(() => {});
          }
        }
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404 && selectedYear !== todayYear) {
          setSelectedYear(todayYear);
          return;
        }
        setLoadError(err instanceof ApiError ? err.message : t.calendar.loadError);
        setLoading(false);
      });
    return () => controller.abort();
  }, [selectedYear, docsByYear, monthIndex, t.calendar.loadError]);

  const sortedYears = useMemo(() => [...availableYears].sort((a, b) => a - b), [availableYears]);
  const minYear = sortedYears[0] ?? selectedYear;
  const maxYear = sortedYears[sortedYears.length - 1] ?? selectedYear;
  const year = calendarDoc?.year ?? selectedYear;
  const activeMonth = calendarDoc?.months[monthIndex] ?? null;
  const todayIso = formatDateIso(todayYear, todayMonthIndex, todayDay);
  const selectedDateIso = formatDateIso(year, monthIndex, selectedDay);

  const isAtStart = selectedYear <= minYear && monthIndex === 0;
  const isAtEnd = selectedYear >= maxYear && monthIndex === 11;

  const storeUpdatedDoc = (updated: CalendarDocument) => {
    setDocsByYear((prev) => ({ ...prev, [updated.year]: updated }));
    if (updated.availableYears?.length) {
      setAvailableYears(updated.availableYears);
    }
  };

  const cells = useMemo(() => buildMonthGrid(year, monthIndex), [year, monthIndex]);

  const dayMap = useMemo(() => {
    const map = new Map<number, CalendarDay>();
    for (const entry of activeMonth?.days ?? []) {
      map.set(entry.day, entry);
    }
    return map;
  }, [activeMonth]);

  const coloredDevelopments = useMemo(
    () =>
      (activeMonth?.development ?? []).map((item, idx) => ({
        item,
        color: DEVELOPMENT_PALETTE[idx % DEVELOPMENT_PALETTE.length],
      })),
    [activeMonth],
  );

  const selectedDayEntry = dayMap.get(selectedDay) ?? null;
  const selectedTasks = selectedDayEntry?.tasks ?? [];
  const selectedNotes = selectedDayEntry?.notes ?? [];
  const assignedSuggestionIds = useMemo(
    () => new Set(selectedTasks.map((task) => task.suggestionId).filter((id): id is string => Boolean(id))),
    [selectedTasks],
  );

  const formattedSelectedDate = useMemo(() => {
    const dateObj = new Date(Date.UTC(year, monthIndex, selectedDay));
    return new Intl.DateTimeFormat(language === 'pl' ? 'pl-PL' : 'en-US', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      timeZone: 'UTC',
    }).format(dateObj);
  }, [year, monthIndex, selectedDay, language]);

  const shortSelectedDayLabel = `${pad2(selectedDay)}.${pad2(monthIndex + 1)}`;

  const handleNavigate = (targetYear: number, targetMonth: number, targetDay?: number) => {
    if (!sortedYears.includes(targetYear) || targetMonth < 0 || targetMonth > 11) return;
    const maxDay = daysInMonth(targetYear, targetMonth);
    setSelectedYear(targetYear);
    setMonthIndex(targetMonth);
    setHoveredDevId(null);
    setActionError(null);
    if (targetDay !== undefined) {
      setSelectedDay(Math.min(targetDay, maxDay));
    } else if (targetYear === todayYear && targetMonth === todayMonthIndex) {
      setSelectedDay(Math.min(todayDay, maxDay));
    } else {
      setSelectedDay(1);
    }
  };

  const handleStepMonth = (delta: -1 | 1) => {
    if (delta === -1) {
      if (isAtStart) return;
      if (monthIndex > 0) {
        handleNavigate(selectedYear, monthIndex - 1);
      } else {
        const yearIdx = sortedYears.indexOf(selectedYear);
        if (yearIdx > 0) {
          handleNavigate(sortedYears[yearIdx - 1], 11);
        }
      }
      return;
    }
    if (isAtEnd) return;
    if (monthIndex < 11) {
      handleNavigate(selectedYear, monthIndex + 1);
    } else {
      const yearIdx = sortedYears.indexOf(selectedYear);
      if (yearIdx !== -1 && yearIdx < sortedYears.length - 1) {
        handleNavigate(sortedYears[yearIdx + 1], 0);
      }
    }
  };

  const handleJumpToday = () => {
    const targetYear = sortedYears.includes(todayYear) ? todayYear : minYear;
    handleNavigate(targetYear, todayMonthIndex, todayDay);
  };

  const handleAddTask = async (event: FormEvent) => {
    event.preventDefault();
    const cleaned = newTaskText.trim();
    if (!cleaned || busyKey) return;
    setBusyKey('add-task');
    setActionError(null);
    try {
      const updated = await addCalendarTask(monthIndex, selectedDay, cleaned, { year });
      storeUpdatedDoc(updated);
      setNewTaskText('');
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t.calendar.saveError);
    } finally {
      setBusyKey(null);
    }
  };

  const handleAssignSuggestion = async (suggestionId: string, text: string) => {
    if (busyKey) return;
    setBusyKey(`sug-${suggestionId}`);
    setActionError(null);
    try {
      const updated = await addCalendarTask(monthIndex, selectedDay, text, { suggestionId, year });
      storeUpdatedDoc(updated);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t.calendar.saveError);
    } finally {
      setBusyKey(null);
    }
  };

  const handleToggleTask = async (taskId: string, nextCompleted: boolean) => {
    if (busyKey) return;
    setBusyKey(`toggle-${taskId}`);
    setActionError(null);
    try {
      const updated = await updateCalendarTask(monthIndex, selectedDay, taskId, {
        completed: nextCompleted,
        year,
      });
      storeUpdatedDoc(updated);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t.calendar.saveError);
    } finally {
      setBusyKey(null);
    }
  };

  const handleDeleteTask = async (taskId: string) => {
    if (busyKey) return;
    setBusyKey(`del-task-${taskId}`);
    setActionError(null);
    try {
      const updated = await deleteCalendarTask(monthIndex, selectedDay, taskId, year);
      storeUpdatedDoc(updated);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t.calendar.saveError);
    } finally {
      setBusyKey(null);
    }
  };

  const handleAddNote = async (event: FormEvent) => {
    event.preventDefault();
    const cleaned = newNoteText.trim();
    if (!cleaned || busyKey) return;
    setBusyKey('add-note');
    setActionError(null);
    try {
      const updated = await addCalendarNote(monthIndex, selectedDay, cleaned, year);
      storeUpdatedDoc(updated);
      setNewNoteText('');
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t.calendar.saveError);
    } finally {
      setBusyKey(null);
    }
  };

  const handleDeleteNote = async (noteId: string) => {
    if (busyKey) return;
    setBusyKey(`del-note-${noteId}`);
    setActionError(null);
    try {
      const updated = await deleteCalendarNote(monthIndex, selectedDay, noteId, year);
      storeUpdatedDoc(updated);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t.calendar.saveError);
    } finally {
      setBusyKey(null);
    }
  };

  const formatNoteTime = (iso: string | null): string => {
    if (!iso) return '';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat(language === 'pl' ? 'pl-PL' : 'en-US', {
      hour: '2-digit',
      minute: '2-digit',
    }).format(date);
  };

  const getCellDevelopments = (dateIso: string): Array<{ item: CalendarDevelopment; color: DevColorToken }> =>
    coloredDevelopments.filter(({ item }) => dateIso >= item.startDate && dateIso <= item.endDate);

  return (
    <div className="calendar-page">
      <div className="page-intro">
        <h1 className="page-title">{t.calendar.title}</h1>
      </div>

      {loading && (
        <div className="card calendar-loading-card" role="status">
          <Loader2 size={20} className="spin-icon" />
          <span>{t.calendar.loading}</span>
        </div>
      )}

      {loadError && (
        <div className="card calendar-error-banner" role="alert">
          {loadError}
        </div>
      )}

      {actionError && (
        <div className="card calendar-error-banner" role="alert">
          {actionError}
        </div>
      )}

      {calendarDoc && activeMonth && (
        <>
          <div className="calendar-main-grid">
            {/* LEFT: Main Monthly Calendar */}
            <section className="card calendar-month-card" aria-label={t.calendar.title}>
              <div className="calendar-month-header">
                <div className="calendar-month-nav">
                  <button
                    type="button"
                    className="secondary-btn calendar-nav-btn"
                    disabled={isAtStart}
                    onClick={() => handleStepMonth(-1)}
                    aria-label={t.calendar.prevMonth}
                    title={t.calendar.prevMonth}
                  >
                    <ChevronLeft size={16} />
                  </button>

                  <Dropdown
                    variant="calendar"
                    className="calendar-month-dropdown"
                    value={`${selectedYear}-${monthIndex}`}
                    onChange={(nextValue) => {
                      const [yrStr, moStr] = nextValue.split('-');
                      handleNavigate(Number(yrStr), Number(moStr));
                    }}
                    ariaLabel={t.calendar.title}
                    groups={sortedYears.map((yr) => ({
                      label: String(yr),
                      options: t.calendar.months.map((label, idx) => ({
                        value: `${yr}-${idx}`,
                        label: `${label} ${yr}`,
                      })),
                    }))}
                  />

                  <button
                    type="button"
                    className="secondary-btn calendar-nav-btn"
                    disabled={isAtEnd}
                    onClick={() => handleStepMonth(1)}
                    aria-label={t.calendar.nextMonth}
                    title={t.calendar.nextMonth}
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>

                <button type="button" className="secondary-btn calendar-today-btn" onClick={handleJumpToday}>
                  <CalendarDays size={14} />
                  <span>{t.calendar.today}</span>
                </button>
              </div>

              <div className="calendar-weekdays" role="row">
                {t.calendar.weekdaysShort.map((weekday) => (
                  <div key={weekday} className="calendar-weekday-cell" role="columnheader">
                    {weekday}
                  </div>
                ))}
              </div>

              <div className="calendar-days-grid" role="grid">
                {cells.map((cell) => {
                  const dayData = cell.inCurrentMonth ? dayMap.get(cell.dayNumber) : undefined;
                  const taskCount = dayData?.tasks.length ?? 0;
                  const completedCount = dayData?.tasks.filter((task) => task.completed).length ?? 0;
                  const noteCount = dayData?.notes.length ?? 0;
                  const hasTasks = taskCount > 0;
                  const hasNotes = noteCount > 0;
                  const isToday = cell.inCurrentMonth && cell.dateIso === todayIso;
                  const isSelected = cell.inCurrentMonth && cell.dateIso === selectedDateIso;

                  const activeDevs = cell.inCurrentMonth ? getCellDevelopments(cell.dateIso) : [];
                  const isHoveredDevMatch =
                    hoveredDevId !== null && activeDevs.some(({ item }) => item.id === hoveredDevId);

                  // Soft background tint when one or more development ranges cover this day
                  let cellBackground: string | undefined;
                  if (activeDevs.length === 1) {
                    cellBackground = `color-mix(in srgb, ${activeDevs[0].color.solid} 11%, var(--bg-surface))`;
                  } else if (activeDevs.length >= 2) {
                    cellBackground = `linear-gradient(135deg, color-mix(in srgb, ${activeDevs[0].color.solid} 13%, var(--bg-surface)) 0%, color-mix(in srgb, ${activeDevs[1].color.solid} 13%, var(--bg-surface)) 100%)`;
                  }

                  const isOutOfRange = !sortedYears.includes(cell.year);

                  return (
                    <button
                      key={cell.key}
                      type="button"
                      disabled={isOutOfRange}
                      className={`calendar-day-cell${cell.inCurrentMonth ? '' : ' is-outside'}${isOutOfRange ? ' is-out-of-range' : ''}${isSelected ? ' is-selected' : ''}${isToday ? ' is-today' : ''}${isHoveredDevMatch ? ' is-dev-highlight' : ''}`}
                      style={cellBackground ? { background: cellBackground } : undefined}
                      aria-pressed={isSelected}
                      onClick={() => {
                        if (isOutOfRange) return;
                        if (cell.inCurrentMonth) {
                          setSelectedDay(cell.dayNumber);
                          setActionError(null);
                        } else {
                          handleNavigate(cell.year, cell.monthIndex, cell.dayNumber);
                        }
                      }}
                    >
                      <div className="calendar-day-top">
                        <span className="calendar-day-num">{cell.dayNumber}</span>
                        {(hasTasks || hasNotes) && (
                          <span className="calendar-day-dots">
                            {hasTasks && (
                              <span
                                className="calendar-dot calendar-dot-task"
                                title={`${t.calendar.tasksDotLegend}: ${completedCount}/${taskCount}`}
                              />
                            )}
                            {hasNotes && (
                              <span
                                className="calendar-dot calendar-dot-note"
                                title={`${t.calendar.notesDotLegend}: ${noteCount}`}
                              />
                            )}
                          </span>
                        )}
                      </div>

                      {activeDevs.length > 0 && (
                        <div className="calendar-dev-bars" aria-hidden="true">
                          {activeDevs.map(({ item, color }) => {
                            const isStart = cell.dateIso === item.startDate;
                            const isEnd = cell.dateIso === item.endDate;
                            return (
                              <span
                                key={item.id}
                                className={`calendar-dev-bar${isStart ? ' is-start' : ''}${isEnd ? ' is-end' : ''}${hoveredDevId === item.id ? ' is-hovered' : ''}`}
                                style={{ backgroundColor: color.solid }}
                              />
                            );
                          })}
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>

              <div className="calendar-dot-legend">
                <span className="calendar-dot-legend-item">
                  <span className="calendar-dot calendar-dot-task" aria-hidden="true" />
                  <span>{t.calendar.tasksDotLegend}</span>
                </span>
                <span className="calendar-dot-legend-item">
                  <span className="calendar-dot calendar-dot-note" aria-hidden="true" />
                  <span>{t.calendar.notesDotLegend}</span>
                </span>
              </div>
            </section>

            {/* RIGHT: Vertical Column with Plant Development Legend + Selected Day Tasks & Notes */}
            <aside className="calendar-side-column">
              {/* 1. Plant Development Legend */}
              <section className="card calendar-dev-card" aria-labelledby="calendar-dev-heading">
                <div className="calendar-panel-head">
                  <div className="calendar-panel-title-row">
                    <Sprout size={17} className="panel-accent-icon" aria-hidden="true" />
                    <h2 id="calendar-dev-heading" className="panel-section-title">
                      {t.calendar.developmentTitle}
                    </h2>
                  </div>
                  <span className="calendar-month-pill">{t.calendar.months[monthIndex]}</span>
                </div>

                {coloredDevelopments.length === 0 ? (
                  <p className="calendar-empty-text">{t.calendar.developmentEmpty}</p>
                ) : (
                  <ul className="calendar-dev-list">
                    {coloredDevelopments.map(({ item, color }) => (
                      <li
                        key={item.id}
                        className={`calendar-dev-item${hoveredDevId === item.id ? ' is-hovered' : ''}`}
                        onMouseEnter={() => setHoveredDevId(item.id)}
                        onMouseLeave={() => setHoveredDevId(null)}
                      >
                        <span
                          className="calendar-dev-swatch"
                          style={{ backgroundColor: color.solid }}
                          aria-hidden="true"
                        />
                        <div className="calendar-dev-body">
                          <span className="calendar-dev-range">
                            {formatShortRange(item.startDate, item.endDate)}
                          </span>
                          <p className="calendar-dev-text">{item.text}</p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* 2. Selected Day: Tasks (with DB checkboxes) & Notes */}
              <section className="card calendar-day-card" aria-labelledby="calendar-day-heading">
                <div className="calendar-panel-head">
                  <div className="calendar-day-heading-wrap">
                    <span className="calendar-day-kicker">{t.calendar.dayPanelTitle}</span>
                    <h2 id="calendar-day-heading" className="calendar-selected-date">
                      {formattedSelectedDate}
                    </h2>
                  </div>
                </div>

                {/* Tasks Sub-section */}
                <div className="calendar-day-section">
                  <div className="calendar-subhead">
                    <span className="calendar-subhead-left">
                      <span className="calendar-dot calendar-dot-task" aria-hidden="true" />
                      <CheckSquare size={15} aria-hidden="true" />
                      <h3>{t.calendar.tasksTitle}</h3>
                    </span>
                    <span className="calendar-count-badge">{selectedTasks.length}</span>
                  </div>

                  {selectedTasks.length === 0 ? (
                    <p className="calendar-empty-text">{t.calendar.tasksEmpty}</p>
                  ) : (
                    <ul className="calendar-task-list">
                      {selectedTasks.map((task) => {
                        const isBusy = busyKey === `toggle-${task.id}` || busyKey === `del-task-${task.id}`;
                        return (
                          <li key={task.id} className={`calendar-task-item${task.completed ? ' is-done' : ''}`}>
                            <label className="calendar-task-check-label">
                              <input
                                type="checkbox"
                                checked={task.completed}
                                disabled={isBusy}
                                onChange={(e) => void handleToggleTask(task.id, e.target.checked)}
                              />
                              <span className="calendar-task-text">{task.text}</span>
                            </label>
                            <button
                              type="button"
                              className="row-delete-btn"
                              disabled={isBusy}
                              onClick={() => void handleDeleteTask(task.id)}
                              aria-label={t.calendar.deleteTask}
                              title={t.calendar.deleteTask}
                            >
                              <Trash2 size={14} />
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  )}

                  <form className="calendar-inline-form" onSubmit={(e) => void handleAddTask(e)}>
                    <input
                      type="text"
                      className="calendar-input"
                      value={newTaskText}
                      onChange={(e) => setNewTaskText(e.target.value)}
                      placeholder={t.calendar.taskPlaceholder}
                      disabled={busyKey === 'add-task'}
                    />
                    <button
                      type="submit"
                      className="primary-btn calendar-add-btn"
                      disabled={!newTaskText.trim() || busyKey === 'add-task'}
                    >
                      <Plus size={15} />
                      <span>{t.calendar.addTask}</span>
                    </button>
                  </form>
                </div>

                {/* Notes Sub-section */}
                <div className="calendar-day-section calendar-day-section-divider">
                  <div className="calendar-subhead">
                    <span className="calendar-subhead-left">
                      <span className="calendar-dot calendar-dot-note" aria-hidden="true" />
                      <StickyNote size={15} aria-hidden="true" />
                      <h3>{t.calendar.notesTitle}</h3>
                    </span>
                    <span className="calendar-count-badge">{selectedNotes.length}</span>
                  </div>

                  {selectedNotes.length === 0 ? (
                    <p className="calendar-empty-text">{t.calendar.notesEmpty}</p>
                  ) : (
                    <ul className="calendar-note-list">
                      {selectedNotes.map((note) => {
                        const isBusy = busyKey === `del-note-${note.id}`;
                        const timeStr = formatNoteTime(note.createdAt);
                        return (
                          <li key={note.id} className="calendar-note-item">
                            <div className="calendar-note-body">
                              <p className="calendar-note-text">{note.text}</p>
                              {timeStr && <span className="calendar-note-time">{timeStr}</span>}
                            </div>
                            <button
                              type="button"
                              className="row-delete-btn"
                              disabled={isBusy}
                              onClick={() => void handleDeleteNote(note.id)}
                              aria-label={t.calendar.deleteNote}
                              title={t.calendar.deleteNote}
                            >
                              <Trash2 size={14} />
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  )}

                  <form className="calendar-note-form" onSubmit={(e) => void handleAddNote(e)}>
                    <textarea
                      className="calendar-textarea"
                      rows={2}
                      value={newNoteText}
                      onChange={(e) => setNewNoteText(e.target.value)}
                      placeholder={t.calendar.notePlaceholder}
                      disabled={busyKey === 'add-note'}
                    />
                    <button
                      type="submit"
                      className="secondary-btn calendar-note-submit"
                      disabled={!newNoteText.trim() || busyKey === 'add-note'}
                    >
                      <Plus size={14} />
                      <span>{t.calendar.addNote}</span>
                    </button>
                  </form>
                </div>
              </section>
            </aside>
          </div>

          {/* BOTTOM: Monthly Suggestions */}
          <section className="card calendar-suggestions-card" aria-labelledby="calendar-suggestions-heading">
            <div className="calendar-panel-head">
              <div className="calendar-panel-title-row">
                <Lightbulb size={18} className="panel-accent-icon" aria-hidden="true" />
                <h2 id="calendar-suggestions-heading" className="panel-section-title">
                  {t.calendar.suggestionsTitle} — {t.calendar.months[monthIndex]}
                </h2>
              </div>
              <span className="calendar-count-badge">{activeMonth.suggestions.length}</span>
            </div>

            {activeMonth.suggestions.length === 0 ? (
              <p className="calendar-empty-text">{t.calendar.suggestionsEmpty}</p>
            ) : (
              <div className="calendar-suggestions-grid">
                {activeMonth.suggestions.map((suggestion) => {
                  const alreadyOnDay = assignedSuggestionIds.has(suggestion.id);
                  const isAdding = busyKey === `sug-${suggestion.id}`;
                  return (
                    <div key={suggestion.id} className="calendar-suggestion-item">
                      <p className="calendar-suggestion-text">{suggestion.text}</p>
                      <button
                        type="button"
                        className={`calendar-suggestion-btn${alreadyOnDay ? ' is-assigned' : ''}`}
                        disabled={alreadyOnDay || Boolean(busyKey)}
                        onClick={() => void handleAssignSuggestion(suggestion.id, suggestion.text)}
                      >
                        {alreadyOnDay ? (
                          <>
                            <Check size={14} />
                            <span>{t.calendar.assignedBadge} ({shortSelectedDayLabel})</span>
                          </>
                        ) : (
                          <>
                            {isAdding ? <Loader2 size={14} className="spin-icon" /> : <Plus size={14} />}
                            <span>{t.calendar.assignToDay} {shortSelectedDayLabel}</span>
                          </>
                        )}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
