import type { CropRiskRow } from '../../api'

export interface Selection { plot: string; crop: string }

const pct = (t: number) => Math.round(8 + 82 * t)

/** Plot x crop grid of risk indices. Shading is per crop column, or on one scale for every cell. */
export function Heatmap({ rows, plotId, selected, across, nUnits, onSelect }: {
  rows: CropRiskRow[]; plotId: string; selected: Selection; across: boolean; nUnits: number
  onSelect: (s: Selection) => void
}) {
  const values = rows.map((r) => new Map(r.peers.map((p) => [p.plot_id, p.risk_index])))
  const plots = [...new Set([plotId, ...rows.flatMap((r) => r.peers.map((p) => p.plot_id))])].sort()
  const range = (vs: number[]) => (vs.length ? [Math.min(...vs), Math.max(...vs)] : [0, 0])
  const all = range(values.flatMap((m) => [...m.values()]))
  const ranges = values.map((m) => (across ? all : range([...m.values()])))
  const hidden = nUnits - plots.length

  return (
    <>
      <div className="risk-scroll">
        <div className="heat" role="group" aria-label="Crop risk index by plot and crop"
          style={{ gridTemplateColumns: `minmax(6.5em, auto) repeat(${rows.length}, minmax(52px, 1fr))` }}>
          <span />
          {rows.map((r) => <span key={r.crop} className="heat-col">{r.label}</span>)}
          {plots.map((p) => (
            <Row key={p} plot={p} me={p === plotId}>
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
                const [lo, hi] = ranges[i]
                const x = pct(hi > lo ? (v - lo) / (hi - lo) : 0.5)
                const on = selected.plot === p && selected.crop === r.crop
                return (
                  <button key={r.crop} className={`heat-cell${on ? ' on' : ''}`} aria-label={text} title={text}
                    aria-pressed={on} onClick={() => onSelect({ plot: p, crop: r.crop })}
                    style={{ background: `color-mix(in srgb, var(--green) ${x}%, transparent)`, color: x > 55 ? '#fff' : 'var(--ink)' }}>
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

function Row({ plot, me, children }: { plot: string; me: boolean; children: React.ReactNode }) {
  return (
    <>
      <span className={`heat-row${me ? ' me' : ''}`}>{plot}{me && <span className="muted"> (this plot)</span>}</span>
      {children}
    </>
  )
}
