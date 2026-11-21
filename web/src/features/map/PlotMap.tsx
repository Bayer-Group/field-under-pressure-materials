import L from 'leaflet'
import { useEffect, useRef } from 'react'
import type { Plot } from '../../api'
import { bySite } from '../../sites'

/** An image laid over the map between two corners. */
export interface MapOverlay {
  url: string
  bounds: [[number, number], [number, number]] // [[south, west], [north, east]]
  crisp?: boolean // show the image's pixels as sharp squares (data maps) instead of smoothing them (photos)
  opacity?: number
}

interface Props {
  plots: Plot[]
  selected: Plot | null
  focusSite: string | null // with no plot selected: zoom to this site's plots instead of all plots
  highlight: string | null // plot id to emphasise (hovered in a list)
  overlay: MapOverlay | null
  base: BaseMap
  contextM: number // how far around a selected plot the map shows, in metres
  onSelect: (plotId: string) => void
  onSite: (site: string) => void
  /** When given, clicking the map asks for a short text about that spot and shows it in a popup. */
  inspect?: (lat: number, lon: number) => Promise<string>
}

/** What is under everything else: a drawn street map, or orthophotos (aerial and satellite imagery). */
export type BaseMap = 'streets' | 'imagery'

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services'
// Static demo: opened from file:// there is no Referer, which OSM's tile servers refuse; Esri needs no key.
const STATIC = import.meta.env.VITE_STATIC === '1'
const BASE_MAPS: Record<BaseMap, { url: string; maxNativeZoom: number; attribution: string }> = {
  streets: STATIC
    ? { url: `${ESRI}/World_Topo_Map/MapServer/tile/{z}/{y}/{x}`, maxNativeZoom: 19,
        attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, USGS, NGA, EPA, USDA, NPS' }
    : { url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', maxNativeZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' },
  // beyond zoom 18 Esri has no imagery in many rural places: stretch the zoom-18 tiles instead of showing gaps
  imagery: { url: `${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, maxNativeZoom: 18,
             attribution: 'Imagery &copy; Esri &mdash; Esri, Maxar, Earthstar Geographics and the GIS User Community' },
}

const OVERLAY_PANE = 'overlay-image' // above the base map, below plot outlines and markers
const DOT = { radius: 7, color: '#fff', weight: 2, fillColor: '#1f6f43', fillOpacity: 1 }
const DOT_HOT = { radius: 10, color: '#fff', weight: 3, fillColor: '#c2410c', fillOpacity: 1 }

/** Square of `half` metres around a point, as Leaflet bounds. */
function square(lat: number, lon: number, half: number): L.LatLngBounds {
  const dLat = half / 111_320
  const dLon = half / (111_320 * Math.cos((lat * Math.PI) / 180))
  return L.latLngBounds([lat - dLat, lon - dLon], [lat + dLat, lon + dLon])
}

/** Interactive map: every plot as a dot; the selected plot outlined, with one image laid over it. */
export function PlotMap({ plots, selected, focusSite, highlight, overlay, base, contextM, onSelect, onSite, inspect }: Props) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layers = useRef<L.ImageOverlay[]>([]) // overlays on the map: the visible one and newer ones still loading
  const dots = useRef(new Map<string, L.CircleMarker>())
  const view = useRef<L.LatLngBounds | null>(null) // what the map was last fitted to
  const userMoved = useRef(false) // the user panned or zoomed since: a resize must not undo that
  const cb = useRef({ onSelect, onSite, inspect })
  cb.current = { onSelect, onSite, inspect }

  useEffect(() => {
    const m = L.map(el.current!, { maxZoom: 21, zoomSnap: 0.5 }).setView([39.5, -100], 5)
    m.createPane(OVERLAY_PANE).style.zIndex = '350'
    m.on('click', (e) => {
      const ask = cb.current.inspect
      if (!ask) return
      const popup = L.popup().setLatLng(e.latlng).setContent('Reading…').openOn(m)
      ask(e.latlng.lat, e.latlng.lng).then((text) => popup.setContent(text), () => popup.setContent('Could not read this spot.'))
    })
    const moved = () => { userMoved.current = true }
    el.current!.addEventListener('pointerdown', moved)
    el.current!.addEventListener('wheel', moved, { passive: true })
    // The map area changes size with the layout; Leaflet only notices window resizes itself. Until the user
    // moves the map, keep what it was fitted to in view (it may first be laid out at a size of zero).
    const ro = new ResizeObserver(() => {
      m.invalidateSize()
      if (view.current && !userMoved.current) m.fitBounds(view.current, { animate: false })
    })
    ro.observe(el.current!)
    map.current = m
    return () => { ro.disconnect(); m.remove(); map.current = null; layers.current = [] }
  }, [])

  // The base map. Tiles of both are kept by the browser, so switching back and forth is quick.
  useEffect(() => {
    const m = map.current
    if (!m) return
    const { url, ...options } = BASE_MAPS[base]
    const tiles = L.tileLayer(url, { ...options, maxZoom: 21 }).addTo(m)
    return () => { tiles.remove() }
  }, [base])

  // Plot dots and site labels, and the view: all plots, one site, or the selected plot with its surroundings.
  useEffect(() => {
    const m = map.current
    if (!m || plots.length === 0) return
    const layer = L.layerGroup().addTo(m)
    dots.current.clear()
    for (const p of plots) {
      if (p.plot_id === selected?.plot_id) continue
      const dot = L.circleMarker([p.lat, p.lon], { ...DOT, bubblingMouseEvents: false })
        .bindTooltip(`Plot ${p.plot_id}`, { direction: 'top', offset: [0, -6] })
        .on('click', () => cb.current.onSelect(p.plot_id))
        .addTo(layer)
      dots.current.set(p.plot_id, dot)
    }
    if (!selected) {
      // one label per site, beside its plots; at the wide view its dots overlap, so the label is the way in
      for (const { site, plots: ps } of bySite(plots)) {
        const north = Math.max(...ps.map((p) => p.lat)), west = Math.min(...ps.map((p) => p.lon))
        L.marker([north, west], {
          icon: L.divIcon({ className: 'site-label', html: `<span>${site}</span><small>${ps.length} plots</small>`, iconSize: undefined, iconAnchor: [-10, 34] }),
          keyboard: false, title: `Zoom to site ${site}`,
        }).on('click', () => cb.current.onSite(site)).addTo(layer)
      }
    }
    let target: L.LatLngBounds
    if (selected) {
      L.rectangle(square(selected.lat, selected.lon, selected.half_m), { color: '#ffd400', weight: 2.5, fill: false, interactive: false }).addTo(layer)
      target = square(selected.lat, selected.lon, contextM)
    } else {
      const shown = plots.filter((p) => !focusSite || p.site === focusSite)
      target = L.latLngBounds(shown.map((p) => [p.lat, p.lon])).pad(focusSite ? 0.15 : 0.25)
    }
    view.current = target
    userMoved.current = false
    m.fitBounds(target)
    return () => { layer.remove() }
  }, [plots, selected, focusSite, contextM])

  // Emphasise the plot hovered in the list.
  useEffect(() => {
    const dot = highlight ? dots.current.get(highlight) : undefined
    if (!dot) return
    dot.setStyle(DOT_HOT).setRadius(DOT_HOT.radius).bringToFront().openTooltip()
    return () => { dot.setStyle(DOT).setRadius(DOT.radius).closeTooltip() }
  }, [highlight, plots, selected])

  // The overlay image. A new one replaces the old only once it has loaded, so stepping through dates does not flicker.
  const url = overlay?.url ?? null
  useEffect(() => {
    const m = map.current
    if (!m) return
    m.closePopup()
    if (!overlay) {
      layers.current.forEach((l) => l.remove())
      layers.current = []
      return
    }
    const next = L.imageOverlay(overlay.url, overlay.bounds, { pane: OVERLAY_PANE, opacity: overlay.opacity ?? 1, className: overlay.crisp ? 'crisp' : '' })
    const settle = () => {
      const at = layers.current.indexOf(next)
      layers.current.splice(0, Math.max(at, 0)).forEach((l) => l.remove())
    }
    next.once('load', settle).once('error', settle).addTo(m)
    layers.current.push(next)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url])

  // Leaflet adds its own classes to this element, so React must not rewrite className: toggle ours directly.
  const inspectable = inspect !== undefined
  useEffect(() => { el.current!.classList.toggle('inspectable', inspectable) }, [inspectable])

  return <div ref={el} className="map" />
}
