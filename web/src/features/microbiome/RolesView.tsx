import { useState } from 'react'
import type { RoleComposition, RoleGenus, RoleTerm, SummaryClassId } from '../../api'
import { GenusName } from '../../GenusName'
import { ROLE_COLOR, ROLE_DARK_INK, UNASSIGNED } from './colors'

const pct = (v: number) => (v >= 10 ? v.toFixed(0) : v >= 0.1 ? v.toFixed(1) : v >= 0.01 ? v.toFixed(2) : v > 0 ? '<0.01' : '0') + '%'
const fmt = new Intl.NumberFormat('en')

const POLARITY_COLOR: Record<string, string> = { ...ROLE_COLOR }
const ink = (bg: string) => (ROLE_DARK_INK.has(bg) || bg === UNASSIGNED ? '#0b0b0b' : '#ffffff')


/** One sample's microbes by what they may do: a summary bar over six classes, the role tree (terms overlap), and
 *  the genera behind a chosen role. */
export function RolesView({ data }: { data: RoleComposition }) {
  const summary = data.summary ?? []
  const terms = data.terms ?? []
  const [hover, setHover] = useState<SummaryClassId | '_none' | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [open, setOpen] = useState<Set<string>>(new Set())

  const segs: { key: SummaryClassId | '_none'; label: string; pct: number; color: string; detail: string }[] = [
    ...summary.map((s) => ({
      key: s.class_id, label: s.label, pct: s.pct, color: ROLE_COLOR[s.class_id],
      detail: `${s.n_genera} genera${s.top.length ? ` · ${s.top.join(', ')}` : ''}`,
    })),
    { key: '_none' as const, label: 'No genus name', pct: data.unassigned_pct, color: UNASSIGNED, detail: 'reads without a genus name' },
  ].filter((s) => s.pct > 0)
  const total = segs.reduce((s, p) => s + p.pct, 0) || 1
  const hovered = segs.find((s) => s.key === hover)

  const byId = new Map(terms.map((t) => [t.term_id, t]))
  const visible = (t: RoleTerm): boolean => {
    // roots and their children always; deeper rows only when every ancestor from depth 1 up is expanded
    let p = t.parent_id ? byId.get(t.parent_id) : undefined
    while (p && p.depth >= 1) {
      if (!open.has(p.term_id)) return false
      p = p.parent_id ? byId.get(p.parent_id) : undefined
    }
    return true
  }
  const hasChildren = (t: RoleTerm) => terms.some((x) => x.parent_id === t.term_id)
  const maxPct = Math.max(...terms.map((t) => t.pct), 0.0001)
  const sel = terms.find((t) => t.term_id === selected) ?? null
  const toggle = (id: string) => setOpen((o) => { const n = new Set(o); if (!n.delete(id)) n.add(id); return n })

  if (summary.length === 0 && terms.length === 0) return <p className="message">No role data for this sample.</p>

  return (
    <div className="composition roles">
      <div className="seg-bar" role="img" onPointerLeave={() => setHover(null)}
        aria-label={`Roles summary: ${summary.map((s) => `${s.label} ${pct(s.pct)}`).join(', ')}`}>
        {(() => {
          let x = 0
          return segs.map((s) => {
            const w = (s.pct / total) * 100
            const left = x
            x += w
            return (
              <div key={s.key} className={`seg ${hover === s.key ? 'on' : hover ? 'dim' : ''}`}
                style={{ left: `${left}%`, width: `${w}%`, background: s.color, color: ink(s.color), boxShadow: hover === s.key ? undefined : 'inset -2px 0 0 var(--surface)' }}
                onPointerEnter={() => setHover(s.key)}>
                {w > 7 ? pct(s.pct) : ''}
              </div>
            )
          })
        })()}
      </div>
      <p className="seg-readout">
        {hovered
          ? <><b>{hovered.label}</b> · {pct(hovered.pct)} · {hovered.detail}</>
          : 'Point at the bar to see a class. A genus counts in exactly one class here.'}
      </p>
      <div className="legend comp-legend">
        {summary.map((s) => (
          <span key={s.class_id}><i style={{ background: ROLE_COLOR[s.class_id] }} />{s.label} {pct(s.pct_of_named)} of named</span>
        ))}
        {data.unassigned_pct > 0 && <span><i style={{ background: UNASSIGNED }} />No genus name</span>}
      </div>

      <h3 className="roles-h">Roles</h3>
      <p className="roles-hint">A genus can have several roles, so these shares can add up to more than 100%.</p>
      <ul className="role-tree">
        {terms.filter(visible).map((t) => {
          const kids = hasChildren(t)
          const expandable = kids && t.depth >= 1
          const color = POLARITY_COLOR[t.polarity] ?? ROLE_COLOR.unknown
          return (
            <li key={t.term_id} className={`role-row ${t.n_genera === 0 ? 'empty' : ''} ${selected === t.term_id ? 'sel' : ''}`}
              style={{ paddingLeft: t.depth * 18 }}>
              <span className="role-twist">
                {expandable && (
                  <button className="ghost twist" aria-expanded={open.has(t.term_id)} aria-label={`Sub-roles of ${t.label}`}
                    onClick={() => toggle(t.term_id)}>{open.has(t.term_id) ? '▾' : '▸'}</button>
                )}
              </span>
              <span className="role-label">
                <button className="role-btn" aria-pressed={selected === t.term_id} aria-describedby={`tip-${t.term_id}`}
                  onClick={() => setSelected(selected === t.term_id ? null : t.term_id)}>{t.label}</button>
                <span role="tooltip" id={`tip-${t.term_id}`} className="genus-tip role-tip">{t.description}</span>
              </span>
              <span className="role-bar" aria-hidden="true"><span style={{ width: `${(t.pct / maxPct) * 100}%`, background: color }} /></span>
              <span className="num role-pct">{t.n_genera === 0 ? '' : pct(t.pct)}</span>
              <span className="role-n muted">{t.n_genera === 0 ? 'none in this sample' : `${fmt.format(t.n_genera)} genera`}</span>
            </li>
          )
        })}
      </ul>

      {sel ? <GenusTable term={sel} byId={byId} /> : <p className="roles-hint">Choose a role to list its genera.</p>}

      <p className="roles-caveat">
        Genus level: a genus marked as including pathogens also contains harmless species. Roles come from an AI
        annotation of each genus, checked by a second AI review only for harmful and abundant genera; for fungi, FUNGuild and
        FungalTraits are used where they give a role.
      </p>
    </div>
  )
}

function GenusTable({ term, byId }: { term: RoleTerm; byId: Map<string, RoleTerm> }) {
  const genera: RoleGenus[] = term.genera ?? []
  const maxPct = Math.max(...genera.map((g) => g.pct), 0.0001)
  return (
    <div className="role-genera">
      <h3 className="roles-h">{term.label}: genera</h3>
      {genera.length === 0 ? <p className="roles-hint">No genera with this role in this sample.</p> : (
        <div className="table-scroll">
          <table className="comp-table">
            <thead>
              <tr><th>Genus</th><th className="share-h">Share of reads</th><th className="num">Reads</th>
                <th>Role</th><th>Species examples</th></tr>
            </thead>
            <tbody>
              {genera.map((g) => (
                <tr key={g.name}>
                  <td><GenusName name={g.name} description={g.description} /></td>
                  <td>
                    <div className="share">
                      <span className="share-bar" aria-hidden="true"><span style={{ width: `${(g.pct / maxPct) * 100}%` }} /></span>
                      <span className="num">{pct(g.pct)}</span>
                    </div>
                  </td>
                  <td className="num">{fmt.format(g.reads)}</td>
                  <td className="muted">{g.term_id !== term.term_id ? byId.get(g.term_id)?.label ?? g.term_id : ''}</td>
                  <td className="muted"><i>{(g.species_examples ?? []).join('; ')}</i></td>
                </tr>
              ))}
              {term.other_genera_pct > 0 && (
                <tr className="rest">
                  <td colSpan={5}>{fmt.format(Math.max(term.n_genera - genera.length, 0))} more genera, together {pct(term.other_genera_pct)}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
