import type { CardStatus, Carriers, CarrierGenus, DecisionCard, Implication } from '../../api'
import { GenusName } from '../../GenusName'

const STATUS_LABEL: Record<CardStatus, string> = {
  good: 'Fine', watch: 'Watch', act: 'Low', notice: 'Worth noticing', info: '', unknown: 'No data',
}
const BASIS_LABEL = { measured: 'Measured', genes: 'Bacterial genes', fungi: 'Fungal DNA', names: 'Bacterial names' } as const
const KIND_LABEL: Record<Implication['kind'], string> = { upside: 'Possible upside', risk: 'Possible risk', neutral: 'Note' }

/** Short cards: title, one line, and (only when something stands out by a stated rule) the reason it is
 *  coloured. Everything else (the full finding, what it can mean, the numbers and rules) is under "More". */
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

/** Short cards: title, one line, and (only when something stands out by a stated rule) the reason it is
 *  coloured. Everything else (the full finding, what it can mean, the numbers and rules) is under "More". */
export function DecisionCards({ cards, wide, carriers }: { cards: DecisionCard[]; wide?: boolean; carriers?: Carriers[] }) {
  return (
    <div className={`dc-grid ${wide ? 'wide' : ''}`}>
      {cards.map((c) => (
        <article key={c.card} className={`dc-card ${c.status}`}>
          <header>
            <h4>{c.title}</h4>
            {STATUS_LABEL[c.status] && <span className={`dc-status ${c.status}`}>{STATUS_LABEL[c.status]}</span>}
          </header>
          <p className="dc-headline">{c.headline}</p>
          {c.flag && <p className={`dc-flag ${c.status}`}>{c.flag}</p>}
          <details className="dc-more">
            <summary>
              More <span className="dc-meta">· {BASIS_LABEL[c.basis]} · {c.confidence} confidence</span>
            </summary>
            <p className="dc-finding">{c.finding}</p>
            {c.implications.length > 0 && (
              <ul className="dc-imps" aria-label="What it can mean">
                {c.implications.map((i) => (
                  <li key={i.text} className={i.kind}><span className="sr-only">{KIND_LABEL[i.kind]}: </span>{i.text}</li>
                ))}
              </ul>
            )}
            {c.evidence.length > 0 && <ul className="dc-evidence">{c.evidence.map((e) => <li key={e}>{e}</li>)}</ul>}
            {(c.carrier_terms ?? []).map((id) => carriers?.find((x) => x.term_id === id)).filter((x): x is Carriers => !!x).map((x) => (
              <div key={x.term_id} className="dc-carriers">
                <b>Who may carry it (by name)</b>
                <p className="carrier-head">{x.label} · {pctLabel(x.pct)}</p>
                <p className={`carrier-agree ${agreementClass(x)}`}>{x.agreement_text}</p>
                <p className="carrier-list">
                  {x.top.length ? <CarrierList top={x.top} /> : 'No known carrier above 0.1% of reads.'}
                </p>
              </div>
            ))}
          </details>
        </article>
      ))}
    </div>
  )
}

/** Legend for the colours and marks used in the cards. */
export function CardLegend() {
  return (
    <div className="dc-legend">
      <span><i className="sw notice" /> worth noticing or below a soil-test level</span>
      <span><i className="sw act" /> well below a soil-test level</span>
      <span><i className="sw good" /> fine</span>
      <span><i className="sw info" /> nothing stands out</span>
      <span className="upside">possible upside</span>
      <span className="risk">possible risk</span>
    </div>
  )
}
