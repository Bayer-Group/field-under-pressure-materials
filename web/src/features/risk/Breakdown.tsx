import { useState } from 'react'
import { getCropContributions, type Contribution } from '../../api'
import { useFetch } from '../../useFetch'
import { STATUS_LABEL } from './labels'

const share = (c: Contribution) => (!c.detected ? '—' : c.share_pct < 0.01 ? '<0.01' : c.share_pct.toFixed(2))

/** Why one cell has its value: the split of the index and the genera behind it. */
export function Breakdown({ plot, unit, crop }: { plot: string; unit: string; crop: string }) {
  const res = useFetch(`${plot}|${unit}|${crop}`, (s) => getCropContributions(plot, unit, crop, s))
  const [all, setAll] = useState<string | null>(null)
  if (res.error) return <p className="message error">Could not load the breakdown: {res.error}</p>
  if (!res.data) return <p className="message">Loading…</p>
  const d = res.data
  const r = d.row
  if (r.status !== 'ok' || r.risk_index === null) {
    return <p className="message">{plot}, {d.label}: {STATUS_LABEL[r.status as Exclude<typeof r.status, 'ok'>]}. Nothing to break down.</p>
  }
  const key = `${plot}|${unit}|${crop}`
  const expanded = all === key
  const rows = expanded ? d.contributions : d.contributions.slice(0, 10)
  const max = Math.max(1e-9, ...rows.map((c) => c.contribution))
  const small = d.contributions.some((c) => c.small_reference)

  return (
    <div className="risk-break">
      <h2>Why: the plant-pathogenic fungi behind this score</h2>
      <p className="risk-note">
        Contribution = A × H. A: how this plot's share of the genus ranks among comparison samples (0–1). H: share of the
        genus's documented species recorded on this crop (USDA Fungus-Host). The index is the sum over all genera.
      </p>
      <table className="comp-table">
        <thead>
          <tr><th>Genus</th><th>In this plot</th><th className="num">Share %</th><th className="num">A</th><th>H</th><th>Contribution</th></tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.genus}>
              <td>{c.genus}{c.members.length > 1 && <span className="muted"> ({c.members.join(', ')})</span>}</td>
              <td><span className={`pill ${c.detected ? 'found' : 'notfound'}`}>{c.detected ? 'Found' : 'Not found'}</span></td>
              <td className="num">{share(c)}</td>
              <td className="num">{c.a.toFixed(2)}{c.small_reference && ' *'}</td>
              <td title={c.species_on_crop.join(', ')}>
                {c.n_species_on_crop} of {c.n_species_documented} species
                {c.n_species_more > 0 && <span className="muted"> (+ {c.n_species_more} more)</span>}
              </td>
              <td>
                <span className="risk-bar-row">
                  <span className="risk-bar"><span className={c.detected ? '' : 'faint'} style={{ width: `${(100 * c.contribution) / max}%` }} /></span>
                  <span className="num">{c.contribution.toFixed(3)}</span>
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {d.contributions.length > 10 && (
        <button className="ghost show-all" onClick={() => setAll(expanded ? null : key)}>
          {expanded ? 'Show top 10' : `Show all ${d.contributions.length}`}
        </button>
      )}
      <p className="risk-note">{d.n_scored_zero_h} other pathogenic genera have no recorded species on this crop.</p>
      {small && <p className="risk-note">* A rests on fewer than 10 comparison samples.</p>}
    </div>
  )
}
