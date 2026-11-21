import { useEffect, useRef, useState } from 'react'
import type { AerialPhoto, EventSummary, GreennessMap, GreennessPoint } from '../../api'
import { formatDate, toTime } from '../../format'
import { eventHref } from '../../router'

/** What is laid over the map. */
export type MapLayer = 'photo' | 'greenness' | 'none'
export interface TimelineChoice {
  layer?: MapLayer
  photoId?: string
  mapId?: string
}

interface Props {
  points: GreennessPoint[]
  events: EventSummary[]
  photos: AerialPhoto[] // oldest first
  maps: GreennessMap[] // oldest first
  layer: MapLayer
  photoId: string | null // the chosen photo (kept while another layer is shown)
  mapId: string | null // the chosen greenness map
  onChange: (choice: TimelineChoice) => void
}

const PLOT_H = 180 // height of the dot plot itself
const M = { top: 34, right: 16, left: 44 } // top margin holds the row of visit markers
const YEARS_H = 22 // row of year labels under the plot
const LANE_H = 30 // row of aerial photo stops under the years

function useWidth() {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)))
    ro.observe(ref.current!)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}

/** Props that turn an SVG group into a slider over `xs` (pixel positions of its stops, ascending). */
function slider(xs: number[], index: number, pick: (i: number) => void) {
  const nearest = (e: React.PointerEvent<SVGGElement>) => {
    const px = e.clientX - e.currentTarget.ownerSVGElement!.getBoundingClientRect().left
    return xs.reduce((best, v, i) => (Math.abs(v - px) < Math.abs(xs[best] - px) ? i : best), 0)
  }
  return {
    role: 'slider', tabIndex: 0, 'aria-valuemin': 0, 'aria-valuemax': xs.length - 1, 'aria-valuenow': index,
    onPointerDown: (e: React.PointerEvent<SVGGElement>) => { e.currentTarget.setPointerCapture(e.pointerId); pick(nearest(e)) },
    onPointerMove: (e: React.PointerEvent<SVGGElement>) => { if (e.buttons & 1) pick(nearest(e)) },
    onKeyDown: (e: React.KeyboardEvent) => {
      const to = { ArrowLeft: index - 1, ArrowDown: index - 1, ArrowRight: index + 1, ArrowUp: index + 1, Home: 0, End: xs.length - 1 }[e.key]
      if (to === undefined) return
      e.preventDefault()
      pick(Math.max(0, Math.min(xs.length - 1, to)))
    },
  }
}

/** One time axis for a plot, and the control for what the map shows.
 *  Top row: soil sampling visits (links to their details). Middle: dot plot of satellite greenness; dragging
 *  across it chooses the day whose greenness map is on the map. Bottom row: aerial photos; dragging along it
 *  chooses the photo. A line marks the chosen date. Future time-based data gets a row here. */
export function PlotTimeline({ points, events, photos, maps, layer, photoId, mapId, onChange }: Props) {
  const [ref, width] = useWidth()
  const photoAt = Math.max(0, photos.findIndex((p) => p.photo_id === photoId))
  const mapAt = Math.max(0, maps.findIndex((m) => m.map_id === mapId))
  const photo = photos[photoAt], gmap = maps[mapAt]

  const times = [...points, ...events, ...photos].map((d) => toTime(d.date))
  let body = null
  if (times.length === 0) {
    body = <p className="message">No data over time for this plot yet.</p>
  } else if (width > 0) {
    const t0 = Math.min(...times), t1 = Math.max(...times)
    const y0 = Math.min(0, ...points.map((p) => p.ndvi)), y1 = 1
    const bottom = M.top + PLOT_H
    const laneY = bottom + YEARS_H + LANE_H / 2
    const x = (t: number) => M.left + ((t - t0) / Math.max(t1 - t0, 1)) * (width - M.left - M.right)
    const y = (v: number) => M.top + (1 - (v - y0) / (y1 - y0)) * PLOT_H
    const years: number[] = []
    for (let yr = new Date(t0).getUTCFullYear() + 1; Date.UTC(yr, 0, 1) <= t1; yr++) years.push(yr)
    const step = Math.max(1, Math.ceil((years.length * 44) / (width - M.left - M.right)))
    const photoX = photos.map((p) => x(toTime(p.date)))
    const mapX = maps.map((m) => x(toTime(m.date)))
    const dots = points.map((p, i) => (
      <circle key={i} className="dot" cx={x(toTime(p.date))} cy={y(p.ndvi)} r={2.6}>
        <title>{`${formatDate(p.date)}: greenness ${p.ndvi.toFixed(2)}`}</title>
      </circle>
    ))
    body = (
      <svg width={width} height={bottom + YEARS_H + LANE_H} role="group" aria-label="Greenness, sampling visits and aerial photos over time">
        {[0, 0.25, 0.5, 0.75, 1].map((v) => (
          <g key={v}>
            <line className="grid" x1={M.left} x2={width - M.right} y1={y(v)} y2={y(v)} />
            <text className="tick" x={M.left - 8} y={y(v)} textAnchor="end" dominantBaseline="middle">{v}</text>
          </g>
        ))}
        {years.map((yr, i) => (
          <g key={yr}>
            <line className="grid" x1={x(Date.UTC(yr, 0, 1))} x2={x(Date.UTC(yr, 0, 1))} y1={M.top} y2={bottom} />
            {i % step === 0 && Date.UTC(yr, 6, 1) <= t1 && (
              <text className="tick" x={x(Date.UTC(yr, 6, 1))} y={bottom + 15} textAnchor="middle">{yr}</text>
            )}
          </g>
        ))}
        {points.length === 0 && (
          <text className="tick" x={(M.left + width - M.right) / 2} y={M.top + PLOT_H / 2} textAnchor="middle">No satellite greenness data for this plot yet</text>
        )}
        {events.map((e) => (
          <line key={e.event_id} className="visit-line" x1={x(toTime(e.date))} x2={x(toTime(e.date))} y1={M.top - 8} y2={bottom} />
        ))}
        {layer === 'photo' && <line className="cursor photo" x1={photoX[photoAt]} x2={photoX[photoAt]} y1={M.top} y2={laneY} />}
        {layer === 'greenness' && <line className="cursor greenness" x1={mapX[mapAt]} x2={mapX[mapAt]} y1={M.top} y2={bottom} />}
        {maps.length > 0 ? (
          <g
            className="map-scrub" aria-label="Day of the greenness map shown on the map"
            aria-valuetext={layer === 'greenness' ? formatDate(gmap.date) : 'hidden'}
            {...slider(mapX, mapAt, (i) => onChange({ layer: 'greenness', mapId: maps[i].map_id }))}
          >
            <rect className="hit" x={M.left} y={M.top} width={width - M.left - M.right} height={PLOT_H} />
            {dots}
          </g>
        ) : dots}
        {events.map((e) => {
          const ex = x(toTime(e.date))
          return (
            <a key={e.event_id} href={eventHref(e.event_id)} className="visit" aria-label={`Soil sampling on ${formatDate(e.date)}: open details`}>
              <title>{`Soil sampling on ${formatDate(e.date)}: click for details`}</title>
              <rect x={ex - 7} y={M.top - 22} width={14} height={18} className="hit" />
              <path d={`M${ex},${M.top - 20} l6,6 l-6,6 l-6,-6 z`} />
            </a>
          )
        })}
        {photos.length > 0 && (
          <g
            className="photo-lane" aria-label="Aerial photo shown on the map"
            aria-valuetext={layer === 'photo' ? formatDate(photo.date, photo.month_only) : 'hidden'}
            {...slider(photoX, photoAt, (i) => onChange({ layer: 'photo', photoId: photos[i].photo_id }))}
          >
            <rect className="hit" x={0} y={laneY - LANE_H / 2} width={width} height={LANE_H} />
            <line className="track" x1={M.left} x2={width - M.right} y1={laneY} y2={laneY} />
            {photos.map((p, i) => {
              const on = layer === 'photo' && i === photoAt
              return (
                <circle key={p.photo_id} className={on ? 'stop on' : 'stop'} cx={photoX[i]} cy={laneY} r={on ? 7 : 4.5}>
                  <title>{`Aerial photo, ${formatDate(p.date, p.month_only)} (${p.source})`}</title>
                </circle>
              )
            })}
          </g>
        )}
      </svg>
    )
  }
  const option = (value: MapLayer, label: React.ReactNode) => (
    <label className={layer === value ? 'on' : ''}>
      <input type="radio" name="map-layer" checked={layer === value} onChange={() => onChange({ layer: value })} />
      {label}
    </label>
  )
  return (
    <div className="chart">
      <div className="chart-head">
        <h2>Greenness over time</h2>
        <div className="legend">
          <span><i className="key-dot" />Satellite observation (0 = bare soil, 1 = dense green)</span>
          <span><i className="key-visit" />Soil sampling visit, click for details</span>
          {photos.length > 0 && <span><i className="key-photo" />Aerial photo</span>}
        </div>
      </div>
      <div ref={ref}>{body}</div>
      {(photos.length > 0 || maps.length > 0) && (
        <div className="layer-choice">
          <span>On the map:</span>
          {photos.length > 0 && option('photo', <>Aerial photo, <b>{formatDate(photo.date, photo.month_only)}</b></>)}
          {maps.length > 0 && option('greenness', <>Greenness map, <b>{formatDate(gmap.date)}</b></>)}
          {option('none', 'Nothing')}
          <span className="hint">
            {maps.length > 0 && 'Drag across the chart to change the day. '}
            {photos.length > 0 && 'Drag along the bottom row to change the photo.'}
          </span>
        </div>
      )}
    </div>
  )
}
