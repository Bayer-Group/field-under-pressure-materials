import { getCropRisk, getCropRiskUnits, type PlotCropRisk, type RiskUnitRef } from '../../api'
import { Choice } from '../../Choice'
import { formatDate } from '../../format'
import { useState } from 'react'
import { navigate, planHref, riskHref } from '../../router'
import { useFetch } from '../../useFetch'
import { Breakdown } from './Breakdown'
import { FollowupTests } from './FollowupTests'
import { Heatmap, type Selection } from './Heatmap'
import { compact } from './labels'
import { SkippedList } from './SkippedList'

const good = (u: RiskUnitRef) => u.method === 'current' && !u.low_depth
/** The unit shown when the route names none: the first well-sequenced one of the current method, else the first. */
export const defaultUnit = (list: RiskUnitRef[]) => list.find(good) ?? list[0]
/** The unit to open when switching to `year`. */
export const pickInYear = (list: RiskUnitRef[], year: number) => {
  const inYear = list.filter((u) => u.year === year)
  return inYear.find(good) ?? inYear.find((u) => u.method === 'current') ?? inYear[0]
}
const dates = (ds: string[]) => (ds.length ? ds.map((d) => formatDate(d)).join(', ') : 'unknown date')

function Details({ data }: { data: PlotCropRisk }) {
  return (
    <details className="risk-about">
      <summary>About this score and its data</summary>
      <ul className="notes">
        {data.caveats.map((c) => <li key={c}>{c}</li>)}
        {data.notes.map((n) => <li key={n}>{n}</li>)}
        {data.kb.map((k) => (
          <li key={k.name}>
            Knowledge: {k.name}{k.source_version ? ` ${k.source_version}` : ''}
            {k.retrieved_utc ? ` (retrieved ${formatDate(k.retrieved_utc.slice(0, 10))})` : ''}
          </li>
        ))}
      </ul>
      <SkippedList groups={data.skipped} />
    </details>
  )
}

/** Crop disease risk of one plot: for each crop, how this plot's soil fungi rank against the other plots of the
 *  same site, year and sequencing method. The chosen unit and crop are in the URL. */
export function RiskPanel({ plotId, unit, crop }: { plotId: string; unit: string | null; crop: string | null }) {
  const units = useFetch(`risk-units:${plotId}`, (s) => getCropRiskUnits(plotId, s))
  const list = units.data ?? []
  const current = list.find((u) => u.unit === unit) ?? (unit ? undefined : defaultUnit(list))
  const risk = useFetch(current ? `${plotId}|${current.unit}` : null, (s) => getCropRisk(plotId, current!.unit, s))
  // A cell picked on another plot (or on this one) lives here; it is dropped when the plot or unit changes.
  const [picked, setPicked] = useState<(Selection & { key: string }) | null>(null)
  const [across, setAcross] = useState(false)

  if (units.error) return <p className="message error">Could not load crop risk data: {units.error}</p>
  if (units.loading) return <p className="message">Loading…</p>
  if (list.length === 0) return <p className="message">No fungal DNA data for this plot, so no crop risk can be computed.</p>
  if (!current) {
    return <p className="message">Unit {unit} was not found for this plot. <a href={riskHref(plotId)}>Show the default</a></p>
  }

  const go = (u: RiskUnitRef) => navigate(riskHref(plotId, u.unit))
  const years = [...new Set(list.map((u) => u.year))]
  const sameYear = list.filter((u) => u.year === current.year)
  const few = (u: RiskUnitRef) => u.low_depth && <span className="few"> · few reads</span>

  return (
    <div className="risk">
      <div className="controls">
        <Choice label="Year">
          {years.map((y) => (
            <button key={y} aria-pressed={current.year === y} onClick={() => go(pickInYear(list, y))}>
              {y}{few(pickInYear(list, y))}
            </button>
          ))}
        </Choice>
        {sameYear.length > 1 && (
          <Choice label="Sequencing method">
            {sameYear.map((u) => (
              <button key={u.unit} aria-pressed={u.unit === current.unit} onClick={() => go(u)}>
                {u.method === 'current' ? 'Current method (.002)' : 'Older method (.001)'}{few(u)}
              </button>
            ))}
          </Choice>
        )}
      </div>
      <div className="chart-head">
        <h2>Sampled {dates(current.collect_dates)}</h2>
        <span className="legend">
          {compact.format(current.total_reads)} DNA reads · {current.n_cores} soil {current.n_cores === 1 ? 'core' : 'cores'} · {current.method_label}
        </span>
      </div>
      {risk.error ? (
        <p className="message error">Could not score the crops: {risk.error}</p>
      ) : !risk.data ? (
        <p className="message">Scoring…</p>
      ) : (
        <>
          <Body data={risk.data} plotId={plotId} unit={current.unit} crop={crop} across={across} setAcross={setAcross}
            picked={picked?.key === `${plotId}|${current.unit}` ? picked : null}
            pick={(s) => setPicked(s && { ...s, key: `${plotId}|${current.unit}` })} />
        </>
      )}
    </div>
  )
}

function Body({ data, plotId, unit, crop, across, setAcross, picked, pick }: {
  data: PlotCropRisk; plotId: string; unit: string; crop: string | null; across: boolean; setAcross: (v: boolean) => void
  picked: Selection | null; pick: (s: Selection | null) => void
}) {
  const valid = (c: string | null) => (c !== null && data.crops.some((r) => r.crop === c) ? c : null)
  const best = data.crops.filter((r) => r.rank !== null).reduce<typeof data.crops[number] | null>(
    (b, r) => (b === null || r.rank! < b.rank! ? r : b), null)
  const fallback = valid(crop) ?? best?.crop ?? data.crops[0]?.crop
  const sel: Selection | null = picked ?? (fallback ? { plot: plotId, crop: fallback } : null)
  const onSelect = (s: Selection) => {
    if (s.plot === plotId) {
      pick(null)
      navigate(riskHref(plotId, unit, s.crop))
    } else pick(s)
  }
  return (
    <>
      <p className="risk-note">
        Each cell is the crop risk index of a plot. Shading compares plots within each crop (darkest = highest for that crop).
        Relative index, not a probability of disease.
        {data.notes.filter((n) => n.startsWith('Light mode')).map((n) => <strong key={n}> {n}</strong>)}
      </p>
      <Choice label="Shading">
        <button aria-pressed={!across} onClick={() => setAcross(false)}>Shade within each crop</button>
        <button aria-pressed={across} onClick={() => setAcross(true)}>Shade across all crops</button>
      </Choice>
      {sel && (
        <>
          <Heatmap rows={data.crops} plotId={plotId} unit={unit} selected={sel} across={across} nUnits={data.n_units_in_group} onSelect={onSelect} />
          <Breakdown plot={sel.plot} unit={unit} crop={sel.crop} />
          <FollowupTests plot={sel.plot} unit={unit} crop={sel.crop} crops={data.crops}
            onCrop={(c) => onSelect({ plot: sel.plot, crop: c })} />
          <p className="risk-note"><a href={planHref(sel.plot, unit, sel.crop)}>Products to consider for this crop on {sel.plot}</a></p>
        </>
      )}
      <Details data={data} />
    </>
  )
}
