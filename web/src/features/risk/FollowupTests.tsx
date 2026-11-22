import { useState } from 'react'
import { getFollowupTests, type CropRiskRow, type TestSuggestion } from '../../api'
import { useFetch } from '../../useFetch'

const TOP = 4

function Item({ s }: { s: TestSuggestion }) {
  return (
    <li className="test-item">
      <div className="test-head">
        {s.trigger !== 'blind_spot' && <span className={`test-tag ${s.trigger}`}>{s.trigger_label}</span>}
        <b>{s.target ?? s.method}</b>
        {s.disease && <span className="muted"> · {s.disease}</span>}
      </div>
      {s.reason && <p>{s.reason}</p>}
      <dl>
        {s.target && <><dt>Test</dt><dd>{s.method}</dd></>}
        {s.sample && <><dt>Sample</dt><dd>{s.sample}</dd></>}
        {s.tells_you && <><dt>Tells you</dt><dd>{s.tells_you}</dd></>}
      </dl>
    </li>
  )
}

/** Which measurements would close the gaps in one cell's assessment, most useful first, with a crop picker
 *  beside the heading (the same choice as clicking a heatmap cell of this plot). */
export function FollowupTests({ plot, unit, crop, crops, onCrop }: {
  plot: string; unit: string; crop: string; crops: CropRiskRow[]; onCrop: (crop: string) => void
}) {
  const key = `tests|${plot}|${unit}|${crop}`
  const res = useFetch(key, (s) => getFollowupTests(plot, unit, crop, s))
  const [all, setAll] = useState<string | null>(null)
  if (res.error) return <p className="message error">Could not load the test suggestions: {res.error}</p>
  if (!res.data) return null
  const d = res.data
  const expanded = all === key
  const rows = expanded ? d.suggestions : d.suggestions.slice(0, TOP)
  return (
    <div className="risk-tests">
      <div className="chart-head tests-head">
        <h2>What to test next: {plot}, {d.label}</h2>
        <label className="crop-pick">
          <span className="choice-label">Crop</span>
          <select value={crop} onChange={(e) => onCrop(e.target.value)}>
            {crops.map((r) => <option key={r.crop} value={r.crop}>{r.label}</option>)}
          </select>
        </label>
      </div>
      {d.suggestions.length === 0 ? (
        <p className="risk-note">No follow-up test is suggested for this crop.</p>
      ) : (
        <>
          <ul>{rows.map((s) => <Item key={s.test_id} s={s} />)}</ul>
          {d.suggestions.length > TOP && (
            <button className="ghost show-all" onClick={() => setAll(expanded ? null : key)}>
              {expanded ? `Show top ${TOP}` : `Show all ${d.suggestions.length}`}
            </button>
          )}
        </>
      )}
      <p className="risk-note">{d.note}</p>
    </div>
  )
}
