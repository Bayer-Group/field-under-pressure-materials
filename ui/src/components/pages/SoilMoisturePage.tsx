import { CalendarDays, Droplets } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError } from '../../api/httpClient';
import {
  fetchSoilMoistureForecast,
  fetchTaskStatus,
  partialSubmission,
  submitAnalysis,
  type AnalysisDates,
  type SoilMoistureForecast,
  type SoilMoistureTask,
  type SoilMoistureTaskStatus,
} from '../../api/soilMoistureApi';
import { useLanguage } from '../../contexts/LanguageContext';

const TERMINAL_STATES = new Set(['COMPLETED', 'FAILED', 'CANCELLED']);
const TASK_POLL_INTERVAL_MS = 5_000;

interface TrackedTask extends SoilMoistureTask {
  dates: AnalysisDates;
}

function ForecastPanel() {
  const { language, t: { soilMoisture: labels } } = useLanguage();
  const [forecast, setForecast] = useState<SoilMoistureForecast | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<AbortController | null>(null);

  useEffect(() => () => pending.current?.abort(), []);

  async function refreshForecast() {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    setError('');
    try {
      const result = await fetchSoilMoistureForecast(controller.signal);
      if (controller.signal.aborted) return;
      setForecast(result);
      setSelectedId((current) =>
        result.fields.some((field) => field.field_id === current)
          ? current
          : result.fields.find((field) => field.forecasts.length)?.field_id ?? result.fields[0]?.field_id ?? null,
      );
    } catch (problem) {
      if (!controller.signal.aborted) {
        setError(problem instanceof ApiError ? problem.message : labels.forecastError);
      }
    } finally {
      pending.current = null;
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  const timeFormat = new Intl.DateTimeFormat(language, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'Europe/Warsaw',
  });
  const percent = new Intl.NumberFormat(language, { style: 'percent', maximumFractionDigits: 1 });
  const millimetres = new Intl.NumberFormat(language, { maximumFractionDigits: 2 });
  const field = forecast?.fields.find((item) => item.field_id === selectedId);

  return (
    <section className="card soil-panel" aria-labelledby="soil-forecast-heading">
      <div className="card-header">
        <div className="card-title-row">
          <span className="card-icon"><Droplets size={18} aria-hidden="true" /></span>
          <div>
            <h2 className="card-title" id="soil-forecast-heading">{labels.forecastTitle}</h2>
            <p className="card-subtitle">{labels.forecastDescription}</p>
          </div>
        </div>
        <button type="button" className="primary-btn soil-action" onClick={refreshForecast} disabled={loading}>
          {labels.loadForecast}
        </button>
      </div>
      {loading && <p className="soil-feedback" role="status">{labels.loadingForecast}</p>}
      {error && <p className="soil-feedback soil-error" role="alert">{error}</p>}
      {forecast && (
        <>
          <dl className="soil-meta">
            <div><dt>{labels.sarDate}</dt><dd>{timeFormat.format(new Date(forecast.sar_acquired_at_utc))}</dd></div>
            <div><dt>{labels.nextOverpass}</dt><dd>{timeFormat.format(new Date(forecast.estimated_next_overpass_utc))}</dd></div>
            <div><dt>{labels.issuedAt}</dt><dd>{timeFormat.format(new Date(forecast.issued_at_utc))}</dd></div>
          </dl>
          {forecast.fields.length > 0 && (
            <label className="soil-input">
              <span>{labels.selectField}</span>
              <select value={selectedId ?? ''} onChange={(event) => setSelectedId(Number(event.target.value))}>
                {forecast.fields.map((item) => (
                  <option key={item.field_id} value={item.field_id}>{labels.field} {item.field_id}</option>
                ))}
              </select>
            </label>
          )}
          {field && field.sar_moisture_m3_m3 !== null && (
            <p className="soil-feedback">{labels.sarMoisture} <strong>{percent.format(field.sar_moisture_m3_m3)}</strong></p>
          )}
          {field?.forecasts.length ? (
            <div className="soil-table-scroll">
              <table className="soil-table" aria-label={labels.forecastTitle}>
                <thead>
                  <tr><th scope="col">{labels.forecastTime}</th><th scope="col">{labels.moisture}</th><th scope="col">{labels.rain}</th><th scope="col">{labels.et0}</th></tr>
                </thead>
                <tbody>
                  {field.forecasts.map((point) => (
                    <tr key={point.valid_at_utc}>
                      <th scope="row">{timeFormat.format(new Date(point.valid_at_utc))}</th>
                      <td><strong>{percent.format(point.moisture_m3_m3)}</strong></td>
                      <td>{millimetres.format(point.precipitation_mm)}</td>
                      <td>{millimetres.format(point.reference_et0_mm)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="soil-feedback">{labels.noForecast}</p>}
        </>
      )}
    </section>
  );
}

function AnalysisPanel() {
  const { t: { soilMoisture: labels } } = useLanguage();
  const [dates, setDates] = useState<AnalysisDates>({ start: '', test_start: '', end: '' });
  const [tasks, setTasks] = useState<TrackedTask[]>([]);
  const [statuses, setStatuses] = useState<Record<string, SoilMoistureTaskStatus>>({});
  const [statusError, setStatusError] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<AbortController | null>(null);

  useEffect(() => () => pending.current?.abort(), []);

  useEffect(() => {
    if (!tasks.length) return;
    const controller = new AbortController();
    const activeIds = new Set(tasks.map((task) => task.id));
    let timer: number | undefined;

    async function poll() {
      const results = await Promise.allSettled(
        [...activeIds].map((id) => fetchTaskStatus(id, controller.signal)),
      );
      if (controller.signal.aborted) return;

      const updates: Record<string, SoilMoistureTaskStatus> = {};
      for (const result of results) {
        if (result.status !== 'fulfilled') continue;
        const task = result.value;
        updates[task.id] = task;
        if (TERMINAL_STATES.has(task.state)) activeIds.delete(task.id);
      }
      setStatuses((previous) => ({ ...previous, ...updates }));
      setStatusError(results.some((result) => result.status === 'rejected'));
      if (activeIds.size) timer = window.setTimeout(poll, TASK_POLL_INTERVAL_MS);
    }

    void poll();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [tasks]);

  function rememberTasks(submitted: SoilMoistureTask[], submittedDates: AnalysisDates) {
    if (!submitted.length) return;
    setTasks((previous) => [
      ...submitted.map((task) => ({ ...task, dates: submittedDates })),
      ...previous.filter((task) => !submitted.some(({ id }) => task.id === id)),
    ]);
  }

  async function runAnalysis(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    if (!dates.start || !dates.test_start || !dates.end || dates.start >= dates.test_start || dates.test_start >= dates.end) {
      setError(labels.dateError);
      return;
    }

    const controller = new AbortController();
    pending.current = controller;
    setSubmitting(true);
    setError('');
    try {
      const submission = await submitAnalysis(dates, controller.signal);
      if (!controller.signal.aborted) rememberTasks(submission.tasks, submission.dates);
    } catch (problem) {
      if (!controller.signal.aborted) {
        rememberTasks(partialSubmission(problem), dates);
        const message = problem instanceof ApiError
          ? problem.message
          : problem instanceof Error && problem.name === 'TimeoutError'
            ? labels.submitTimeout
            : labels.submitError;
        setError(message);
      }
    } finally {
      pending.current = null;
      if (!controller.signal.aborted) setSubmitting(false);
    }
  }

  const dateFields = [
    { name: 'start', label: labels.start },
    { name: 'test_start', label: labels.testStart },
    { name: 'end', label: labels.end },
  ] as const;
  const completed = tasks.some((task) => statuses[task.id]?.state === 'COMPLETED');

  return (
    <section className="card soil-panel" aria-labelledby="soil-analysis-heading">
      <div className="card-title-row">
        <span className="card-icon"><CalendarDays size={18} aria-hidden="true" /></span>
        <div>
          <h2 className="card-title" id="soil-analysis-heading">{labels.analysisTitle}</h2>
          <p className="card-subtitle" id="soil-analysis-dates">{labels.analysisDescription}</p>
        </div>
      </div>
      <form className="soil-date-form" onSubmit={runAnalysis} aria-describedby="soil-analysis-dates">
        {dateFields.map(({ name, label }) => (
          <label key={name} className="soil-input">
            <span>{label}</span>
            <input
              name={name}
              type="date"
              value={dates[name]}
              onChange={(event) => {
                const value = event.target.value;
                setDates((previous) => ({ ...previous, [name]: value }));
              }}
              required
            />
          </label>
        ))}
        <button type="submit" className="primary-btn soil-action" disabled={submitting}>{labels.submit}</button>
      </form>
      {submitting && <p className="soil-feedback" role="status">{labels.submitting}</p>}
      {error && <p className="soil-feedback soil-error" role="alert">{error}</p>}
      {statusError && <p className="soil-feedback" role="status">{labels.statusError}</p>}
      {tasks.length > 0 && (
        <div className="soil-table-scroll">
          <table className="soil-table" aria-label={labels.analysisTitle}>
            <thead>
              <tr><th scope="col">{labels.exportLabel}</th><th scope="col">{labels.statusLabel}</th><th scope="col">{labels.taskId}</th></tr>
            </thead>
            <tbody>
              {tasks.map((task) => {
                const status = statuses[task.id];
                const state = status?.state ?? 'UNCONFIRMED';
                return (
                  <tr key={task.id}>
                    <th scope="row">
                      {labels.taskNames[task.name] ?? task.name}
                      <small>{task.dates.start} → {task.dates.end}</small>
                    </th>
                    <td>
                      <span className="soil-status" data-state={state}>{labels.states[state] ?? state}</span>
                      {status?.error && <small className="soil-error">{status.error}</small>}
                    </td>
                    <td><code>{task.id}</code></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {completed && (
        <a className="soil-drive-link" href="https://drive.google.com/drive/search?q=soil_moisture" target="_blank" rel="noreferrer">
          {labels.driveLabel}
        </a>
      )}
    </section>
  );
}

export function SoilMoisturePage() {
  const { t } = useLanguage();
  return (
    <div className="dashboard-page">
      <div className="page-intro">
        <div>
          <h1 className="page-title">{t.nav.analytics}</h1>
          <p className="page-subtitle">{t.soilMoisture.subtitle}</p>
        </div>
      </div>
      <ForecastPanel />
      <AnalysisPanel />
    </div>
  );
}
