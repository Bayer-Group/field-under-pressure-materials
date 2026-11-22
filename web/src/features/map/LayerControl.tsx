import type { AerialPhoto, GreennessMap } from '../../api'
import { formatDate, toTime } from '../../format'
import type { MapLayer, TimelineChoice } from '../timeline/PlotTimeline'

interface Props {
  photos: AerialPhoto[] // oldest first
  maps: GreennessMap[] // oldest first
  layer: MapLayer
  photoId: string | null
  mapId: string | null
  onChange: (choice: TimelineChoice) => void
}

/** Card on the map: what is laid over the plot (aerial photo, greenness map or nothing), and buttons to step
 *  to the previous or next date of it, or pick any date. The same choice can be made by dragging on the timeline. */
export function LayerControl({ photos, maps, layer, photoId, mapId, onChange }: Props) {
  if (photos.length === 0 && maps.length === 0) return null
  const photoAt = Math.max(0, photos.findIndex((p) => p.photo_id === photoId))
  const mapAt = Math.max(0, maps.findIndex((m) => m.map_id === mapId))

  const options: { value: MapLayer; label: string; n: number }[] = [
    { value: 'photo', label: 'Aerial photo', n: photos.length },
    { value: 'greenness', label: 'Greenness', n: maps.length },
    { value: 'none', label: 'Off', n: 1 },
  ]
  const stepper = layer === 'photo'
    ? { at: photoAt, items: photos.map((p) => ({ date: p.date, monthOnly: p.month_only })), sub: photos[photoAt].source,
        go: (i: number) => onChange({ layer: 'photo', photoId: photos[i].photo_id }), what: 'photo' }
    : layer === 'greenness'
      ? { at: mapAt, items: maps.map((m) => ({ date: m.date, monthOnly: false })), sub: 'Sentinel-2 satellite, 10 m pixels',
          go: (i: number) => onChange({ layer: 'greenness', mapId: maps[i].map_id }), what: 'greenness map' }
      : null

  return (
    <div className="layer-card" role="group" aria-label="What is shown over the plot">
      <div className="layer-title">On the map</div>
      <div className="segmented small">
        {options.filter((o) => o.n > 0).map((o) => (
          <button key={o.value} aria-pressed={layer === o.value} onClick={() => onChange({ layer: o.value })}>{o.label}</button>
        ))}
      </div>
      {stepper && <DatePicker {...stepper} />}
    </div>
  )
}

interface Dated { date: string; monthOnly: boolean }
const yearOf = (iso: string) => Number(iso.slice(0, 4))
const dayOfYear = (iso: string) => (toTime(iso) - Date.UTC(yearOf(iso), 0, 1)) / 86_400_000
const DAY_MONTH = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })
const MONTH = new Intl.DateTimeFormat('en-GB', { month: 'long', timeZone: 'UTC' })
const dayLabel = (d: Dated) => (d.monthOnly ? MONTH : DAY_MONTH).format(new Date(d.date + 'T00:00:00Z'))

/** Jump to any date in two picks: a year, then one of the dates that year has (switching year keeps the season).
 *  Buttons either side step one date at a time. */
function DatePicker({ at, items, sub, go, what }: { at: number; items: Dated[]; sub: string; go: (i: number) => void; what: string }) {
  const year = yearOf(items[at].date)
  const years = [...new Set(items.map((d) => yearOf(d.date)))]
  const inYear = items.map((d, i) => ({ d, i })).filter(({ d }) => yearOf(d.date) === year)
  const pickYear = (y: number) => {
    const doy = dayOfYear(items[at].date)
    const options = items.map((d, i) => ({ d, i })).filter(({ d }) => yearOf(d.date) === y)
    go(options.reduce((best, o) => (Math.abs(dayOfYear(o.d.date) - doy) < Math.abs(dayOfYear(best.d.date) - doy) ? o : best)).i)
  }
  return (
    <div className="stepper">
      <button aria-label={`Previous ${what}`} title={`Previous ${what}`} disabled={at === 0} onClick={() => go(at - 1)}>‹</button>
      <div className="stepper-text">
        <div className="date-pick">
          <select aria-label={`Year of the ${what}`} value={year} onChange={(e) => pickYear(Number(e.target.value))}>
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
          <select aria-label={`Date of the ${what}`} value={at} onChange={(e) => go(Number(e.target.value))}>
            {inYear.map(({ d, i }) => <option key={i} value={i}>{dayLabel(d)}</option>)}
          </select>
        </div>
        <span aria-live="polite" title={`${sub} · ${formatDate(items[at].date, items[at].monthOnly)}`}>{sub} · {at + 1} of {items.length}</span>
      </div>
      <button aria-label={`Next ${what}`} title={`Next ${what}`} disabled={at === items.length - 1} onClick={() => go(at + 1)}>›</button>
    </div>
  )
}

/** Colour key of the greenness map. Colours: keep in step with NDVI_RAMP in src/cropfit/overlay.py. */
export function NdviLegend() {
  return (
    <div className="ndvi-legend">
      <div className="layer-title">Greenness (NDVI)</div>
      <div className="bar" />
      <div className="ticks"><span>0</span><span>0.2</span><span>0.4</span><span>0.6</span><span>0.8</span><span>1</span></div>
      <div className="ends"><span>bare soil</span><span>dense green</span></div>
      <div className="water"><i />below 0: water or snow</div>
      <div className="hint">Click the map to read one spot</div>
    </div>
  )
}
