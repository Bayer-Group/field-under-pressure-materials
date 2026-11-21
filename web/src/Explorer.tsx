import { useEffect, useRef, useState } from 'react'
import { api, type Plot } from './api'
import { ErrorBoundary } from './ErrorBoundary'
import { LayerControl, NdviLegend } from './features/map/LayerControl'
import { PlotMap, type BaseMap, type MapOverlay } from './features/map/PlotMap'
import { FunctionsPanel } from './features/functions/FunctionsPanel'
import { MicrobiomePanel } from './features/microbiome/MicrobiomePanel'
import { PlotTimeline, type MapLayer, type TimelineChoice } from './features/timeline/PlotTimeline'
import { formatDate } from './format'
import { PlanPanel } from './features/plan/PlanPanel'
import { RiskPanel } from './features/risk/RiskPanel'
import { functionsHref, microbesHref, navigate, planHref, plotHref, riskHref, type MicrobeView, type PlotTab } from './router'
import { bySite, formatLatLon, shortId, siteName } from './sites'
import { useFetch } from './useFetch'

// How far around the plot the map shows: aerial photos cover about 120-240 m, greenness maps 1 km.
const CONTEXT_M: Record<MapLayer, number> = { photo: 130, greenness: 1050, none: 130 }

/** Map of all plots beside a panel. With no plot chosen the panel lists the plots by site; once one is chosen
 *  it has one tab per kind of plot data: the timeline (greenness, visits, aerial photos; the image chosen on it
 *  is laid over the map), the soil microbiome, the soil characteristics, the crop disease risk and the products to consider. Panels for future backend results become further tabs. */
const tabHref = (tab: PlotTab, id: string) => (tab === 'microbes' ? microbesHref(id) : tab === 'risk' ? riskHref(id) : tab === 'plan' ? planHref(id) : tab === 'functions' ? functionsHref(id) : plotHref(id))

export function Explorer({ plotId, tab, sampleId, unit, crop, view }: {
  plotId: string | null; tab: PlotTab; sampleId: string | null; unit: string | null; crop: string | null; view: MicrobeView
}) {
  const plots = useFetch('plots', api.plots)
  const photos = useFetch(plotId, (s) => api.aerial(plotId!, s))
  const maps = useFetch(plotId, (s) => api.greennessMaps(plotId!, s))
  const greenness = useFetch(plotId, (s) => api.greenness(plotId!, s))
  const events = useFetch(plotId, (s) => api.plotEvents(plotId!, s))
  const [focusSite, setFocusSite] = useState<string | null>(null)
  const [highlight, setHighlight] = useState<string | null>(null)

  // What the user chose on the timeline for this plot. Until they choose: the most recent photo and map,
  // showing the photo if there is one.
  const [chosen, setChosen] = useState<{ plotId: string } & TimelineChoice>()
  const mine = chosen && chosen.plotId === plotId ? chosen : undefined
  const photoList = photos.data ?? [], mapList = maps.data ?? []
  const photo = photoList.find((p) => p.photo_id === mine?.photoId) ?? photoList.at(-1) ?? null
  const gmap = mapList.find((m) => m.map_id === mine?.mapId) ?? mapList.at(-1) ?? null
  let layer: MapLayer = mine?.layer ?? (photo ? 'photo' : gmap ? 'greenness' : 'none')
  if ((layer === 'photo' && !photo) || (layer === 'greenness' && !gmap)) layer = 'none'
  const choose = (c: TimelineChoice) => setChosen({ ...mine, ...c, plotId: plotId! })

  const overlay: MapOverlay | null =
    layer === 'photo' ? { url: photo!.url, bounds: photo!.bounds }
    : layer === 'greenness' ? { url: gmap!.url, bounds: gmap!.bounds, crisp: true, opacity: 0.85 }
    : null
  const inspect = layer === 'greenness'
    ? async (lat: number, lon: number) => {
        const { ndvi } = await api.greennessAt(gmap!.map_id, lat, lon)
        return ndvi === null
          ? `No reading here on ${formatDate(gmap!.date)} (cloud, or outside the map).`
          : `Greenness here on ${formatDate(gmap!.date)}: <b>${ndvi.toFixed(2)}</b>`
      }
    : undefined

  const selected = plots.data?.find((p) => p.plot_id === plotId) ?? null
  // Under a greenness map the base is orthophotos, so greenness is read against the real ground, not a drawn map.
  const baseMap: BaseMap = selected && layer === 'greenness' ? 'imagery' : 'streets'
  // Only the plot list gates the whole panel; greenness/photo/event errors belong to the greenness tab,
  // so a missing satellite or aerial table does not hide the microbes and crop risk tabs.
  const error = plots.error
  const timelineError = photos.error ?? maps.error ?? greenness.error ?? events.error
  const loading = greenness.loading || events.loading || photos.loading || maps.loading
  const open = (id: string) => { setHighlight(null); navigate(tabHref(tab, id)) }

  return (
    <main className={`explorer ${selected ? 'has-plot' : ''}`}>
      <section className="panel">
        {error ? (
          <p className="message error">Could not load data: {error}</p>
        ) : !plotId ? (
          <Overview plots={plots.data} focusSite={focusSite} onFocusSite={setFocusSite} onHighlight={setHighlight} />
        ) : plots.data && !selected ? (
          <p className="message">Plot {plotId} was not found. <a href="#/">Back to all plots</a></p>
        ) : !selected ? (
          <p className="message">Loading…</p>
        ) : (
          <>
            <PlotHead plot={selected} plots={plots.data!} tab={tab} onOpen={open} />
            {/* an error in one tab leaves the plot head, the other tabs and the map usable */}
            <ErrorBoundary key={`${selected.plot_id}/${tab}`}>
            {tab === 'microbes' ? (
              <MicrobiomePanel plotId={selected.plot_id} sampleId={sampleId} view={view} />
            ) : tab === 'risk' ? (
              <RiskPanel plotId={selected.plot_id} unit={unit} crop={crop} />
            ) : tab === 'plan' ? (
              <PlanPanel plotId={selected.plot_id} unit={unit} crop={crop} />
            ) : tab === 'functions' ? (
              <FunctionsPanel plotId={selected.plot_id} sampleId={sampleId} />
            ) : timelineError ? (
              <p className="message error">Could not load data: {timelineError}</p>
            ) : loading ? (
              <p className="message">Loading…</p>
            ) : (
              <PlotTimeline
                points={greenness.data ?? []} events={events.data ?? []} photos={photoList} maps={mapList}
                layer={layer} photoId={photo?.photo_id ?? null} mapId={gmap?.map_id ?? null} onChange={choose}
              />
            )}
            </ErrorBoundary>
          </>
        )}
      </section>
      <section className="map-area" aria-label="Map">
        <PlotMap
          plots={plots.data ?? []} selected={selected} focusSite={focusSite} highlight={highlight}
          overlay={selected ? overlay : null} contextM={CONTEXT_M[layer]}
          base={baseMap}
          onSelect={open} onSite={setFocusSite} inspect={selected ? inspect : undefined}
        />
        {selected && !loading && (
          <LayerControl photos={photoList} maps={mapList} layer={layer}
            photoId={photo?.photo_id ?? null} mapId={gmap?.map_id ?? null} onChange={choose} />
        )}
        {selected && layer === 'greenness' && <NdviLegend />}
      </section>
    </main>
  )
}

/** The panel with no plot chosen: what this is, and every plot by site. */
function Overview({ plots, focusSite, onFocusSite, onHighlight }: {
  plots: Plot[] | null; focusSite: string | null; onFocusSite: (s: string | null) => void; onHighlight: (id: string | null) => void
}) {
  if (!plots) return <p className="message">Loading plots…</p>
  const groups = bySite(plots)
  return (
    <div className="overview">
      <h1>Sampled plots</h1>
      <p className="lead">
        {plots.length} plots at {groups.length} {groups.length === 1 ? 'site' : 'sites'}. Choose one to see how green it has
        been over the years, its aerial photos and soil sampling visits, the microbes found in its soil and what
        they can do, and the crop disease risk and products to consider that follow from them.
      </p>
      {groups.map(({ site, plots: ps }) => (
        <section key={site} className={`site-card ${focusSite === site ? 'focused' : ''}`}>
          <div className="site-head">
            <div>
              <h2>{siteName(site)}</h2>
              <span className="muted">Site {site} · {ps.length} plots</span>
            </div>
            <button className="ghost" onClick={() => onFocusSite(focusSite === site ? null : site)}>
              {focusSite === site ? 'Show all sites' : 'Zoom map here'}
            </button>
          </div>
          <ul className="plot-grid" onPointerLeave={() => onHighlight(null)}>
            {ps.map((p) => (
              <li key={p.plot_id}>
                <a href={plotHref(p.plot_id)} title={`Plot ${p.plot_id}`}
                  onPointerEnter={() => onHighlight(p.plot_id)} onFocus={() => onHighlight(p.plot_id)} onBlur={() => onHighlight(null)}>
                  {shortId(p)}
                </a>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

/** Title of a chosen plot, a way to move to another plot, and the tabs. */
function PlotHead({ plot, plots, tab, onOpen }: { plot: Plot; plots: Plot[]; tab: PlotTab; onOpen: (id: string) => void }) {
  const groups = bySite(plots)
  const order = groups.flatMap((g) => g.plots)
  const at = order.findIndex((p) => p.plot_id === plot.plot_id)
  const prev = order[at - 1], next = order[at + 1]
  // On a narrow screen the tab row scrolls sideways: keep the current tab in view.
  const tabs = useRef<HTMLElement>(null)
  useEffect(() => {
    const row = tabs.current, on = row?.querySelector<HTMLElement>('[aria-current]')
    if (!row || !on) return
    const left = on.offsetLeft - row.offsetLeft, right = left + on.offsetWidth
    if (left < row.scrollLeft) row.scrollLeft = left
    else if (right > row.scrollLeft + row.clientWidth) row.scrollLeft = right - row.clientWidth
  }, [tab])
  return (
    <div className="plot-head">
      <div className="plot-nav">
        <a href="#/" className="back">← All plots</a>
        <div className="plot-switch">
          <button aria-label={prev ? `Previous plot, ${prev.plot_id}` : 'Previous plot'} disabled={!prev} onClick={() => onOpen(prev.plot_id)}>‹</button>
          <select aria-label="Plot" value={plot.plot_id} onChange={(e) => onOpen(e.target.value)}>
            {groups.map((g) => (
              <optgroup key={g.site} label={siteName(g.site)}>
                {g.plots.map((p) => <option key={p.plot_id} value={p.plot_id}>{p.plot_id}</option>)}
              </optgroup>
            ))}
          </select>
          <button aria-label={next ? `Next plot, ${next.plot_id}` : 'Next plot'} disabled={!next} onClick={() => onOpen(next.plot_id)}>›</button>
        </div>
      </div>
      <h1>Plot {plot.plot_id}</h1>
      <p className="muted plot-sub">{siteName(plot.site)} · {formatLatLon(plot.lat, plot.lon)} · {plot.half_m * 2} × {plot.half_m * 2} m (yellow square on the map)</p>
      <nav className="tabs" ref={tabs} aria-label="What to show for this plot">
        <a href={plotHref(plot.plot_id)} aria-current={tab === 'greenness' ? 'page' : undefined}>Greenness over time</a>
        <a href={microbesHref(plot.plot_id)} aria-current={tab === 'microbes' ? 'page' : undefined}>Soil microbes</a>
        <a href={functionsHref(plot.plot_id)} aria-current={tab === 'functions' ? 'page' : undefined}>Soil characteristics</a>
        <a href={riskHref(plot.plot_id)} aria-current={tab === 'risk' ? 'page' : undefined}>Crop disease risk</a>
        <a href={planHref(plot.plot_id)} aria-current={tab === 'plan' ? 'page' : undefined}>Treatment plan</a>
      </nav>
    </div>
  )
}
