import { getCropRisk, getCropRiskUnits, type PlotCropRisk, type RiskUnitRef } from '../../api'
import { Choice } from '../../Choice'
import { formatDate } from '../../format'
import { navigate, riskHref } from '../../router'
import { useFetch } from '../../useFetch'
import { ContributionsTable } from './ContributionsTable'
import { CropList } from './CropList'
import { compact } from './labels'
import { SkippedList } from './SkippedList'

const good = (u: RiskUnitRef) => u.method === 'current' && !u.low_depth
/** The unit shown when the route names none: the first well-sequenced one of the current method, else the first. */
const defaultUnit = (list: RiskUnitRef[]) => list.find(good) ?? list[0]
/** The unit to open when switching to `year`. */
const pickInYear = (list: RiskUnitRef[], year: number) => {
  const inYear = list.filter((u) => u.year === year)
  return inYear.find(good) ?? inYear.find((u) => u.method === 'current') ?? inYear[0]
}
const dates = (ds: string[]) => (ds.length ? ds.map((d) => formatDate(d)).join(', ') : 'unknown date')

function Notes({ data }: { data: PlotCropRisk }) {
  const others = Math.max(0, data.n_units_in_group - 1)
  const shallow = Math.max(0, ...data.crops.map((c) => c.n_peers_too_shallow))
  return (
    <ul className="notes">
      <li className="caution">
        Compare this plot with the other {others} {others === 1 ? 'plot' : 'plots'} of {data.site} sampled in {data.year} with
        the same sequencing method, for the same crop
        {shallow > 0 ? ` (${shallow} ${shallow === 1 ? 'plot' : 'plots'} in this group had too few reads to score)` : ''}.
        Comparing crops with each other mostly shows how well each crop's diseases are documented, not soil risk.
        This is a relative index, not a probability of disease.
      </li>
      {data.caveats.map((c) => <li key={c}>{c}</li>)}
      {data.notes.map((n) => <li key={n}>{n}</li>)}
      {data.kb.map((k) => (
        <li key={k.name}>
          Knowledge: {k.name}{k.source_version ? ` ${k.source_version}` : ''}
          {k.retrieved_utc ? ` (retrieved ${formatDate(k.retrieved_utc.slice(0, 10))})` : ''}
        </li>
      ))}
    </ul>
  )
}

/** Crop disease risk of one plot: for each crop, how this plot's soil fungi rank against the other plots of the
 *  same site, year and sequencing method. The chosen unit and crop are in the URL. */
export function RiskPanel({ plotId, unit, crop }: { plotId: string; unit: string | null; crop: string | null }) {
  const units = useFetch(`risk-units:${plotId}`, (s) => getCropRiskUnits(plotId, s))
  const list = units.data ?? []
  const current = list.find((u) => u.unit === unit) ?? (unit ? undefined : defaultUnit(list))
  const risk = useFetch(current ? `${plotId}|${current.unit}` : null, (s) => getCropRisk(plotId, current!.unit, s))

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
          <p className="rank-hint">Ranked against the other plots of this site, year and method — not a probability of disease.</p>
          <CropList rows={risk.data.crops} plotId={plotId} unit={current.unit} crop={crop} />
          {crop && <ContributionsTable plotId={plotId} unit={current.unit} crop={crop} />}
          <Notes data={risk.data} />
          <SkippedList groups={risk.data.skipped} />
        </>
      )}
    </div>
  )
}
