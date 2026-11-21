import { useEffect, useRef, useState } from 'react'
import type { AerialPhoto, EventSummary, GreennessMap, GreennessPoint, MicrobiomeSample } from '../../api'
import { formatDate, toTime } from '../../format'
import { eventHref, microbesHref } from '../../router'

/** What is laid over the map. */
export type MapLayer = 'photo' | 'greenness' | 'none'
export interface TimelineChoice {
  layer?: MapLayer
  photoId?: string
  mapId?: string
}

interface Props {
  plotId: string
  points: GreennessPoint[]
  events: EventSummary[]
  photos: AerialPhoto[] // oldest first
  maps: GreennessMap[] // oldest first
  metagenomes: MicrobiomeSample[] // soil DNA (metagenome) samples of the plot
  layer: MapLayer
  photoId: string | null // the chosen photo (kept while another layer is shown)
  mapId: string | null // the chosen greenness map
  onChange: (choice: TimelineChoice) => void
}

const PLOT_H = 220 // height of the dot plot itself
const M = { top: 34, right: 14, left: 58 } // top margin holds the row of visit markers; left the row names
const YEARS_H = 24 // row of year labels under the plot
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

/** Index in `xs` (ascending) nearest to `px`. */
const nearestIndex = (xs: number[], px: number) => xs.reduce((best, v, i) => (Math.abs(v - px) < Math.abs(xs[best] - px) ? i : best), 0)
const svgX = (e: React.PointerEvent<Element>) => e.clientX - (e.currentTarget as SVGElement).closest('svg')!.getBoundingClientRect().left

/** Props that turn an SVG group into a slider over `xs` (pixel positions of its stops, ascending). */
function slider(xs: number[], index: number, pick: (i: number) => void) {
  return {
    role: 'slider', tabIndex: 0, 'aria-valuemin': 0, 'aria-valuemax': xs.length - 1, 'aria-valuenow': index,
    onPointerDown: (e: React.PointerEvent<SVGGElement>) => { e.currentTarget.setPointerCapture(e.pointerId); pick(nearestIndex(xs, svgX(e))) },
    onPointerMove: (e: React.PointerEvent<SVGGElement>) => { if (e.buttons & 1) pick(nearestIndex(xs, svgX(e))) },
    onKeyDown: (e: React.KeyboardEvent) => {
      const to = { ArrowLeft: index - 1, ArrowDown: index - 1, ArrowRight: index + 1, ArrowUp: index + 1, Home: 0, End: xs.length - 1 }[e.key]
      if (to === undefined) return
      e.preventDefault()
      pick(Math.max(0, Math.min(xs.length - 1, to)))
    },
  }
}

/** One time axis for a plot, and a control for what the map shows.
 *  Top row: soil sampling visits (links to their details). Middle: dot plot of satellite greenness; pointing at it
 *  reads the nearest observation, dragging across it chooses the day whose greenness map is on the map. Bottom row:
 *  aerial photos; dragging along it chooses the photo. A line marks the chosen date. Dashed lines mark the days
 *  soil DNA was sequenced (metagenomics); their markers on the axis open that sample's microbes. Future time-based data gets
 *  a row here. */
export function PlotTimeline({ plotId, points, events, photos, maps, metagenomes, layer, photoId, mapId, onChange }: Props) {
  const [ref, width] = useWidth()
  const [hoverAt, setHoverAt] = useState<number | null>(null) // index into points
  const photoAt = Math.max(0, photos.findIndex((p) => p.photo_id === photoId))
  const mapAt = Math.max(0, maps.findIndex((m) => m.map_id === mapId))
  const photo = photos[photoAt], gmap = maps[mapAt]

  // one mark per day with a metagenome (a day can have more than one)
  const dna = metagenomes.filter((m, i, all) => all.findIndex((o) => o.date === m.date) === i)
  const times = [...points, ...events, ...photos, ...dna].map((d) => toTime(d.date))
  const first = points[0], last = points.at(-1)
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
    const yr0 = new Date(t0).getUTCFullYear(), yr1 = new Date(t1).getUTCFullYear()
    const yearLines: number[] = [], yearLabels: number[] = []
    for (let yr = yr0; yr <= yr1; yr++) {
      if (yr > yr0) yearLines.push(yr)
      // a year is labelled at its middle, if the middle is on the axis
      if (Date.UTC(yr, 6, 1) >= t0 && Date.UTC(yr, 6, 1) <= t1) yearLabels.push(yr)
    }
    const step = Math.max(1, Math.ceil((yearLabels.length * 40) / (width - M.left - M.right)))
    const pointX = points.map((p) => x(toTime(p.date)))
    const photoX = photos.map((p) => x(toTime(p.date)))
    const mapX = maps.map((m) => x(toTime(m.date)))
    const hovered = hoverAt !== null ? points[hoverAt] : null
    const dots = points.map((p, i) => <circle key={i} className="dot" cx={pointX[i]} cy={y(p.ndvi)} r={2.8} />)
    const plotHover = {
      onPointerMove: (e: React.PointerEvent<SVGElement>) => { if (points.length) setHoverAt(nearestIndex(pointX, svgX(e))) },
      onPointerLeave: () => setHoverAt(null),
    }
    body = (
      <svg width={width} height={bottom + YEARS_H + LANE_H} role="group" aria-label="Greenness, sampling visits, metagenomics and aerial photos over time">
        {[0, 0.25, 0.5, 0.75, 1].map((v) => (
          <g key={v}>
            <line className={v === 0 ? 'baseline' : 'grid'} x1={M.left} x2={width - M.right} y1={y(v)} y2={y(v)} />
            <text className="tick" x={M.left - 8} y={y(v)} textAnchor="end" dominantBaseline="middle">{v}</text>
          </g>
        ))}
        <text className="axis-title" transform={`translate(12 ${M.top + PLOT_H / 2}) rotate(-90)`} textAnchor="middle">Greenness (NDVI)</text>
        {yearLines.map((yr) => (
          <line key={yr} className="grid" x1={x(Date.UTC(yr, 0, 1))} x2={x(Date.UTC(yr, 0, 1))} y1={M.top} y2={bottom + 6} />
        ))}
        {yearLabels.map((yr, i) => i % step === 0 && (
          <text key={yr} className="tick" x={x(Date.UTC(yr, 6, 1))} y={bottom + 16} textAnchor="middle">{yr}</text>
        ))}
        {points.length === 0 && (
          <text className="tick" x={(M.left + width - M.right) / 2} y={M.top + PLOT_H / 2} textAnchor="middle">No satellite greenness data for this plot yet</text>
        )}

        <text className="row-name" x={M.left - 8} y={M.top - 13} textAnchor="end" dominantBaseline="middle">Visits</text>
        {layer === 'photo' && photo && <line className="cursor photo" x1={photoX[photoAt]} x2={photoX[photoAt]} y1={M.top} y2={laneY} />}
        {layer === 'greenness' && gmap && <line className="cursor greenness" x1={mapX[mapAt]} x2={mapX[mapAt]} y1={M.top} y2={bottom} />}
        {dna.map((m) => {
          const mx = x(toTime(m.date))
          return <line key={m.sample_id} className="dna-line" x1={mx} x2={mx} y1={M.top} y2={bottom} />
        })}
        {maps.length > 0 ? (
          <g
            className="map-scrub" aria-label="Day of the greenness map shown on the map"
            aria-valuetext={layer === 'greenness' ? formatDate(gmap.date) : 'not shown'}
            {...slider(mapX, mapAt, (i) => onChange({ layer: 'greenness', mapId: maps[i].map_id }))} {...plotHover}
          >
            <rect className="hit" x={M.left} y={M.top} width={width - M.left - M.right} height={PLOT_H} />
            {dots}
          </g>
        ) : (
          <g {...plotHover}>
            <rect className="hit" x={M.left} y={M.top} width={width - M.left - M.right} height={PLOT_H} />
            {dots}
          </g>
        )}
        {hovered && (
          <g className="hover-mark" pointerEvents="none">
            <line x1={pointX[hoverAt!]} x2={pointX[hoverAt!]} y1={M.top} y2={bottom} />
            <circle cx={pointX[hoverAt!]} cy={y(hovered.ndvi)} r={5} />
          </g>
        )}
        {events.map((e) => {
          const ex = x(toTime(e.date))
          return (
            <a key={e.event_id} href={eventHref(e.event_id)} className="visit" aria-label={`Soil sampling on ${formatDate(e.date)}: open details`}>
              <title>{`Soil sampling on ${formatDate(e.date)}: click for details`}</title>
              <line className="visit-line" x1={ex} x2={ex} y1={M.top - 4} y2={bottom} />
              <rect x={ex - 7} y={M.top - 24} width={14} height={20} className="hit" />
              <path d={`M${ex},${M.top - 19} l6,6 l-6,6 l-6,-6 z`} />
            </a>
          )
        })}
        {dna.map((m) => {
          const mx = x(toTime(m.date))
          return (
            <a key={m.sample_id} href={microbesHref(plotId, m.sample_id)} className="dna" aria-label={`Soil DNA sequenced (metagenomics), sampled ${formatDate(m.date)}: open its microbes`}>
              <title>{`Metagenomics: soil sampled ${formatDate(m.date)}. Click to see its microbes`}</title>
              <rect x={mx - 7} y={bottom - 8} width={14} height={16} className="hit" />
              <path d={`M${mx},${bottom - 2} l5,8 l-10,0 z`} />
            </a>
          )
        })}
        {photos.length > 0 && (
          <>
            <text className="row-name" x={M.left - 8} y={laneY} textAnchor="end" dominantBaseline="middle">Photos</text>
            <g
              className="photo-lane" aria-label="Aerial photo shown on the map"
              aria-valuetext={layer === 'photo' ? formatDate(photo.date, photo.month_only) : 'not shown'}
              {...slider(photoX, photoAt, (i) => onChange({ layer: 'photo', photoId: photos[i].photo_id }))}
            >
              <rect className="hit" x={M.left - 6} y={laneY - LANE_H / 2} width={width - M.left - M.right + 12} height={LANE_H} />
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
          </>
        )}
      </svg>
    )
  }

  const hovered = hoverAt !== null ? points[hoverAt] : null
  return (
    <div className="chart">
      <div className="chart-head">
        <div>
          <h2>Greenness over time</h2>
          <p className="chart-sub">
            {points.length > 0
              ? <>{points.length} cloud-free satellite readings, {formatDate(first!.date)} to {formatDate(last!.date)}. 0 is bare soil, 1 dense green growth.</>
              : 'Satellite readings of how green the plot is.'}
          </p>
        </div>
      </div>
      <div className="legend">
        <span><i className="key-dot" />Satellite reading</span>
        {events.length > 0 && <span><i className="key-visit" />Soil sampling visit ({events.length}): point to see its date, click for details</span>}
        {dna.length > 0 && <span><i className="key-dna" />Metagenomics, soil DNA sequenced ({dna.length}): click the marker for its microbes</span>}
        {photos.length > 0 && <span><i className="key-photo" />Aerial photo ({photos.length})</span>}
      </div>
      <p className="readout" aria-live="polite">
        {hovered
          ? <><b>{hovered.ndvi.toFixed(2)}</b> greenness on {formatDate(hovered.date)}</>
          : points.length > 0 ? 'Point at the chart to read a value.' : ' '}
      </p>
      <div ref={ref}>{body}</div>
      {(maps.length > 0 || photos.length > 0) && (
        <p className="hint">
          {maps.length > 0 && <>Drag across the chart to put that day’s greenness map on the map. </>}
          {photos.length > 0 && <>Drag along the photo row to change the aerial photo. </>}
          Arrow keys work too once a row is focused.
        </p>
      )}
    </div>
  )
}
