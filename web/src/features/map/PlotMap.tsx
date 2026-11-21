import L from 'leaflet'
import { useEffect, useRef } from 'react'
import type { Plot } from '../../api'

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
  overlay: MapOverlay | null
  contextM: number // how far around a selected plot the map shows, in metres
  onSelect: (plotId: string) => void
  /** When given, clicking the map asks for a short text about that spot and shows it in a popup. */
  inspect?: (lat: number, lon: number) => Promise<string>
}

const OVERLAY_PANE = 'overlay-image' // above the base map, below plot outlines and markers

/** Square of `half` metres around a point, as Leaflet bounds. */
function square(lat: number, lon: number, half: number): L.LatLngBounds {
  const dLat = half / 111_320
  const dLon = half / (111_320 * Math.cos((lat * Math.PI) / 180))
  return L.latLngBounds([lat - dLat, lon - dLon], [lat + dLat, lon + dLon])
}

/** Interactive map: every plot as a dot; the selected plot outlined, with one image laid over it. */
export function PlotMap({ plots, selected, overlay, contextM, onSelect, inspect }: Props) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layers = useRef<L.ImageOverlay[]>([]) // overlays on the map: the visible one and newer ones still loading
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect
  const inspectRef = useRef(inspect)
  inspectRef.current = inspect

  useEffect(() => {
    const m = L.map(el.current!, { maxZoom: 21 }).setView([39.5, -100], 5)
    m.createPane(OVERLAY_PANE).style.zIndex = '350'
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxNativeZoom: 19,
      maxZoom: 21,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(m)
    m.on('click', (e) => {
      const ask = inspectRef.current
      if (!ask) return
      const popup = L.popup().setLatLng(e.latlng).setContent('…').openOn(m)
      ask(e.latlng.lat, e.latlng.lng).then((text) => popup.setContent(text), () => popup.setContent('Could not read this spot.'))
    })
    // The map area changes size when the panel below it does; Leaflet only notices window resizes itself.
    const ro = new ResizeObserver(() => m.invalidateSize())
    ro.observe(el.current!)
    map.current = m
    return () => { ro.disconnect(); m.remove(); map.current = null; layers.current = [] }
  }, [])

  // Plot dots, and the view: all plots, or the selected one with its surroundings.
  useEffect(() => {
    const m = map.current
    if (!m || plots.length === 0) return
    const layer = L.layerGroup().addTo(m)
    for (const p of plots) {
      if (p.plot_id === selected?.plot_id) continue
      L.circleMarker([p.lat, p.lon], { radius: 7, color: '#fff', weight: 2, fillColor: '#1f6f43', fillOpacity: 1, bubblingMouseEvents: false })
        .bindTooltip(`Plot ${p.plot_id}`)
        .on('click', () => onSelectRef.current(p.plot_id))
        .addTo(layer)
    }
    if (selected) {
      L.rectangle(square(selected.lat, selected.lon, selected.half_m), { color: '#ffd400', weight: 2, fill: false, interactive: false }).addTo(layer)
      m.fitBounds(square(selected.lat, selected.lon, contextM))
    } else {
      m.fitBounds(L.latLngBounds(plots.map((p) => [p.lat, p.lon])).pad(0.2))
    }
    return () => { layer.remove() }
  }, [plots, selected, contextM])

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
