import { useState } from 'react'
import { api } from './api'
import { PlotMap, type MapOverlay } from './features/map/PlotMap'
import { PlotTimeline, type MapLayer, type TimelineChoice } from './features/timeline/PlotTimeline'
import { formatDate } from './format'
import { navigate, plotHref } from './router'
import { useFetch } from './useFetch'

// How far around the plot the map shows: aerial photos cover about 120-240 m, greenness maps 1 km.
const CONTEXT_M: Record<MapLayer, number> = { photo: 130, greenness: 1050, none: 130 }

/** Map of all plots; once a plot is chosen, its timeline below (greenness, visits, aerial photos) and the
 *  image chosen on that timeline laid over the map. Panels for future backend results (recommendations etc.)
 *  belong in the plot panel next to the timeline. */
export function Explorer({ plotId }: { plotId: string | null }) {
  const plots = useFetch('plots', api.plots)
  const photos = useFetch(plotId, (s) => api.aerial(plotId!, s))
  const maps = useFetch(plotId, (s) => api.greennessMaps(plotId!, s))
  const greenness = useFetch(plotId, (s) => api.greenness(plotId!, s))
  const events = useFetch(plotId, (s) => api.plotEvents(plotId!, s))

  // What the user chose on the timeline for this plot. Until they choose: the most recent photo and map,
  // showing the photo if there is one.
  const [chosen, setChosen] = useState<{ plotId: string } & TimelineChoice>()
  const mine = chosen && chosen.plotId === plotId ? chosen : undefined
  const photoList = photos.data ?? [], mapList = maps.data ?? []
  const photo = photoList.find((p) => p.photo_id === mine?.photoId) ?? photoList.at(-1) ?? null
  const gmap = mapList.find((m) => m.map_id === mine?.mapId) ?? mapList.at(-1) ?? null
  let layer: MapLayer = mine?.layer ?? (photo ? 'photo' : gmap ? 'greenness' : 'none')
  if ((layer === 'photo' && !photo) || (layer === 'greenness' && !gmap)) layer = 'none'

  const overlay: MapOverlay | null =
    layer === 'photo' ? { url: photo!.url, bounds: photo!.bounds }
    : layer === 'greenness' ? { url: gmap!.url, bounds: gmap!.bounds, crisp: true, opacity: 0.85 }
    : null
  const inspect = layer === 'greenness'
    ? async (lat: number, lon: number) => {
        const { ndvi } = await api.greennessAt(gmap!.map_id, lat, lon)
        return ndvi === null
          ? `No reading here on ${formatDate(gmap!.date)} (cloud, or outside the map).`
          : `Greenness here on ${formatDate(gmap!.date)}: ${ndvi.toFixed(2)}`
      }
    : undefined

  const selected = plots.data?.find((p) => p.plot_id === plotId) ?? null
  const error = plots.error ?? photos.error ?? maps.error ?? greenness.error ?? events.error
  const loading = greenness.loading || events.loading || photos.loading || maps.loading

  return (
    <main className="explorer">
      <section className="map-area">
        <PlotMap
          plots={plots.data ?? []} selected={selected} overlay={selected ? overlay : null} contextM={CONTEXT_M[layer]}
          onSelect={(id) => navigate(plotHref(id))} inspect={selected ? inspect : undefined}
        />
        {selected && layer === 'greenness' && (
          <div className="ndvi-legend">
            <div className="bar" />
            <div className="ends"><span>bare soil</span><span>dense green</span></div>
            <div className="hint">Click the map to read a spot</div>
          </div>
        )}
      </section>
      <section className="panel">
        {error ? (
          <p className="message error">Could not load data: {error}</p>
        ) : !plotId ? (
          <p className="message">{plots.loading ? 'Loading plots…' : 'Select a plot on the map to see how green it has been over time.'}</p>
        ) : plots.data && !selected ? (
          <p className="message">Plot {plotId} was not found. <a href="#/">Back to the map</a></p>
        ) : (
          <>
            <div className="panel-head">
              <h1>Plot {plotId}</h1>
              <a href="#/">All plots</a>
            </div>
            {loading ? (
              <p className="message">Loading…</p>
            ) : (
              <PlotTimeline
                points={greenness.data ?? []} events={events.data ?? []} photos={photoList} maps={mapList}
                layer={layer} photoId={photo?.photo_id ?? null} mapId={gmap?.map_id ?? null}
                onChange={(c) => setChosen({ ...mine, ...c, plotId })}
              />
            )}
          </>
        )}
      </section>
    </main>
  )
}
