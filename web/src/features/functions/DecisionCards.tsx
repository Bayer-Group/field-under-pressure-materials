import type { CardStatus, Carriers, CarrierGenus, DecisionCard, Implication } from '../../api'
import { GenusName } from '../../GenusName'

// Calm wording: a small coloured dot and a short label, never an alarm.
const STATUS: Record<CardStatus, { label: string; tone: 'ok' | 'look' | 'none' } | null> = {
  good: { label: 'Looks fine', tone: 'ok' },
  watch: { label: 'Worth a look', tone: 'look' },
  act: { label: 'Worth a look', tone: 'look' },
  notice: { label: 'Worth a look', tone: 'look' },
  info: null,
  unknown: { label: 'No data', tone: 'none' },
}
const BASIS_LABEL = { measured: 'Measured in the soil', genes: 'From bacterial genes', fungi: 'From fungal DNA', names: 'From bacterial names' } as const
const KIND_LABEL: Record<Implication['kind'], string> = { upside: 'Possible upside', risk: 'Possible concern', neutral: 'Note' }
const SECTIONS: { id: DecisionCard['section']; title: string; sub: string }[] = [
  { id: 'measured', title: 'Measured in this soil', sub: 'What NEON measured in the same soil at the same visit.' },
  { id: 'microbes', title: 'What the soil microbes can do', sub: 'From the genes in the soil DNA: what the microbes are equipped to do, not how active they are.' },
  { id: 'life', title: 'Soil life and plant health', sub: 'Fungi and bacteria that matter for crops, and signs of chemical pressure.' },
]

export const sharePct = (v: number) => (v >= 10 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v >= 0.1 ? v.toFixed(1) : v > 0 ? '<0.1' : '0') + '%'
const pctLabel = (v: number) => (v >= 1 ? v.toFixed(v >= 10 ? 0 : 1) : v > 0 ? '<1' : '0') + '%'
/** 'Bradyrhizobium japonicum' -> 'B. japonicum' */
const abbreviate = (sp: string) => sp.replace(/^([A-Z])[a-z]+\s+/, '$1. ')

/** Carrier genera as an inline list: `Name 6.1% (B. japonicum), ...`. */
export function CarrierList({ top }: { top: CarrierGenus[] }) {
  return (
    <>
      {top.map((g, i) => (
        <span key={g.name}>
          {i > 0 && ', '}
          <GenusName name={g.name} description={g.description} /> {sharePct(g.pct)}
          {g.species_examples?.[0] && <i className="carrier-sp"> {abbreviate(g.species_examples[0])}</i>}
        </span>
      ))}
    </>
  )
}

export function agreementClass(c: Carriers) {
  return c.agreement === 'names_only' || c.agreement === 'genes_only' ? 'caution' : ''
}

/** The cards of one sample, grouped into three calm sections. Each card shows one plain sentence, who does it
 *  and how this soil compares with the other well-sequenced NEON farm soils; the rest is under "Read more". */
export function DecisionCards({ cards, carriers }: { cards: DecisionCard[]; carriers?: Carriers[] }) {
  return (
    <>
      {SECTIONS.map((sec) => {
        const mine = cards.filter((c) => (c.section ?? 'microbes') === sec.id)
        if (!mine.length) return null
        return (
          <section key={sec.id} className="sc-section">
            <h3>{sec.title}</h3>
            <p className="sc-sub">{sec.sub}</p>
            <div className="sc-grid">
              {mine.map((c) => <Card key={c.card} c={c} carriers={carriers} />)}
            </div>
          </section>
        )
      })}
    </>
  )
}

function Card({ c, carriers }: { c: DecisionCard; carriers?: Carriers[] }) {
  const st = STATUS[c.status]
  const points = c.implications.filter((i) => i.kind !== 'neutral')
  const notes = c.implications.filter((i) => i.kind === 'neutral')
  const named = (c.carrier_terms ?? []).map((id) => carriers?.find((x) => x.term_id === id)).filter((x): x is Carriers => !!x)
  return (
    <article className={`sc-card ${st?.tone ?? 'plain'}`}>
      <header>
        <h4>{c.title}</h4>
        {st && <span className={`sc-tag ${st.tone}`}><i aria-hidden="true" />{st.label}</span>}
      </header>
      <p className="sc-headline">{c.headline}</p>
      {c.flag && <p className="sc-flag">{c.flag}</p>}
      {(c.who ?? []).length > 0 && (
        <div className="sc-who">
          <span className="sc-label">Who does it</span>
          <ul>{c.who.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      )}
      {c.context && <p className="sc-context">{c.context}</p>}
      <details className="sc-more">
        <summary>Read more <span className="sc-meta">· {BASIS_LABEL[c.basis]} · {c.confidence} confidence</span></summary>
        <p className="sc-finding">{c.finding}</p>
        {points.length > 0 && (
          <ul className="sc-points" aria-label="What it can mean">
            {points.map((i) => <li key={i.text} className={i.kind}><span className="sr-only">{KIND_LABEL[i.kind]}: </span>{i.text}</li>)}
          </ul>
        )}
        {notes.length > 0 && <ul className="sc-notes">{notes.map((i) => <li key={i.text}>{i.text}</li>)}</ul>}
        {named.map((x) => (
          <div key={x.term_id} className="dc-carriers">
            <b>Known carriers by name</b>
            <p className="carrier-head">{x.label} · {pctLabel(x.pct)}</p>
            <p className={`carrier-agree ${agreementClass(x)}`}>{x.agreement_text}</p>
            <p className="carrier-list">{x.top.length ? <CarrierList top={x.top} /> : 'No known carrier above 0.1% of reads.'}</p>
          </div>
        ))}
        {c.evidence.length > 0 && (
          <details className="sc-evidence">
            <summary>Numbers and rules</summary>
            <ul>{c.evidence.map((e) => <li key={e}>{e}</li>)}</ul>
          </details>
        )}
      </details>
    </article>
  )
}
