import { useEffect, useRef, useState } from 'react'
import type { Composition } from '../../api'
import { OTHER, UNASSIGNED, hasOwnColor, inkOn, phylumColor } from './colors'

const pct = (v: number) => (v >= 10 ? v.toFixed(0) : v >= 0.1 ? v.toFixed(1) : v >= 0.01 ? v.toFixed(2) : v > 0 ? '<0.01' : '0') + '%'
const fmt = new Intl.NumberFormat('en')
const PLURAL = { phylum: 'phyla', class: 'classes', genus: 'genera' } as const
const GAP = 2 // px of surface between two parts wide enough to carry one
const MIN_GAPPED = 6 // parts narrower than this touch their neighbours (thousands of genera cannot all have gaps)
const FIRST_ROWS = 25 // table rows shown before "Show all"

interface Part { key: string; label: string; detail: string | null; pct: number; reads: number | null; color: string }

const SINGULAR_TITLE = { phylum: 'Phylum', class: 'Class', genus: 'Genus' } as const
const EXAMPLE = {
  bacteria: { phylum: 'Firmicutes', class: 'Bacilli', genus: 'Streptomyces' },
  fungi: { phylum: 'Glomeromycota', class: 'Sordariomycetes', genus: 'Fusarium' },
} as const

/** One sample's composition, every taxon shown: a tall segmented bar (parts grouped by phylum, so a phylum's
 *  colour forms one run), a readout naming the part under the pointer, a legend of the coloured phyla, and a
 *  table of every taxon's share and reads (the table view). Hovering a part or a table row highlights both.
 *  `query` narrows the table to taxa whose name or phylum contains it, and lights up their parts of the bar. */
export function CompositionView({ data, query, onQuery }: { data: Composition; query: string; onQuery: (q: string) => void }) {
  const { kind, rank } = data
  const named: Part[] = data.taxa.map((t) => ({
    key: t.name, label: t.name, detail: rank === 'phylum' ? null : t.phylum, pct: t.pct, reads: t.reads,
    color: phylumColor(kind, t.phylum),
  }))
  const rest: Part[] = [
    { key: '_other', label: `Other ${PLURAL[rank]}`, detail: `${data.n_taxa - data.taxa.length} more`,
      pct: data.other_pct, reads: null, color: OTHER },
    { key: '_unassigned', label: `No ${rank} name`, detail: 'reads that could not be named this precisely',
      pct: data.unassigned_pct, reads: null, color: UNASSIGNED },
  ].filter((p) => p.pct > 0)

  // bar order: coloured phyla by their summed share, then the grey ones; taxa by share inside each phylum
  const phylumShare = new Map<string, number>()
  for (const t of data.taxa) if (t.phylum) phylumShare.set(t.phylum, (phylumShare.get(t.phylum) ?? 0) + t.pct)
  const rankOf = (phylum: string | null) => (hasOwnColor(kind, phylum) ? 0 : 1)
  const order = data.taxa.map((t, i) => ({ t, p: named[i] }))
    .sort((a, b) => rankOf(a.t.phylum) - rankOf(b.t.phylum)
      || (phylumShare.get(b.t.phylum ?? '') ?? 0) - (phylumShare.get(a.t.phylum ?? '') ?? 0)
      || (a.t.phylum ?? '').localeCompare(b.t.phylum ?? '') || b.p.pct - a.p.pct)
    .map((x) => x.p)
  const bar = [...order, ...rest]
  const legend = [...phylumShare.keys()].filter((k) => hasOwnColor(kind, k))
    .sort((a, b) => phylumShare.get(b)! - phylumShare.get(a)!)
  const greyPhyla = [...phylumShare.keys()].filter((k) => !hasOwnColor(kind, k)).length
  const q = query.trim().toLowerCase()
  const matches = (p: Part) => !q || (!p.key.startsWith('_') && (p.label.toLowerCase().includes(q) || (p.detail ?? '').toLowerCase().includes(q)))
  const table = [...named, ...rest].filter(matches)
  const found = new Set(q ? table.map((p) => p.key) : [])
  const foundPct = table.reduce((s, p) => s + p.pct, 0)

  const [hover, setHover] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)
  // the long tail of genera is behind a button; a search always lists every match, and the two grey rows stay
  const short = !q && !showAll && named.length > FIRST_ROWS + 5
  const rows = short ? [...named.slice(0, FIRST_ROWS), ...rest] : table
  // bars compare named taxa (the grey rows get none), against the largest one, so they keep their scale while searching
  const maxPct = Math.max(...named.map((p) => p.pct), 0.0001)
  const [ref, width] = useWidth()
  const total = bar.reduce((s, p) => s + p.pct, 0) || 1
  let x = 0
  const placed = bar.map((p) => {
    const w = (p.pct / total) * width
    const box = { p, left: x, width: w >= MIN_GAPPED ? w - GAP : w }
    x += w
    return box
  })
  const fits = (w: number, p: Part) => w >= pct(p.pct).length * 7.5 + 12
  const hovered = bar.find((p) => p.key === hover)

  return (
    <div className="composition">
      <div ref={ref} className="seg-bar" role="img" onPointerLeave={() => setHover(null)}
        aria-label={`Composition by ${rank}, ${data.n_taxa} ${PLURAL[rank]}; the table below lists each one`}>
        {width > 0 && placed.map(({ p, left, width: w }) => (
          <div key={p.key} className={['seg', w >= 8 ? 'round' : '', hover === p.key ? 'on' : (q ? !found.has(p.key) : hover) ? 'dim' : ''].join(' ')}
            style={{ left, width: Math.max(w, 0.5), background: p.color, color: inkOn(p.color) }}
            onPointerEnter={() => setHover(p.key)}>
            {fits(w, p) ? pct(p.pct) : ''}
          </div>
        ))}
      </div>
      <p className="seg-readout">
        {hovered
          ? <><b>{hovered.label}</b>{hovered.detail && ` · ${hovered.detail}`} · {pct(hovered.pct)}{hovered.reads !== null && ` · ${fmt.format(hovered.reads)} reads`}</>
          : `${fmt.format(data.n_taxa)} ${PLURAL[rank]}. Point at the bar to name a part.`}
      </p>
      <div className="legend comp-legend">
        {legend.map((ph) => <span key={ph}><i style={{ background: phylumColor(kind, ph) }} />{ph}</span>)}
        {greyPhyla > 0 && <span><i style={{ background: OTHER }} />{greyPhyla} more {greyPhyla === 1 ? 'phylum' : 'phyla'} (listed in the table)</span>}
        {data.unassigned_pct > 0 && <span><i style={{ background: UNASSIGNED }} />No name at this rank</span>}
      </div>
      <div className="taxon-search">
        <input type="search" value={query} onChange={(e) => onQuery(e.target.value)}
          placeholder={`Find a ${rank === 'phylum' ? 'phylum' : `${rank} or phylum`}, e.g. ${EXAMPLE[data.kind][rank]}`}
          aria-label={rank === 'phylum' ? 'Find a phylum by name' : `Find a ${rank} by its name or its phylum`} />
        {q && (
          <span className="search-count" aria-live="polite">
            {table.length === 0
              ? `No ${rank} matching “${query.trim()}” in this sample`
              : `${fmt.format(table.length)} of ${fmt.format(data.n_taxa)} ${PLURAL[rank]} match · together ${pct(foundPct)}`}
          </span>
        )}
      </div>
      <table className="comp-table">
        <thead>
          <tr><th>{SINGULAR_TITLE[rank]}</th>
            {rank !== 'phylum' && <th>Phylum</th>}<th className="share-h">Share of reads</th><th className="num">Reads</th></tr>
        </thead>
        <tbody onPointerLeave={() => setHover(null)}>
          {rows.map((p, i) => (
            <tr key={p.key} className={[hover === p.key ? 'on' : '', p.key.startsWith('_') ? 'rest' : '', short && i === FIRST_ROWS ? 'after-gap' : ''].join(' ')}
              onPointerEnter={() => setHover(p.key)}>
              <td>
                <i className="swatch" style={{ background: p.color }} />{p.label}
                {p.key.startsWith('_') && <span className="muted"> · {p.detail}</span>}
              </td>
              {rank !== 'phylum' && <td className="muted">{p.key.startsWith('_') ? '' : p.detail ?? '–'}</td>}
              <td>
                <div className="share">
                  <span className="share-bar" aria-hidden="true">
                    {!p.key.startsWith('_') && <span style={{ width: `${(p.pct / maxPct) * 100}%` }} />}
                  </span>
                  <span className="num">{pct(p.pct)}</span>
                </div>
              </td>
              <td className="num">{p.reads !== null ? fmt.format(p.reads) : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {short && (
        <button className="ghost show-all" onClick={() => setShowAll(true)}>
          Show all {fmt.format(named.length)} {PLURAL[rank]} ({fmt.format(named.length - FIRST_ROWS)} more, together {pct(named.slice(FIRST_ROWS).reduce((s, p) => s + p.pct, 0))})
        </button>
      )}
      {!q && showAll && named.length > FIRST_ROWS + 5 && (
        <button className="ghost show-all" onClick={() => setShowAll(false)}>Show the top {FIRST_ROWS} only</button>
      )}
    </div>
  )
}

function useWidth() {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width))
    ro.observe(ref.current!)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}
