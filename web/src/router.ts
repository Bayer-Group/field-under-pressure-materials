import { useSyncExternalStore } from 'react'

// Hash routes, so the app works from any static server and links can be bookmarked:
//   #/                 overview map
//   #/plot/<plot_id>   map zoomed to one plot, with its greenness chart
//   #/event/<event_id> details of one sampling visit
export type Route = { page: 'map'; plotId: string | null } | { page: 'event'; eventId: string }

export function parseRoute(hash: string): Route {
  const [page, arg] = hash.replace(/^#\/?/, '').split('/').map(decodeURIComponent)
  if (page === 'event' && arg) return { page: 'event', eventId: arg }
  return { page: 'map', plotId: page === 'plot' && arg ? arg : null }
}

export const plotHref = (plotId: string) => `#/plot/${encodeURIComponent(plotId)}`
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
