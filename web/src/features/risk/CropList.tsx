import { useState } from 'react'
import type { CropRiskRow } from '../../api'
import { Choice } from '../../Choice'
import { riskHref } from '../../router'
import { DotStrip } from './DotStrip'
import { rankText, STATUS_LABEL } from './labels'
import { SplitBar } from './SplitBar'

type Sort = 'rank' | 'index'

function sortRows(rows: CropRiskRow[], sort: Sort): CropRiskRow[] {
  const val = (r: CropRiskRow) => r.risk_index ?? -1
  return [...rows].sort((a, b) => {
    if ((a.status === 'ok') !== (b.status === 'ok')) return a.status === 'ok' ? -1 : 1
    if (sort === 'rank') return (b.percentile ?? -1) - (a.percentile ?? -1) || val(b) - val(a)
    return val(b) - val(a)
  })
}

/** One row per crop, each opening the genera behind its index. */
export function CropList({ rows, plotId, unit, crop }: { rows: CropRiskRow[]; plotId: string; unit: string; crop: string | null }) {
  const [sort, setSort] = useState<Sort>('rank')
  const labelOf = (c: string) => rows.find((r) => r.crop === c)?.label ?? c
  return (
    <div className="crop-list">
      <div className="list-tools">
        <Choice label="Sort crops by">
          <button aria-pressed={sort === 'rank'} onClick={() => setSort('rank')}>Rank among plots</button>
          <button aria-pressed={sort === 'index'} onClick={() => setSort('index')}>Index value</button>
        </Choice>
        <div className="legend">
          <span><i className="key-found" />found in this plot</span>
          <span><i className="key-notfound" />not found here (counted at its mid-rank, about 0.47 each)</span>
        </div>
      </div>
      <ul className="crop-rows">
        {sortRows(rows, sort).map((r) => (
          <li key={r.crop} className={r.crop === crop ? 'on' : ''}>
            <a className="crop-name" href={riskHref(plotId, unit, r.crop)} aria-current={r.crop === crop ? 'true' : undefined}>{r.label}</a>
            {r.status === 'ok' && r.rank !== null ? (
              <>
                <span className="rank">{rankText(r.rank, r.n_peers)}</span>
                <DotStrip row={r} plotId={plotId} unit={unit} />
                <SplitBar row={r} />
                <span className="value">{r.risk_index?.toFixed(2)}</span>
              </>
            ) : (
              <span className="badge">{r.status === 'ok' ? STATUS_LABEL.no_scored_genera : STATUS_LABEL[r.status]}</span>
            )}
            {r.small_reference && <span className="hint">small reference</span>}
            {r.same_as && <span className="hint">same host records as {labelOf(r.same_as)}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}
