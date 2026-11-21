import type { SkippedGroup } from '../../api'
import { compact } from './labels'

/** Genera that were left out of the index, grouped by why. */
export function SkippedList({ groups }: { groups: SkippedGroup[] }) {
  if (groups.length === 0) return null
  return (
    <div className="skipped">
      <h2>Not scored</h2>
      {groups.map((g) => (
        <details key={g.reason}>
          <summary>{g.label} ({g.n})</summary>
          <ul>
            {g.genera.map((x, i) => (
              <li key={`${x.genus}-${i}`}>
                {x.genus ?? 'unnamed'}
                {(x.reads !== null || x.detail) && (
                  <span className="muted"> — {[x.reads !== null ? `${compact.format(x.reads)} reads` : null, x.detail].filter(Boolean).join(', ')}</span>
                )}
              </li>
            ))}
            {g.more > 0 && <li className="muted">+ {g.more} more</li>}
          </ul>
        </details>
      ))}
    </div>
  )
}
