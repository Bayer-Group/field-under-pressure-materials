// Typed client for the local API (src/cropfit/api.py). One function per endpoint; the types mirror the
// response models there. New backend features get a type and a function here, nothing else talks to fetch.

export interface Plot {
  plot_id: string
  site: string
  lat: number
  lon: number
  half_m: number
}

export interface GreennessPoint {
  date: string // YYYY-MM-DD
  ndvi: number
}

export interface EventSummary {
  event_id: string
  date: string
}

export interface EventDetail extends EventSummary {
  plot_id: string
  site: string
  sampled: string[]
}

export interface AerialPhoto {
  photo_id: string
  date: string
  month_only: boolean
  source: string
  bounds: [[number, number], [number, number]] // [[south, west], [north, east]]
  url: string
}

export interface GreennessMap {
  map_id: string
  date: string
  bounds: [[number, number], [number, number]]
  url: string
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(`/api${path}`, { signal })
  if (!r.ok) {
    const detail = await r.json().then((b) => b.detail, () => null)
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${r.status})`)
  }
  return r.json()
}

const id = encodeURIComponent

export const api = {
  plots: (s?: AbortSignal) => get<Plot[]>('/plots', s),
  greenness: (plotId: string, s?: AbortSignal) => get<GreennessPoint[]>(`/plots/${id(plotId)}/greenness`, s),
  plotEvents: (plotId: string, s?: AbortSignal) => get<EventSummary[]>(`/plots/${id(plotId)}/events`, s),
  aerial: (plotId: string, s?: AbortSignal) => get<AerialPhoto[]>(`/plots/${id(plotId)}/aerial`, s),
  greennessMaps: (plotId: string, s?: AbortSignal) => get<GreennessMap[]>(`/plots/${id(plotId)}/greenness-maps`, s),
  greennessAt: (mapId: string, lat: number, lon: number) =>
    get<{ ndvi: number | null }>(`/greenness-maps/${id(mapId)}/value?lat=${lat}&lon=${lon}`),
  event: (eventId: string, s?: AbortSignal) => get<EventDetail>(`/events/${id(eventId)}`, s),
}
