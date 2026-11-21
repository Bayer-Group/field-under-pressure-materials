import { getCropRisk, getCropRiskUnits, getProductPlan, type ProductPlan, type ProductRecommendation, type ProductTiming, type RiskUnitRef } from '../../api'
import { Choice } from '../../Choice'
import { formatDate } from '../../format'
import { navigate, planHref, riskHref } from '../../router'
import { useFetch } from '../../useFetch'
import { defaultUnit, pickInYear } from '../risk/RiskPanel'

const BASIS_LABEL: Record<ProductRecommendation['basis'], string> = {
  measured: 'Soil measurement', genes: 'Bacterial genes', fungi: 'Fungal DNA', site: 'Site conditions', history: 'Crop history',
}
const TIMING_LABEL: Record<ProductTiming, string> = { before_planting: 'Before planting', during_growth: 'During growth' }
const DEFAULT_CROP = 'corn'
const BUY_URL = 'https://www.cropscience.bayer.us/' // where "Buy now" goes
/** Entries that are advice rather than something to buy get no "Buy now". */
const NOT_FOR_SALE = new Set(['no_product', 'caution', 'note'])

function Item({ r, testsHref }: { r: ProductRecommendation; testsHref: string }) {
  return (
    <li className={`test-item plan-item ${r.category}`}>
      <div className="test-head">
        <span className={`test-tag ${r.category}`}>{r.category_label}</span>
        {r.trigger !== 'soil_signal' && <span className={`test-tag ${r.trigger}`}>{r.trigger_label}</span>}
      </div>
      <div className="plan-class-row">
        <b className="plan-class">{r.product_class}</b>
        {!NOT_FOR_SALE.has(r.category) && (
          <a className="buy-now" href={BUY_URL} target="_blank" rel="noopener noreferrer"
            aria-label={`Buy now: ${r.product_class} (opens Bayer Crop Science in a new tab)`}>Buy now</a>
        )}
      </div>
      <p>{r.reason}</p>
      <dl>
        {r.stage && <><dt>When</dt><dd>{r.stage}</dd></>}
        {r.works_because && <><dt>Why it helps</dt><dd>{r.works_because}</dd></>}
        {r.caution && <><dt>Keep in mind</dt><dd>{r.caution}</dd></>}
        {r.confirm_with.length > 0 && (
          <><dt>Confirm with</dt><dd>Test for {r.confirm_with.map((t) => t.name).join('; ')} (<a href={testsHref}>what to test next</a>)</dd></>
        )}
        <dt>Rests on</dt><dd>{BASIS_LABEL[r.basis]} · {r.confidence} confidence</dd>
      </dl>
    </li>
  )
}

function Column({ timing, plan, testsHref }: { timing: ProductTiming; plan: ProductPlan; testsHref: string }) {
  const rows = plan.recommendations.filter((r) => r.timing === timing)
  return (
    <section className="plan-col" aria-label={TIMING_LABEL[timing]}>
      <h2>{TIMING_LABEL[timing]}</h2>
      {rows.length === 0
        ? <p className="risk-note">Nothing stands out for this stage.</p>
        : <ul>{rows.map((r) => <Item key={r.product_id} r={r} testsHref={testsHref} />)}</ul>}
    </section>
  )
}

/** Products worth considering for one crop on one plot and year, before planting and during growth: from the
 *  crop disease risk of the fungal sample, the soil measurements and bacterial genes of the same year, the crop
 *  history and the site. The chosen unit and crop are in the URL. */
export function PlanPanel({ plotId, unit, crop }: { plotId: string; unit: string | null; crop: string | null }) {
  const units = useFetch(`risk-units:${plotId}`, (s) => getCropRiskUnits(plotId, s))
  const list = units.data ?? []
  const current = list.find((u) => u.unit === unit) ?? (unit ? undefined : defaultUnit(list))
  const risk = useFetch(current ? `${plotId}|${current.unit}` : null, (s) => getCropRisk(plotId, current!.unit, s))
  const crops = risk.data?.crops ?? []
  const chosen = crops.find((c) => c.crop === crop)?.crop ?? crops.find((c) => c.crop === DEFAULT_CROP)?.crop ?? crops[0]?.crop ?? null
  const plan = useFetch(current && chosen ? `plan|${plotId}|${current.unit}|${chosen}` : null,
    (s) => getProductPlan(plotId, current!.unit, chosen!, s))

  if (units.error) return <p className="message error">Could not load the plot's samples: {units.error}</p>
  if (units.loading) return <p className="message">Loading…</p>
  if (list.length === 0) return <p className="message">No fungal DNA data for this plot, so no treatment plan can be made.</p>
  if (!current) {
    return <p className="message">Unit {unit} was not found for this plot. <a href={planHref(plotId)}>Show the default</a></p>
  }
  const years = [...new Set(list.map((u) => u.year))]
  const sameYear = list.filter((u) => u.year === current.year)
  const go = (u: RiskUnitRef) => navigate(planHref(plotId, u.unit, chosen))

  return (
    <div className="risk plan">
      <div className="controls">
        <Choice label="Year">
          {years.map((y) => (
            <button key={y} aria-pressed={current.year === y} onClick={() => go(pickInYear(list, y))}>{y}</button>
          ))}
        </Choice>
        {sameYear.length > 1 && (
          <Choice label="Sequencing method">
            {sameYear.map((u) => (
              <button key={u.unit} aria-pressed={u.unit === current.unit} onClick={() => go(u)}>
                {u.method === 'current' ? 'Current method (.002)' : 'Older method (.001)'}
              </button>
            ))}
          </Choice>
        )}
        {crops.length > 0 && (
          <Choice label="Crop to grow">
            {crops.map((c) => (
              <button key={c.crop} aria-pressed={c.crop === chosen} onClick={() => navigate(planHref(plotId, current.unit, c.crop))}>
                {c.label}
              </button>
            ))}
          </Choice>
        )}
      </div>
      {risk.error ? (
        <p className="message error">Could not score the crops: {risk.error}</p>
      ) : plan.error ? (
        <p className="message error">Could not load the treatment plan: {plan.error}</p>
      ) : !plan.data ? (
        <p className="message">Working out the plan…</p>
      ) : (
        <>
          <div className="chart-head">
            <h2>Products to consider for {plan.data.label.toLowerCase()}</h2>
            <span className="legend">
              Soil fungi sampled {current.collect_dates.map((d) => formatDate(d)).join(', ') || 'on an unknown date'}
            </span>
          </div>
          <p className="risk-note">{plan.data.note}</p>
          {current.low_depth && (
            <p className="risk-note"><strong>This fungal sample has too few DNA reads to score, so nothing here rests on the fungi found.</strong></p>
          )}
          <div className="plan-cols">
            <Column timing="before_planting" plan={plan.data} testsHref={riskHref(plotId, current.unit, chosen)} />
            <Column timing="during_growth" plan={plan.data} testsHref={riskHref(plotId, current.unit, chosen)} />
          </div>
          <details className="risk-about" open={plan.data.unchecked.length > 0 && plan.data.recommendations.length === 0}>
            <summary>What this plan rests on, and what could not be checked</summary>
            <ul className="notes">
              {plan.data.sources.map((s) => <li key={s}>{s}</li>)}
              {plan.data.unchecked.length > 0 && (
                <li>
                  Not checked, because the soil values they need are missing for this plot and year:
                  <ul>{plan.data.unchecked.map((u) => <li key={u.product_id}>{u.product_class}</li>)}</ul>
                </li>
              )}
              <li>Nematodes and oomycetes are not measured by any dataset here; see the tests under crop disease risk.</li>
            </ul>
          </details>
        </>
      )}
    </div>
  )
}
