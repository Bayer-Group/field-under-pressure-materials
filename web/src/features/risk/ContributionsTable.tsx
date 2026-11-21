import { getCropContributions, type Contribution } from '../../api'
import { useFetch } from '../../useFetch'
import { STATUS_LABEL } from './labels'

const share = (c: Contribution) => (!c.detected ? '—' : c.share_pct < 0.01 ? '<0.01' : c.share_pct.toFixed(2))
const lifestyle = (c: Contribution) => {
  const l = c.lifestyle ? c.lifestyle.replace(/_/g, ' ') : '—'
  return c.passed_by === 'secondary_lifestyle' ? `${l}; plant pathogen as secondary lifestyle` : l
}

/** The genera behind one crop's index: A (how this plot ranks on the genus) times H (how well the genus is
 *  documented on the crop). Fetched when a crop is chosen. */
export function ContributionsTable({ plotId, unit, crop }: { plotId: string; unit: string; crop: string }) {
  const res = useFetch(`${plotId}|${unit}|${crop}`, (s) => getCropContributions(plotId, unit, crop, s))
  if (res.error) return <p className="message error">Could not load the genera: {res.error}</p>
  if (!res.data) return <p className="message">Loading…</p>
  const d = res.data
  if (d.row.status !== 'ok') {
    return <p className="message">{d.label}: {STATUS_LABEL[d.row.status]}. No genera to show.</p>
  }
  return (
    <div className="contributions">
      <h2>Genera behind the {d.label} index</h2>
      <table className="comp-table">
        <thead>
          <tr>
            <th>Genus</th><th>In this plot</th><th className="num">Share %</th><th className="num">A</th>
            <th>H</th><th className="num">Contribution</th><th>Lifestyle</th>
          </tr>
        </thead>
        <tbody>
          {d.contributions.map((c) => (
            <tr key={c.genus}>
              <td>
                {c.genus}
                {c.members.length > 1 && <span className="muted"> ({c.members.join(', ')})</span>}
              </td>
              <td><span className={`pill ${c.detected ? 'found' : 'notfound'}`}>{c.detected ? 'Found' : 'Not found'}</span></td>
              <td className="num">{share(c)}</td>
              <td className="num">{c.a.toFixed(2)}{c.small_reference && <span className="hint" title="Few comparison samples"> *</span>}</td>
              <td>
                {c.species_on_crop.length > 0 ? (
                  <details>
                    <summary>{c.n_species_on_crop} of {c.n_species_documented} species</summary>
                    <ul>
                      {c.species_on_crop.map((s) => <li key={s}>{s}</li>)}
                      {c.n_species_more > 0 && <li className="muted">and {c.n_species_more} more</li>}
                    </ul>
                  </details>
                ) : (
                  <>{c.n_species_on_crop} of {c.n_species_documented} species</>
                )}
              </td>
              <td className="num">{c.contribution.toFixed(3)}</td>
              <td className="muted">{lifestyle(c)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="foot">{d.n_scored_zero_h} other scored genera have no recorded species on this crop.</p>
      <p className="foot">
        A = how this plot's share of the genus ranks among comparison samples (0–1). H = share of the genus's documented
        species recorded on this crop (USDA). Contribution = A × H; the index is the sum.
        {d.contributions.some((c) => c.small_reference) && ' * A rests on fewer than 10 comparison samples.'}
      </p>
    </div>
  )
}
