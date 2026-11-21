import { useEffect, useRef, useState } from 'react'
import type { Composition } from '../../api'
import { OTHER, UNASSIGNED, hasOwnColor, inkOn, phylumColor } from './colors'

const pct = (v: number) => (v >= 10 ? v.toFixed(0) : v >= 0.1 ? v.toFixed(1) : v > 0 ? '<0.1' : '0') + '%'
const fmt = new Intl.NumberFormat('en')

interface Part { key: string; label: string; detail: string | null; pct: number; reads: number | null; color: string }

const PLURAL = { phylum: 'phyla', class: 'classes', genus: 'genera' } as const

/** One sample's composition: a tall segmented bar (parts grouped by phylum, so a phylum's colour forms one run),
 *  a legend of the phyla in it, and a table with every part's share and reads (the table view). Hovering a part
 *  of the bar or a table row highlights both. */
export function CompositionView({ data }: { data: Composition }) {
  const { kind, rank } = data
  const named: Part[] = data.taxa.map((t) => ({
    key: t.name, label: t.name, detail: rank === 'phylum' ? null : t.phylum, pct: t.pct, reads: t.reads,
    color: phylumColor(kind, t.phylum),
  }))
  const rest: Part[] = [
    { key: '_other', label: `Other ${PLURAL[rank]}`,
      detail: `${data.n_taxa - data.taxa.length} more, each smaller`, pct: data.other_pct, reads: null, color: OTHER },
    { key: '_unassigned', label: `No ${rank} name`, detail: 'reads that could not be named this precisely',
      pct: data.unassigned_pct, reads: null, color: UNASSIGNED },
  ].filter((p) => p.pct > 0)

  // bar order: phyla by their summed share, then taxa by share inside each phylum; the neutral parts last
  const phylumShare = new Map<string, number>()
  for (const t of data.taxa) {
    const k = hasOwnColor(kind, t.phylum) ? t.phylum! : '_grey'
    phylumShare.set(k, (phylumShare.get(k) ?? 0) + t.pct)
  }
  const groupOf = (i: number) => (hasOwnColor(kind, data.taxa[i].phylum) ? data.taxa[i].phylum! : '_grey')
  const order = named.map((p, i) => ({ p, g: groupOf(i) }))
    .sort((a, b) => (a.g === '_grey' ? 1 : 0) - (b.g === '_grey' ? 1 : 0)
      || phylumShare.get(b.g)! - phylumShare.get(a.g)! || b.p.pct - a.p.pct)
    .map((x) => x.p)
  const bar = [...order, ...rest]
  const legend = [...phylumShare.keys()].filter((k) => k !== '_grey')
    .sort((a, b) => phylumShare.get(b)! - phylumShare.get(a)!)
  const table = [...named, ...rest]

  const [hover, setHover] = useState<string | null>(null)
  const [ref, width] = useWidth()
  const fits = (p: Part) => (p.pct / 100) * width >= pct(p.pct).length * 7.5 + 12
  const title = (p: Part) => `${p.label}${p.detail ? ` (${p.detail})` : ''}: ${pct(p.pct)}${p.reads !== null ? `, ${fmt.format(p.reads)} reads` : ''}`

  return (
    <div className="composition">
      <div ref={ref} className="seg-bar" role="img"
        aria-label={`Composition by ${rank}: ${bar.map((p) => `${p.label} ${pct(p.pct)}`).join(', ')}`}>
        {bar.map((p) => (
          <div key={p.key} className={hover === p.key ? 'seg on' : hover ? 'seg dim' : 'seg'} title={title(p)}
            style={{ flexGrow: p.pct, background: p.color, color: inkOn(p.color) }}
            onPointerEnter={() => setHover(p.key)} onPointerLeave={() => setHover(null)}>
            {width > 0 && fits(p) ? pct(p.pct) : ''}
          </div>
        ))}
      </div>
      <div className="legend comp-legend">
        {legend.map((ph) => <span key={ph}><i style={{ background: phylumColor(kind, ph) }} />{ph}</span>)}
        {phylumShare.has('_grey') || data.other_pct > 0 ? <span><i style={{ background: OTHER }} />Other</span> : null}
        {data.unassigned_pct > 0 && <span><i style={{ background: UNASSIGNED }} />No name at this rank</span>}
      </div>
      <table className="comp-table">
        <thead>
          <tr><th>{rank === 'phylum' ? 'Phylum' : rank === 'class' ? 'Class' : 'Genus'}</th>
            {rank !== 'phylum' && <th>Phylum</th>}<th className="num">Share</th><th className="num">Reads</th></tr>
        </thead>
        <tbody>
          {table.map((p) => (
            <tr key={p.key} className={[hover === p.key ? 'on' : '', p.key.startsWith('_') ? 'rest' : ''].join(' ')}
              onPointerEnter={() => setHover(p.key)} onPointerLeave={() => setHover(null)}>
              <td>
                <i className="swatch" style={{ background: p.color }} />{p.label}
                {p.key.startsWith('_') && <span className="muted"> · {p.detail}</span>}
              </td>
              {rank !== 'phylum' && <td className="muted">{p.key.startsWith('_') ? '' : p.detail ?? '–'}</td>}
              <td className="num">{pct(p.pct)}</td>
              <td className="num">{p.reads !== null ? fmt.format(p.reads) : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function useWidth() {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)))
    ro.observe(ref.current!)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}
