import type { CropRiskRow } from '../../api'
import { riskHref } from '../../router'

const W = 160, H = 18, PAD = 8

/** One dot per comparison plot on a line from the lowest to the highest index; this plot is the large green dot.
 *  Other plots' dots link to the same unit and crop on that plot. */
export function DotStrip({ row, plotId, unit }: { row: CropRiskRow; plotId: string; unit: string }) {
  const values = row.peers.map((p) => p.risk_index)
  const lo = Math.min(...values), hi = Math.max(...values)
  const x = (v: number) => (hi > lo ? PAD + ((v - lo) / (hi - lo)) * (W - 2 * PAD) : W / 2)
  const mine = row.peers.find((p) => p.plot_id === plotId)
  const label = mine && row.risk_index !== null
    ? `This plot ${row.risk_index.toFixed(2)}, rank ${row.rank ?? '?'} of ${row.n_peers}`
    : 'Comparison of this plot with the others'
  return (
    <svg className="dot-strip" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="group" aria-label={label}>
      <line x1={PAD} x2={W - PAD} y1={H / 2} y2={H / 2} className="axis" />
      {row.peers.filter((p) => p.plot_id !== plotId).map((p) => (
        <a key={p.plot_id} href={riskHref(p.plot_id, unit, row.crop)}>
          <title>{`${p.plot_id}: ${p.risk_index.toFixed(2)}`}</title>
          <circle cx={x(p.risk_index)} cy={H / 2} r={3.5} className="peer" />
        </a>
      ))}
      {mine && (
        <circle cx={x(mine.risk_index)} cy={H / 2} r={6} className="me">
          <title>{`${mine.plot_id}: ${mine.risk_index.toFixed(2)}`}</title>
        </circle>
      )}
    </svg>
  )
}
