import { api } from '../../api'
import { formatDate } from '../../format'
import { microbesHref, plotHref } from '../../router'
import { useFetch } from '../../useFetch'

const KIND_LINK = { bacteria: 'Bacteria and archaea in the soil', fungi: 'Fungi in the soil' } as const

/** One sampling visit. Results the backend derives for a visit later get their own sections here. */
export function EventDetails({ eventId }: { eventId: string }) {
  const { data: event, error, loading } = useFetch(eventId, (s) => api.event(eventId, s))
  const microbes = useFetch(event ? `microbiome:${event.plot_id}` : null, (s) => api.microbiome(event!.plot_id, s))
  if (loading) return <main className="page"><p className="message">Loading…</p></main>
  if (error || !event) {
    return <main className="page"><p className="message error">Could not load this visit: {error}</p><a href="#/">Back to the map</a></main>
  }
  const fromVisit = (microbes.data ?? []).filter((s) => s.date === event.date)
  return (
    <main className="page">
      <a href={plotHref(event.plot_id)}>← Back to plot {event.plot_id}</a>
      <h1>Soil sampling on {formatDate(event.date)}</h1>
      <p className="sub">Plot {event.plot_id} · site {event.site}</p>
      <section className="card">
        <h2>Collected on this visit</h2>
        {event.sampled.length ? (
          <ul>{event.sampled.map((s) => <li key={s}>{s}</li>)}</ul>
        ) : (
          <p className="message">Nothing recorded.</p>
        )}
        {fromVisit.length > 0 && (
          <>
            <h2 className="card-sub">Soil microbes from this visit</h2>
            <ul>
              {fromVisit.map((s) => (
                <li key={s.sample_id}><a href={microbesHref(event.plot_id, s.sample_id)}>{KIND_LINK[s.kind]}</a></li>
              ))}
            </ul>
          </>
        )}
      </section>
    </main>
  )
}
