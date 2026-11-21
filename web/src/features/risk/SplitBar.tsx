import type { CropRiskRow } from '../../api'

const W = 120, H = 8

/** The index as a bar (length relative to the highest peer): solid for the part from genera found in this plot,
 *  light for the part from genera not found here. */
export function SplitBar({ row }: { row: CropRiskRow }) {
  const max = Math.max(...row.peers.map((p) => p.risk_index), row.risk_index ?? 0)
  if (row.risk_index === null || max <= 0) return <svg className="split-bar" width={W} height={H} aria-hidden="true" />
  const total = (row.risk_index / max) * W
  const found = ((row.from_detected ?? 0) / row.risk_index) * total
  return (
    <svg className="split-bar" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`${(row.from_detected ?? 0).toFixed(2)} from fungi found here, ${(row.from_not_detected ?? 0).toFixed(2)} from fungi not found here`}>
      <rect x={0} y={0} width={W} height={H} rx={2} className="track" />
      <rect x={0} y={0} width={found} height={H} className="found" />
      <rect x={found} y={0} width={Math.max(total - found, 0)} height={H} className="notfound" />
    </svg>
  )
}
