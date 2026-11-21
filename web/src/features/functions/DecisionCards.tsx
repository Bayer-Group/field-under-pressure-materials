import type { CardStatus, DecisionCard, Implication } from '../../api'

const STATUS_LABEL: Record<CardStatus, string> = {
  good: 'Fine', watch: 'Watch', act: 'Low', notice: 'Worth noticing', info: '', unknown: 'No data',
}
const BASIS_LABEL = { measured: 'Measured', genes: 'Bacterial genes', fungi: 'Fungal DNA' } as const
const KIND_LABEL: Record<Implication['kind'], string> = { upside: 'Possible upside', risk: 'Possible risk', neutral: 'Note' }

/** Short cards: title, one line, and (only when something stands out by a stated rule) the reason it is
 *  coloured. Everything else (the full finding, what it can mean, the numbers and rules) is under "More". */
export function DecisionCards({ cards, wide }: { cards: DecisionCard[]; wide?: boolean }) {
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
