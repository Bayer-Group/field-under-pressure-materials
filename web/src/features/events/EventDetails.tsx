import { api } from '../../api'
import { daysBetween, formatDate } from '../../format'
import { eventHref, microbesHref, plotHref } from '../../router'
import { siteName } from '../../sites'
import { useFetch } from '../../useFetch'

const KIND_LINK = { bacteria: 'Bacteria and archaea', fungi: 'Fungi' } as const
const NEAR_DAYS = 16 // a satellite reading further than this from the visit is not shown as "around" it

const relDays = (d: number) => (d === 0 ? 'same day' : `${Math.abs(d)} ${Math.abs(d) === 1 ? 'day' : 'days'} ${d < 0 ? 'before' : 'after'}`)

/** One sampling visit. Results the backend derives for a visit later get their own sections here. */
export function EventDetails({ eventId }: { eventId: string }) {
  const { data: event, error, loading } = useFetch(eventId, (s) => api.event(eventId, s))
  const plotId = event?.plot_id ?? null
  const microbes = useFetch(plotId && `microbiome:${plotId}`, (s) => api.microbiome(plotId!, s))
  const visits = useFetch(plotId && `events:${plotId}`, (s) => api.plotEvents(plotId!, s))
  const greenness = useFetch(plotId && `greenness:${plotId}`, (s) => api.greenness(plotId!, s))
  if (loading) return <main className="page"><p className="message">Loading…</p></main>
  if (error || !event) {
    return <main className="page"><p className="message error">Could not load this visit: {error}</p><a href="#/">Back to all plots</a></main>
  }
  const fromVisit = (microbes.data ?? []).filter((s) => s.date === event.date)
  const list = visits.data ?? []
  const at = list.findIndex((v) => v.event_id === event.event_id)
  const prev = at > 0 ? list[at - 1] : null, next = at >= 0 ? list[at + 1] ?? null : null
  const near = (greenness.data ?? [])
    .map((p) => ({ ...p, d: daysBetween(event.date, p.date) }))
    .filter((p) => Math.abs(p.d) <= NEAR_DAYS)
    .sort((a, b) => Math.abs(a.d) - Math.abs(b.d))[0]

  return (
    <main className="page">
      <nav className="crumbs" aria-label="Breadcrumb">
        <a href="#/">All plots</a><span aria-hidden="true">/</span>
        <a href={plotHref(event.plot_id)}>Plot {event.plot_id}</a><span aria-hidden="true">/</span>
        <span>Visit</span>
      </nav>
      <div className="page-head">
        <div>
          <h1>Soil sampling on {formatDate(event.date)}</h1>
          <p className="sub">Plot {event.plot_id} · {siteName(event.site)}{at >= 0 && ` · visit ${at + 1} of ${list.length}`}</p>
        </div>
        {list.length > 1 && (
          <div className="pager">
            {prev ? <a href={eventHref(prev.event_id)} className="button">‹ {formatDate(prev.date)}</a> : <span className="button disabled">‹ Earlier</span>}
            {next ? <a href={eventHref(next.event_id)} className="button">{formatDate(next.date)} ›</a> : <span className="button disabled">Later ›</span>}
          </div>
        )}
      </div>

      <div className="cards">
        <section className="card">
          <h2>Collected on this visit</h2>
          {event.sampled.length ? (
            <ul className="checks">{event.sampled.map((s) => <li key={s}>{s}</li>)}</ul>
          ) : (
            <p className="message">Nothing recorded.</p>
          )}
        </section>

        {fromVisit.length > 0 && (
          <section className="card">
            <h2>Soil microbes from this visit</h2>
            <p className="card-note">What lives in the soil, by share of DNA reads.</p>
            <div className="link-buttons">
              {fromVisit.map((s) => (
                <a key={s.sample_id} className="button primary" href={microbesHref(event.plot_id, s.sample_id)}>
                  {KIND_LINK[s.kind]} →
                </a>
              ))}
            </div>
          </section>
        )}

        <section className="card">
          <h2>Greenness around this visit</h2>
          {greenness.loading ? (
            <p className="message">Loading…</p>
          ) : near ? (
            <>
              <p className="stat"><b>{near.ndvi.toFixed(2)}</b><span>NDVI, {formatDate(near.date)} ({relDays(near.d)})</span></p>
              <p className="card-note">Nearest cloud-free satellite reading. 0 is bare soil, 1 dense green growth.</p>
            </>
          ) : (
            <p className="message">No cloud-free satellite reading within {NEAR_DAYS} days of this visit.</p>
          )}
          <a href={plotHref(event.plot_id)}>See the whole greenness timeline →</a>
        </section>
      </div>
    </main>
  )
}
