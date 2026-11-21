import { useSyncExternalStore } from 'react'

// Hash routes, so the app works from any static server and links can be bookmarked:
//   #/                                    overview map
//   #/plot/<plot_id>                      map zoomed to one plot, with its greenness chart
//   #/plot/<plot_id>/microbes[/<sample>]  the same plot with its soil microbiome composition
//   #/plot/<plot_id>/risk[/<unit>[/<crop>]]  the same plot with its crop disease risk
//   #/event/<event_id>                    details of one sampling visit
export type PlotTab = 'greenness' | 'microbes' | 'risk'
export type Route =
  | { page: 'map'; plotId: string | null; tab: PlotTab; sampleId: string | null; unit: string | null; crop: string | null }
  | { page: 'event'; eventId: string }

export function parseRoute(hash: string): Route {
  const [page, arg, tab, third, fourth] = hash.replace(/^#\/?/, '').split('/').map(decodeURIComponent)
  if (page === 'event' && arg) return { page: 'event', eventId: arg }
  const plotId = page === 'plot' && arg ? arg : null
  const microbes = plotId !== null && tab === 'microbes'
  const risk = plotId !== null && tab === 'risk'
  return {
    page: 'map', plotId, tab: microbes ? 'microbes' : risk ? 'risk' : 'greenness',
    sampleId: microbes && third ? third : null,
    unit: risk && third ? third : null, crop: risk && third && fourth ? fourth : null,
  }
}

export const plotHref = (plotId: string) => `#/plot/${encodeURIComponent(plotId)}`
export const microbesHref = (plotId: string, sampleId?: string) =>
  `${plotHref(plotId)}/microbes${sampleId ? `/${encodeURIComponent(sampleId)}` : ''}`
export const riskHref = (plotId: string, unit?: string | null, crop?: string | null) =>
  `${plotHref(plotId)}/risk${unit ? `/${encodeURIComponent(unit)}${crop ? `/${encodeURIComponent(crop)}` : ''}` : ''}`
export const eventHref = (eventId: string) => `#/event/${encodeURIComponent(eventId)}`
export const navigate = (href: string) => { window.location.hash = href }

const subscribe = (cb: () => void) => {
  window.addEventListener('hashchange', cb)
  return () => window.removeEventListener('hashchange', cb)
}

export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash)
  return parseRoute(hash)
}
