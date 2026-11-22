import { useOrchard } from '../../contexts/OrchardContext';
import { Activity, CloudSun, Download, Droplets, FlaskConical, Layers3, Leaf, LoaderCircle, Sun, TreeDeciduous } from 'lucide-react';
import { lazy, Suspense, useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import {
  fetchAnalystField, fetchAnalystFields, fetchAnalystForecast, fetchAnalystRaster, fetchFieldJob, RASTER_KINDS, startFieldJob,
  type AnalysisTree, type AnalystField, type AnalystFieldOption, type FieldJob, type RasterKind, type Risk, type RiskStatus,
} from '../../api/analyticsApi';
import { ApiError } from '../../api/httpClient';
import { useLanguage } from '../../contexts/LanguageContext';
import { analyticsCopy, USDA_TEXTURE } from '../../i18n/analytics';
import { readPagePref, writePagePref } from '../../utils/pagePrefs';
import { Dropdown } from '../common/Dropdown';
import { SoilMoisturePage } from './SoilMoisturePage';

const FieldMap = lazy(() => import('./SoilRasterMap'));
const FORECAST_DAYS_AHEAD = 3;
const TREE_ORDER: RiskStatus[] = ['high', 'watch', 'low', 'insufficient'];
const FORECAST_FOCUS: LayerFocus = { kind: 'moisture' };

function localForecastDates() {
  const parts = new Intl.DateTimeFormat('pl-PL', {
    timeZone: 'Europe/Warsaw', year: 'numeric', month: 'numeric', day: 'numeric',
  }).formatToParts(new Date());
  const number = (name: string) => Number(parts.find((part) => part.type === name)?.value);
  return Array.from({ length: FORECAST_DAYS_AHEAD + 1 }, (_, offset) =>
    new Date(Date.UTC(number('year'), number('month') - 1, number('day') + offset)).toISOString().slice(0, 10));
}

function useCopy() {
  const { language } = useLanguage();
  return { copy: analyticsCopy[language], language };
}

function rasterLabel(copy: ReturnType<typeof useCopy>['copy'], kind: RasterKind) {
  return kind === 'moisture' ? copy.soilMoisture : copy[kind];
}

function treeSlotLabel(tree: AnalysisTree) {
  return tree.rowLabel && tree.indexInRow != null ? `${tree.rowLabel} · #${tree.indexInRow}` : tree.id.slice(-6);
}

function RiskBadge({ status }: { status: RiskStatus }) {
  const { copy } = useCopy();
  return <span className="analytics-badge" data-risk={status}>{copy.statuses[status]}</span>;
}

function ScoreCard({ risk, trees, metrics }: { risk: Risk; trees: AnalysisTree[]; metrics: AnalystField['metrics'] }) {
  const { copy, language } = useCopy();
  const number = new Intl.NumberFormat(language, { maximumFractionDigits: 2 });
  const ph = metrics.ph?.mean;
  const texture = metrics.texture?.dominant_class;
  const soilReadings = { ph: ph == null ? null : number.format(ph), texture: texture == null ? null : `${USDA_TEXTURE[texture - 1] ?? 'USDA'} · ${texture}` };
  const assessed = trees.filter((tree) => tree.risk.score !== null).length;
  const high = trees.filter((tree) => tree.risk.status === 'high').length;
  return (
    <div className="analytics-score-grid">
      <section className="card analytics-score" data-risk={risk.status} aria-labelledby="analytics-risk">
        <div className="analytics-row analytics-spread">
          <div className="analytics-row"><Activity size={20} aria-hidden="true" /><h2 id="analytics-risk">{copy.risk}</h2></div>
          <RiskBadge status={risk.status} />
        </div>
        <div className="analytics-score-value">{risk.score ?? '—'} <small>/ 100</small></div>
        <div className="analytics-risk-meter" role="progressbar" aria-label={copy.risk} aria-valuemin={0} aria-valuemax={100} aria-valuenow={risk.score ?? undefined}>
          {risk.score !== null && <span style={{ left: `${risk.score}%` }} />}
        </div>
        <div className="analytics-score-caption"><span>{copy.method}</span><span>{copy.threshold}</span></div>
        <div className="analytics-score-footer">
          <div><span>{copy.coverage}</span><strong>{risk.coverage}% <small>min. {risk.min_coverage}%</small></strong></div>
          <div><span>{copy.treeExposure}</span><strong>{assessed ? `${high} / ${assessed}` : '—'} <small>{assessed ? copy.evaluated : ''}</small></strong></div>
        </div>
      </section>
      <section className="card analytics-factors" aria-labelledby="analytics-factors">
        <h2 id="analytics-factors">{copy.factors}</h2>
        <div className="analytics-factor-list">
          {risk.factors.map((factor) => {
            const measurement = factor.id === 'ph' || factor.id === 'texture' ? soilReadings[factor.id] : null;
            return (
              <div key={factor.id} className="analytics-factor">
                <span>{factor.id === 'temperature' ? copy.weather : copy.weights[factor.id]}{measurement != null &&
                  <small className="analytics-factor-reading">{measurement}{factor.severity == null && ` · ${copy.noSpeciesRange}`}</small>}</span>
                <span className="analytics-weight">{factor.weight}%</span>
                <span className="analytics-factor-track" data-missing={factor.severity === null}>
                  <span style={{ width: `${factor.severity ?? 0}%` }} />
                </span>
                <strong>{factor.severity ?? '—'}</strong>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function MetricCard({ title, icon, value, detail, tone }: { title: string; icon: ReactNode; value: string; detail?: string; tone?: string }) {
  return (
    <section className="card analytics-metric" data-tone={tone}>
      <div className="analytics-row">{icon}<h3>{title}</h3></div>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </section>
  );
}

function Metrics({ metrics, forecast }: { metrics: AnalystField['metrics']; forecast: boolean }) {
  const { copy, language } = useCopy();
  const format = new Intl.NumberFormat(language, { maximumFractionDigits: 2 });
  const percent = new Intl.NumberFormat(language, { style: 'percent', maximumFractionDigits: 1 });
  const moisture = metrics.moisture?.mean_m3_m3;
  const ndvi = metrics.ndvi?.mean;
  const ph = metrics.ph?.mean;
  const texture = metrics.texture?.dominant_class;
  const solar = metrics.solar;
  const temperature = metrics.weather?.mean_temperature_c;
  const rain = metrics.weather?.precipitation_mm;
  const et0 = metrics.weather?.reference_et0_mm;
  const humidity = metrics.weather?.mean_humidity_percent;
  const wind = metrics.weather?.mean_wind_km_h;
  const cloud = metrics.weather?.mean_cloud_percent;
  const acquired = metrics.moisture?.acquired_at_utc?.slice(0, 10);
  const detail = (pixels?: number, depth?: number | null) =>
    [pixels == null ? '' : `${pixels} ${copy.soilPixels}`, depth == null ? '' : `${depth} cm`].filter(Boolean).join(' · ');
  return (
    <div className="analytics-metrics">
      <MetricCard title={forecast ? copy.forecastMoisture : copy.soilMoisture} icon={<Droplets size={17} />} tone="water"
        value={moisture == null ? '—' : percent.format(moisture)}
        detail={forecast ? [copy.endOfDay, detail(metrics.moisture?.valid_pixels)].filter(Boolean).join(' · ') : metrics.forecast_min_m3_m3 == null ? [acquired, detail(metrics.moisture?.valid_pixels)].filter(Boolean).join(' · ') :
          `${copy.forecastMin} ${percent.format(metrics.forecast_min_m3_m3)}`} />
      <MetricCard title={copy.ndvi} icon={<Leaf size={17} />} tone="ndvi" value={ndvi == null ? '—' : format.format(ndvi)}
        detail={detail(metrics.ndvi?.valid_pixels)} />
      <MetricCard title={copy.ph} icon={<FlaskConical size={17} />} tone="soil" value={ph == null ? '—' : format.format(ph)}
        detail={detail(metrics.ph?.valid_pixels, metrics.ph?.depth_cm)} />
      <MetricCard title={copy.texture} icon={<Layers3 size={17} />} tone="soil"
        value={texture == null ? '—' : `${USDA_TEXTURE[texture - 1] ?? 'USDA'} · ${texture}`}
        detail={detail(metrics.texture?.valid_pixels, metrics.texture?.depth_cm)} />
      <MetricCard title={copy.solar} icon={<Sun size={17} />} tone={solar?.level ?? 'solar'}
        value={solar?.level ? copy.solarLevels[solar.level] : '—'}
        detail={[solar?.date_local, solar?.clear_sky_fraction == null ? '' : percent.format(solar.clear_sky_fraction)].filter(Boolean).join(' · ')} />
      <MetricCard title={copy.weather} icon={<CloudSun size={17} />} value={temperature == null ? '—' : `${format.format(temperature)} °C`}
        detail={[
          rain == null ? '' : `${copy.rain} ${format.format(rain)} mm`,
          et0 == null ? '' : `${copy.et0} ${format.format(et0)} mm`,
          humidity == null ? '' : `${copy.humidity} ${format.format(humidity)}%`,
          wind == null ? '' : `${copy.wind} ${format.format(wind)} km/h`,
          cloud == null ? '' : `${copy.cloud} ${format.format(cloud)}%`,
        ].filter(Boolean).join(' · ')} />
    </div>
  );
}

type LayerFocus = { kind: RasterKind };

function FieldMapSection({ field, selected, onSelectTree, focus }: { field: AnalystField; selected: string; onSelectTree: (id: string) => void; focus: LayerFocus | null }) {
  const { copy, language } = useCopy();
  const { t } = useLanguage();
  const [kind, setKind] = useState<RasterKind>(() => {
    const saved = readPagePref<string>('analytics.mapKind', '');
    if (RASTER_KINDS.includes(saved as RasterKind)) return saved as RasterKind;
    return focus?.kind ?? RASTER_KINDS.find((layer) => field.metrics[layer]?.raster) ?? 'moisture';
  });
  const handleSelectKind = (nextKind: RasterKind) => {
    setKind(nextKind);
    writePagePref('analytics.mapKind', nextKind);
  };
  const [uploads, setUploads] = useState<Partial<Record<RasterKind, File>>>({});
  const [downloads, setDownloads] = useState<Partial<Record<RasterKind, File>>>({});
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle');
  const [resetMap, setResetMap] = useState<(() => void) | null>(null);
  const handleResetReady = useCallback((fn: (() => void) | null) => {
    setResetMap(() => fn);
  }, []);
  const filename = field.metrics[kind]?.raster;
  const day = field.forecast_day;
  const manual = uploads[kind];
  const remote = downloads[kind];
  const file = manual ?? (remote?.name === filename ? remote ?? null : null);
  const tree = field.trees.find((entry) => entry.id === selected);

  useEffect(() => {
    if (!focus) return;
    setKind(focus.kind);
    setUploads((previous) => ({ ...previous, [focus.kind]: undefined }));
  }, [focus]);

  useEffect(() => {
    if (!filename || file) { setStatus('idle'); return; }
    const controller = new AbortController();
    setStatus('loading');
    void fetchAnalystRaster(field.id, kind, filename, controller.signal, day).then((result) => {
      if (controller.signal.aborted) return;
      setDownloads((previous) => ({ ...previous, [kind]: result }));
      setStatus('idle');
    }).catch(() => {
      if (!controller.signal.aborted) setStatus('error');
    });
    return () => controller.abort();
  }, [filename, field.id, kind, file, day]);

  return (
    <section className="card analytics-map-panel" aria-labelledby="analytics-map-heading">
      <div className="analytics-map-header">
        <h2 id="analytics-map-heading">{copy.cultivation} - {copy.risk}</h2>
        <div className="analytics-map-actions">
          <div className="analytics-segment">
            {RASTER_KINDS.map((layer) => (
              <button key={layer} type="button" aria-pressed={kind === layer} onClick={() => handleSelectKind(layer)}>
                {layer === 'moisture' && day ? copy.forecastMoisture : rasterLabel(copy, layer)}
              </button>
            ))}
          </div>
          <label className="analytics-upload">
            <span>{copy.upload}</span>
            <input type="file" accept=".tif,.tiff,image/tiff" aria-label={copy.upload} onChange={(event) => {
              const selected = event.currentTarget.files?.[0];
              if (selected) setUploads((previous) => ({ ...previous, [kind]: selected }));
              event.currentTarget.value = '';
            }} />
          </label>
          <button type="button" className="soil-map-reset" onClick={() => resetMap?.()} disabled={!resetMap}>
            {t.soilMoisture.raster.reset}
          </button>
        </div>
      </div>
      {status !== 'idle' && <p className="analytics-muted" role="status">{status === 'loading' ? copy.rasterLoading : copy.rasterError}</p>}
      {status === 'idle' && !file && !filename && <p className="analytics-muted">{copy.rasterEmpty}</p>}
      <Suspense fallback={<p role="status" className="analytics-muted">{copy.loading}</p>}>
        <FieldMap kind={kind} file={file} field={field} selectedTreeId={selected} onSelectTree={onSelectTree} colorBy="risk" hideResetBar onResetReady={handleResetReady} />
      </Suspense>
      <div className="analytics-tree-legend" aria-label={copy.legend}>
        {TREE_ORDER.map((status) => <span key={status} data-risk={status}>{copy.statuses[status]}</span>)}
      </div>
      {tree && <div className="analytics-tree-selection" aria-live="polite">
        <strong>{tree.species ?? copy.tree} · {treeSlotLabel(tree)}</strong><RiskBadge status={tree.risk.status} />
        <span>{tree.healthStatus ? `${t.health.statuses[tree.healthStatus]} (${tree.healthScore}/100)` : t.health.statuses.unrated}</span>
        {tree.healthSource === 'estimate' && <span>{language === 'pl' ? 'Szacunek ML' : 'ML estimate'} · {tree.healthCoverage}%</span>}
      </div>}
    </section>
  );
}

function TreePixelDetails({ tree }: { tree: AnalysisTree }) {
  const { copy, language } = useCopy();
  const analysis = tree.pixel_analysis;
  const number = new Intl.NumberFormat(language, { maximumFractionDigits: 3 });
  const percent = new Intl.NumberFormat(language, { style: 'percent', maximumFractionDigits: 1 });
  const pixel = analysis.pixel;
  return (
    <div className="analytics-pixel-details" aria-live="polite">
      <p>
        {analysis.status ? copy.sampleStatuses[analysis.status] : copy.noSample}
        {pixel?.row != null && pixel.column != null &&
          <> · {copy.treePixel} · {copy.row} {pixel.row}, {copy.column} {pixel.column}</>}
      </p>
      <dl>
        <div><dt>{copy.soilMoisture}</dt><dd>{analysis.moisture_m3_m3 == null ? '—' : percent.format(analysis.moisture_m3_m3)}</dd></div>
        <div><dt>{copy.ndvi}</dt><dd>{analysis.ndvi == null ? '—' : number.format(analysis.ndvi)}</dd></div>
        <div><dt>{copy.ph}</dt><dd>{analysis.ph == null ? '—' : number.format(analysis.ph)}</dd></div>
        <div><dt>{copy.texture}</dt><dd>{analysis.texture == null ? '—' : USDA_TEXTURE[analysis.texture - 1] ?? analysis.texture}</dd></div>
        <div><dt>{copy.solar}</dt><dd>{analysis.solar ? copy.solarLevels[analysis.solar] : '—'}</dd></div>
      </dl>
    </div>
  );
}

function TreeTable({ trees, selected, onSelect }: { trees: AnalysisTree[]; selected: string; onSelect: (id: string) => void }) {
  const { copy } = useCopy();
  const { t } = useLanguage();
  const [filter, setFilter] = useState<RiskStatus | 'all'>(() => {
    const saved = readPagePref<string>('analytics.treeFilter', 'all');
    return saved === 'all' || TREE_ORDER.includes(saved as RiskStatus) ? (saved as RiskStatus | 'all') : 'all';
  });
  useEffect(() => {
    writePagePref('analytics.treeFilter', filter);
  }, [filter]);
  const displayed = trees.filter((tree) => filter === 'all' || tree.risk.status === filter)
    .sort((a, b) => (b.risk.score ?? -1) - (a.risk.score ?? -1));
  const highlighted = trees.find((tree) => tree.id === selected);
  return (
    <section className="card analytics-tree-panel" aria-labelledby="analytics-trees">
      <div className="analytics-row analytics-spread">
        <div className="analytics-row"><TreeDeciduous size={19} aria-hidden="true" /><h2 id="analytics-trees">{copy.riskTrees}</h2></div>
        <div className="soil-input">
          <span>{copy.filter}</span>
          <Dropdown
            value={filter}
            onChange={(nextValue) => setFilter(nextValue as RiskStatus | 'all')}
            ariaLabel={copy.filter}
            options={[
              { value: 'all', label: copy.allTrees },
              ...TREE_ORDER.map((status) => ({ value: status, label: copy.statuses[status] })),
            ]}
          />
        </div>
      </div>
      {highlighted ? (
        <>
          <div className="analytics-tree-selection">
            <strong>{highlighted.species ?? copy.tree} · {treeSlotLabel(highlighted)}</strong>
            <RiskBadge status={highlighted.risk.status} />
          </div>
          <TreePixelDetails tree={highlighted} />
        </>
      ) : !!trees.length && <p className="analytics-muted">{copy.scan}</p>}
      {!displayed.length ? <p className="analytics-muted">{trees.length ? copy.noTrees : copy.noAssignedTrees}</p> : (
        <div className="soil-table-scroll">
          <table className="soil-table">
            <thead><tr><th>{copy.tree} ({t.orchard3d.inspectorRow})</th><th>{copy.species}</th><th>{copy.status}</th><th>{copy.drivers}</th></tr></thead>
            <tbody>{displayed.map((tree) => {
              const signals = tree.risk.factors.filter((factor) => (factor.severity ?? 0) >= 30)
                .sort((a, b) => b.severity! * b.weight - a.severity! * a.weight)
                .slice(0, 3).map((factor) => copy.weights[factor.id]).join(', ');
              return (
                <tr key={tree.id} data-selected={selected === tree.id}>
                  <th scope="row"><button type="button" aria-pressed={selected === tree.id} onClick={() => onSelect(tree.id)}>{treeSlotLabel(tree)}</button></th>
                  <td>{tree.species ?? '—'}</td>
                  <td><RiskBadge status={tree.risk.status} /> <strong>{tree.risk.score ?? '—'}</strong></td>
                  <td>{signals || '—'}</td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      )}
    </section>
  );
}

type FieldLoad =
  | { fieldId: string; state: 'starting' | 'loading' }
  | { fieldId: string; state: 'processing'; job: FieldJob }
  | { fieldId: string; state: 'error'; detail: string; job?: FieldJob }
  | { fieldId: string; state: 'ready'; job: FieldJob | null };

function waitForStatus(signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    function finish() {
      window.clearTimeout(timer);
      signal.removeEventListener('abort', finish);
      resolve();
    }
    const timer = window.setTimeout(finish, 3_000);
    signal.addEventListener('abort', finish, { once: true });
    if (signal.aborted) finish();
  });
}

export function AnalyticsPage({ active }: { active: boolean }) {
  const { copy, language } = useCopy();
  const [fields, setFields] = useState<AnalystFieldOption[]>([]);
  const { selectedOrchardId: fieldId } = useOrchard();
  const [fieldLoad, setFieldLoad] = useState<FieldLoad | null>(null);
  const [viewer, setViewer] = useState<{ field: AnalystField; focus: LayerFocus | null } | null>(null);
  const [day, setDay] = useState(() => {
    const saved = readPagePref<string>('analytics.day', '');
    return saved === '' || localForecastDates().includes(saved) ? saved : '';
  });
  useEffect(() => {
    writePagePref('analytics.day', day);
  }, [day]);
  const [forecastRefresh, setForecastRefresh] = useState(0);
  const [forecastLoad, setForecastLoad] = useState<{ key: string; field?: AnalystField; error?: string } | null>(null);
  const [tree, setTree] = useState('');
  const [catalog, setCatalog] = useState<'loading' | 'ready' | 'error'>('loading');
  const [jobsOpened, setJobsOpened] = useState(false);
  const pending = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    setCatalog('loading');
    void fetchAnalystFields(controller.signal).then((data) => {
      if (controller.signal.aborted) return;
      setFields(data);
      setCatalog('ready');
    }).catch(() => {
      if (!controller.signal.aborted) setCatalog('error');
    });
    return () => controller.abort();
  }, [active]);

  const watchField = useCallback(async (identity: string, start: boolean) => {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    const { signal } = controller;
    if (start) {
      setTree('');
      setFieldLoad({ fieldId: identity, state: 'starting' });
    }
    try {
      let job = start ? await startFieldJob(identity, signal) : await fetchFieldJob(identity, signal);
      let published = '';
      while (!signal.aborted) {
        const ready = job?.ready_layers ?? [];
        const revision = `${job?.id ?? ''}:${ready.join(',')}`;
        const initialCompleted = published === '' && job?.state === 'completed';
        const preferred = initialCompleted && ready.includes('moisture') ? 'moisture' : ready[ready.length - 1];
        const latestLayer = revision !== published ? preferred : undefined;
        const failed = job?.state === 'failed';
        const finished = !job || job.state === 'completed' || failed;
        if (job && !finished) {
          setFieldLoad({ fieldId: identity, state: 'processing', job });
        } else if (!failed) {
          setFieldLoad({ fieldId: identity, state: 'loading' });
        }
        if (latestLayer || finished) {
          const field = await fetchAnalystField(identity, signal);
          if (signal.aborted) return;
          setViewer((previous) => ({
            field,
            focus: latestLayer ? { kind: latestLayer } : previous?.field.id === identity ? previous.focus : null,
          }));
          published = revision;
        }
        if (finished) {
          if (job?.state === 'failed') setFieldLoad({ fieldId: identity, state: 'error', detail: job.error ?? '', job });
          else setFieldLoad({ fieldId: identity, state: 'ready', job });
          return;
        }
        await waitForStatus(signal);
        if (signal.aborted) return;
        job = await fetchFieldJob(identity, signal);
      }
    } catch (error) {
      if (!signal.aborted) {
        setFieldLoad({ fieldId: identity, state: 'error', detail: error instanceof ApiError ? error.message : '' });
      }
    } finally {
      if (pending.current === controller) pending.current = null;
    }
  }, []);

  useEffect(() => {
    if (active && fieldId) void watchField(fieldId, false);
    return () => pending.current?.abort();
  }, [active, fieldId, watchField]);

  const dates = localForecastDates();
  const dayFormat = new Intl.DateTimeFormat(language, { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
  const rawView = viewer?.field.id === fieldId ? viewer : null;
  const baseline = rawView?.field.metrics.moisture?.raster ?? '';
  const forecastKey = JSON.stringify([fieldId, day, forecastRefresh, baseline]);

  useEffect(() => {
    if (!active || !fieldId || !day) return;
    const controller = new AbortController();
    const { signal } = controller;
    void fetchAnalystForecast(fieldId, day, signal).then((field) => {
      if (!signal.aborted) setForecastLoad({ key: forecastKey, field });
    }).catch((error) => {
      if (!signal.aborted) setForecastLoad({ key: forecastKey, error: error instanceof ApiError ? error.message : copy.fieldError });
    });
    return () => controller.abort();
  }, [active, fieldId, day, forecastKey, copy.fieldError]);

  const current = fieldLoad?.fieldId === fieldId ? fieldLoad : null;
  const dated = forecastLoad?.key === forecastKey ? forecastLoad : null;
  const visible = day ? (dated?.field ? { field: dated.field, focus: FORECAST_FOCUS } : null) : rawView;
  const visibleField = visible?.field;
  const projected = visibleField?.forecast_day;
  const loading = current?.state === 'starting' || current?.state === 'processing' || current?.state === 'loading';
  const forecastLoading = !!(fieldId && day && !dated);
  const busy = day ? forecastLoading : loading;
  const running = current?.state === 'processing' ? current.job : null;
  const job = current && 'job' in current ? current.job : null;
  const available = job?.ready_layers ?? [];
  const layerErrors = Object.entries(job?.layer_errors ?? {}) as [RasterKind, string][];
  const stage = running?.state;
  const stageText = stage && stage !== 'completed' && stage !== 'failed' ? copy.jobStages[stage] : null;
  const moistureExport = running?.export_status?.moisture;
  const moistureAttempt = moistureExport && ['READY', 'RUNNING'].includes(moistureExport.state)
    ? ` · ${copy.soilMoisture} (${copy.exportAttempt} ${moistureExport.attempt ?? 1})` : '';

  function loadField(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!fieldId || busy) return;
    if (day) setForecastRefresh((value) => value + 1);
    else void watchField(fieldId, true);
  }

  return (
    <div className="dashboard-page analytics-page">
      <div className="analytics-intro">
        <h1 className="page-title">{copy.title}</h1>
      </div>
      <form className="card analytics-toolbar" onSubmit={loadField} aria-describedby="analytics-field-status">
        <div className="soil-input">
          <span>{copy.analysisDate}</span>
          <Dropdown
            value={day}
            onChange={setDay}
            ariaLabel={copy.analysisDate}
            options={[
              { value: '', label: copy.satelliteObservation },
              ...dates.map((date, offset) => ({
                value: date,
                label: `${offset ? `+${offset} · ` : `${copy.today} · `}${dayFormat.format(new Date(date))}`,
              })),
            ]}
          />
        </div>
        <button type="submit" className="primary-btn soil-action analytics-load" disabled={!fieldId || busy}>
          {busy ? <LoaderCircle size={16} className="analytics-spinner" aria-hidden="true" /> : <Download size={16} aria-hidden="true" />}
          {day ? (forecastLoading ? copy.forecastLoading : copy.loadForecast) : loading ? copy.downloadingField : copy.loadField}
        </button>
        <p id="analytics-field-status" role="status" className="analytics-muted analytics-field-status">
          {day ? (forecastLoading ? copy.forecastLoading : projected ? `${copy.forecastFor} ${projected.date_local}` : '') :
            stageText ? `${stageText}${running && available.length ? ` · ${copy.readyLayers} ${available.length}/${running.total}` : ''}${moistureAttempt}` :
            current?.state === 'starting' ? copy.startingJob : loading ? copy.fieldLoading : visibleField ? copy.fieldLoaded :
            catalog === 'loading' ? copy.catalogLoading : catalog === 'ready' && !fields.length ? copy.noFields : ''}
        </p>
      </form>
      {catalog === 'error' && <p role="alert" className="card analytics-muted">{copy.connection}</p>}
      {(day ? dated?.error : current?.state === 'error') && <p role="alert" className="card analytics-muted">
        {day ? dated?.error : current?.state === 'error' ? current.detail || copy.fieldError : ''}
      </p>}
      {!day && !!layerErrors.length && <details className="card analytics-jobs">
        <summary>{copy.layerErrors}</summary>
        <ul>{layerErrors.map(([kind, detail]) => <li key={kind}><strong>{rasterLabel(copy, kind)}</strong> · {detail}</li>)}</ul>
      </details>}
      {visibleField && (
          <>
            {!day && !!available.length && (loading || available.length < (job?.total ?? 0) || job?.state === 'failed') &&
              <p className="card analytics-muted" role="status">{copy.preview} {copy.readyLayers} · {available.map((kind) => rasterLabel(copy, kind)).join(', ')}</p>}
            {projected && <div className="card analytics-muted analytics-forecast-context">
              <p>{copy.forecastContext}{projected.anchor_at_utc && ` · ${copy.sarAnchor} ${projected.anchor_at_utc.slice(0, 10)}`}</p>
              {projected.moisture_status !== 'available' && <p role="status">{copy.moistureStatus[projected.moisture_status]}</p>}
              {!visibleField.metrics.weather && <p role="status">{copy.forecastWeatherMissing}</p>}
              {['missing_sar', 'stale_sar'].includes(projected.moisture_status) &&
                <button type="button" className="soil-map-reset" disabled={loading} onClick={() => void watchField(fieldId, true)}>
                  {loading ? copy.downloadingField : copy.loadField}
                </button>}
            </div>}
            <ScoreCard risk={visibleField.risk} trees={visibleField.trees} metrics={visibleField.metrics} />
            <Metrics metrics={visibleField.metrics} forecast={!!projected} />
            <FieldMapSection key={`map-${fieldId}-${day}`} field={visibleField} selected={tree} onSelectTree={setTree} focus={visible.focus} />
            <TreeTable key={`trees-${fieldId}`} trees={visibleField.trees} selected={tree} onSelect={setTree} />
          </>
      )}
      <details className="card analytics-jobs" onToggle={(event) => { if (event.currentTarget.open) setJobsOpened(true); }}>
        <summary>{copy.jobs}</summary>
        {jobsOpened && <SoilMoisturePage key={fieldId} embedded />}
      </details>
    </div>
  );
}
