import type { CropRiskRow } from '../../api'
import { riskHref } from '../../router'

export interface Selection { plot: string; crop: string }

/** Cell colour for a value at `t` (0 = lowest risk, 1 = highest): green below the middle, red above it,
 *  stronger the further from the middle. */
function tone(t: number): { background: string; color: string } {
  const strength = Math.round(8 + 82 * Math.abs(t - 0.5) * 2)
  const hue = t < 0.5 ? 'var(--good)' : 'var(--bad)'
  return { background: `color-mix(in srgb, ${hue} ${strength}%, transparent)`, color: strength > 55 ? '#fff' : 'var(--ink)' }
}

/** Plot x crop grid of risk indices. Shading is per plot row, or on one scale for every cell. */
export function Heatmap({ rows, plotId, unit, selected, across, nUnits, onSelect }: {
  rows: CropRiskRow[]; plotId: string; unit: string; selected: Selection; across: boolean; nUnits: number
  onSelect: (s: Selection) => void
}) {
  const values = rows.map((r) => new Map(r.peers.map((p) => [p.plot_id, p.risk_index])))
  const plots = [...new Set([plotId, ...rows.flatMap((r) => r.peers.map((p) => p.plot_id))])].sort()
  const range = (vs: number[]) => (vs.length ? [Math.min(...vs), Math.max(...vs)] : [0, 0])
  const all = range(values.flatMap((m) => [...m.values()]))
  // One [lo, hi] per plot row: that plot's indices across the scored crops.
  const ranges = new Map(plots.map((p) => [p, across ? all : range(
    values.flatMap((m, i) => (rows[i].status === 'no_knowledge' ? [] : m.has(p) ? [m.get(p)!] : [])))]))
  const hidden = nUnits - plots.length

  return (
    <>
      <div className="risk-scroll">
        <div className="heat" role="group" aria-label="Crop risk index by plot and crop"
          style={{ gridTemplateColumns: `minmax(6.5em, auto) repeat(${rows.length}, minmax(52px, 1fr))` }}>
          <span />
          {rows.map((r) => <span key={r.crop} className="heat-col">{r.label}</span>)}
          {plots.map((p) => (
            <Row key={p} plot={p} me={p === plotId} href={riskHref(p, unit, selected.crop)}>
              {rows.map((r, i) => {
                const v = values[i].get(p)
                if (r.status === 'no_knowledge') {
                  return <span key={r.crop} className="heat-cell none" title="no host records">no host records</span>
                }
                if (v === undefined) {
                  return <span key={r.crop} className="heat-cell none" title="not scored (too few reads)">—</span>
                }
                const rank = 1 + r.peers.filter((q) => q.risk_index > v).length
                const text = `${p}, ${r.label}: ${v.toFixed(2)}, rank ${rank} of ${r.peers.length}`
                const [lo, hi] = ranges.get(p)!
                const on = selected.plot === p && selected.crop === r.crop
                return (
                  <button key={r.crop} className={`heat-cell${on ? ' on' : ''}`} aria-label={text} title={text}
                    aria-pressed={on} onClick={() => onSelect({ plot: p, crop: r.crop })}
                    style={tone(hi > lo ? (v - lo) / (hi - lo) : 0.5)}>
                    {v.toFixed(2)}
                  </button>
                )
              })}
            </Row>
          ))}
        </div>
      </div>
      {hidden > 0 && (
        <p className="risk-note">
          {hidden} {hidden === 1 ? 'plot' : 'plots'} of this group had too few DNA reads to score and {hidden === 1 ? 'is' : 'are'} not shown.
        </p>
      )}
    </>
  )
}

/** Row label: the plot ID doubles as a plot selector (same year, method and crop on that plot). */
function Row({ plot, me, href, children }: { plot: string; me: boolean; href: string; children: React.ReactNode }) {
  return (
    <>
      {me ? (
        <span className="heat-row me" aria-current="page">{plot}<span className="muted"> (this plot)</span></span>
      ) : (
        <a className="heat-row" href={href} title={`Open plot ${plot}`}>{plot}</a>
      )}
      {children}
    </>
  )
}
