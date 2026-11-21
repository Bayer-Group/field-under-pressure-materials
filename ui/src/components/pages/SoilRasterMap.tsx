import { fromBlob } from 'geotiff';
import Feature from 'ol/Feature.js';
import Map from 'ol/Map.js';
import View from 'ol/View.js';
import GeoJSON from 'ol/format/GeoJSON.js';
import { isEmpty } from 'ol/extent.js';
import Point from 'ol/geom/Point.js';
import TileLayer from 'ol/layer/Tile.js';
import VectorLayer from 'ol/layer/Vector.js';
import WebGLTileLayer from 'ol/layer/WebGLTile.js';
import { fromLonLat, transform, transformExtent } from 'ol/proj.js';
import GeoTIFF from 'ol/source/GeoTIFF.js';
import OSM from 'ol/source/OSM.js';
import VectorSource from 'ol/source/Vector.js';
import { Circle as CircleStyle, Fill, Stroke, Style } from 'ol/style.js';
import { useEffect, useId, useRef, useState } from 'react';
import type { AnalystField, RasterKind, RiskStatus } from '../../api/analyticsApi';
import { useLanguage } from '../../contexts/LanguageContext';
import { analyticsCopy, USDA_TEXTURE } from '../../i18n/analytics';
import 'ol/ol.css';

const MAP_PROJECTION = 'EPSG:3857';
const COLOR_STOPS = {
  moisture: [[0, '#c47a36'], [0.125, '#ead287'], [0.25, '#78b9a0'], [0.375, '#347fc1'], [0.5, '#203e7d']],
  ndvi: [[-1, '#283e62'], [0, '#b77a50'], [0.25, '#eccd71'], [0.55, '#83b665'], [1, '#185c38']],
  ph: [[4, '#b24b3e'], [5.5, '#dc9d53'], [6.5, '#edce7b'], [7.5, '#82ab74'], [9, '#46788e']],
  texture: [[1, '#78434a'], [2, '#95566e'], [3, '#9a5f46'], [4, '#b77453'], [5, '#ba7e95'], [6, '#c78d5d'],
    [7, '#d5a76f'], [8, '#7b9277'], [9, '#edc184'], [10, '#507a86'], [11, '#e2d098'], [12, '#f7e7b3']],
} as const;
const LIMITS = { moisture: [0, 1], ndvi: [-1, 1], ph: [0, 14], texture: [1, 12] } as const;
const TREE_COLORS: Record<RiskStatus, string> = { high: '#cd3045', watch: '#ba6a12', low: '#188550', insufficient: '#596b80' };
const TREE_STYLES = Object.fromEntries(
  Object.entries(TREE_COLORS).map(([status, color]) => [status, new Style({
    image: new CircleStyle({ radius: status === 'high' ? 8 : 6, fill: new Fill({ color }), stroke: new Stroke({ color: '#fff', width: 2 }) }),
    zIndex: status === 'high' ? 2 : 1,
  })]),
);
const FIELD_STYLE = new Style({
  stroke: new Stroke({ color: '#184f70', width: 2.5 }),
  fill: new Fill({ color: 'rgba(29, 104, 145, .08)' }),
});

interface RasterMapProps {
  file: File | null;
  kind?: RasterKind;
  field?: AnalystField;
  onSelectTree?: (treeId: string) => void;
}

export default function SoilRasterMap({ file, kind = 'moisture', field, onSelectTree }: RasterMapProps) {
  const { language, t: { soilMoisture: { raster: labels } } } = useLanguage();
  const target = useRef<HTMLDivElement>(null);
  const resetView = useRef<(() => void) | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [selection, setSelection] = useState<number | 'empty' | 'error' | null>(null);
  const readingId = useId();
  const stops = COLOR_STOPS[kind];
  const format = new Intl.NumberFormat(language, kind === 'moisture'
    ? { style: 'percent', maximumFractionDigits: 1 }
    : { maximumFractionDigits: 3 });
  const projected = kind === 'moisture' && !!field?.forecast_day;
  const label = kind === 'moisture'
    ? projected ? analyticsCopy[language].forecastMoisture : labels.legend
    : analyticsCopy[language][kind];

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let map: Map | undefined;
    let overlay: WebGLTileLayer | undefined;
    let observer: ResizeObserver | undefined;
    let selectionId = 0;
    setStatus('loading');
    setSelection(null);

    async function prepareRaster(rasterFile: File) {
      const tiff = await fromBlob(rasterFile, signal);
      const image = await tiff.getImage();
      const bandCount = image.getSamplesPerPixel();
      if (bandCount !== 1 && (kind !== 'moisture' || bandCount !== 3)) throw new Error('Unsupported band count');
      const band = bandCount === 3 ? 3 : 1;
      const noData = image.getGDALNoData() ?? -9999;
      const source = new GeoTIFF({
        sources: [{ blob: rasterFile, bands: [band], nodata: noData }],
        normalize: false, interpolate: false, transition: 0,
      });
      const { extent, projection } = await source.getView();
      if (!extent || !extent.every(Number.isFinite) || !projection) throw new Error('Missing georeferencing');
      const mapExtent = transformExtent(extent, projection, MAP_PROJECTION, 8);
      if (!mapExtent.every(Number.isFinite)) throw new Error('Unsupported projection');
      return { image, band, noData, source, projection, mapExtent };
    }

    async function openMap() {
      let raster: Awaited<ReturnType<typeof prepareRaster>> | null = null;
      if (file) {
        try {
          raster = await prepareRaster(file);
        } catch (error) {
          if (!field) throw error;
        }
      }
      const mapTarget = target.current;
      if (signal.aborted || !mapTarget) return;
      const layers: (TileLayer<OSM> | VectorLayer | WebGLTileLayer)[] = [new TileLayer({ source: new OSM(), maxZoom: 20 })];
      const [minimum, maximum] = LIMITS[kind];
      if (raster) {
        overlay = new WebGLTileLayer({
          source: raster.source,
          style: { color: [
            'case',
            ['all', ['>', ['band', 2], 0], ['>=', ['band', 1], minimum], ['<=', ['band', 1], maximum]],
            ['interpolate', ['linear'], ['band', 1], ...stops.flat()],
            [0, 0, 0, 0],
          ] },
        });
        layers.push(overlay);
      }
      let mapExtent = raster?.mapExtent;
      if (field) {
        const outlines = new GeoJSON().readFeatures(field.geometry, { dataProjection: 'EPSG:4326', featureProjection: MAP_PROJECTION });
        const boundary = new VectorSource({ features: outlines });
        const points = field.trees.flatMap((tree) => {
          if (!tree.coordinates) return [];
          const feature = new Feature({ geometry: new Point(fromLonLat(tree.coordinates)), treeId: tree.id });
          feature.setStyle(TREE_STYLES[tree.risk.status]);
          return [feature];
        });
        layers.push(new VectorLayer({ source: boundary, style: FIELD_STYLE }));
        layers.push(new VectorLayer({ source: new VectorSource({ features: points }) }));
        const extent = boundary.getExtent();
        if (extent && !isEmpty(extent)) mapExtent = extent;
      }

      const view = new View({ projection: MAP_PROJECTION, maxZoom: 22 });
      map = new Map({ target: mapTarget, view, layers });
      const extent = mapExtent;
      resetView.current = () => {
        if (extent) view.fit(extent, { padding: [32, 32, 32, 32], maxZoom: 19 });
      };
      if (mapTarget.clientWidth && mapTarget.clientHeight) resetView.current();
      else {
        observer = new ResizeObserver(() => {
          if (signal.aborted || !mapTarget.clientWidth || !mapTarget.clientHeight) return;
          observer?.disconnect();
          map?.updateSize();
          resetView.current?.();
        });
        observer.observe(mapTarget);
      }
      if (raster) {
        const markReady = () => {
          if (!signal.aborted) setStatus((current) => current === 'loading' ? 'ready' : current);
        };
        raster.source.on('tileloaderror', () => {
          if (!signal.aborted) setStatus('error');
        });
        raster.source.once('tileloadend', markReady);
        map.once('rendercomplete', markReady);
      } else {
        setStatus(file ? 'error' : 'ready');
      }

      map.on('singleclick', async (event) => {
        const requestId = ++selectionId;
        const treeId = map?.forEachFeatureAtPixel(event.pixel, (feature) => feature.get('treeId') as string | undefined, { hitTolerance: 4 });
        if (treeId) {
          onSelectTree?.(treeId);
          return;
        }
        if (!raster) return;
        try {
          const { image, projection, band, noData } = raster;
          const [x, y] = transform(event.coordinate, MAP_PROJECTION, projection);
          const [originX, originY] = image.getOrigin();
          const [stepX, stepY] = image.getResolution();
          const col = Math.floor((x - originX) / stepX);
          const row = Math.floor((y - originY) / stepY);
          const outside = col < 0 || col >= image.getWidth() || row < 0 || row >= image.getHeight();
          const value = outside ? NaN : (await image.readRasters({
            window: [col, row, col + 1, row + 1], samples: [band - 1], interleave: true, signal,
          }))[0];
          if (!signal.aborted && requestId === selectionId) {
            const valid = Number.isFinite(value) && value !== noData && value >= minimum && value <= maximum &&
              (kind !== 'texture' || Number.isInteger(value));
            setSelection(valid ? value : 'empty');
          }
        } catch {
          if (!signal.aborted && requestId === selectionId) setSelection('error');
        }
      });
    }

    void openMap().catch(() => {
      if (!signal.aborted) setStatus('error');
    });
    return () => {
      controller.abort();
      observer?.disconnect();
      resetView.current = null;
      map?.dispose();
      overlay?.dispose();
    };
  }, [file, kind, field, onSelectTree, stops]);

  return (
    <div className="soil-raster">
      <div className="soil-raster-bar">
        <button type="button" className="soil-map-reset" onClick={() => resetView.current?.()} disabled={status === 'loading' || !resetView.current}>
          {labels.reset}
        </button>
      </div>
      <div ref={target} className="soil-raster-map" role="region" aria-label={file ? label : labels.title} aria-describedby={status === 'error' || file ? readingId : undefined} tabIndex={0} />
      {status === 'error' ? (
        <p className="soil-feedback soil-error" id={readingId} role="alert">{labels.error}</p>
      ) : file && (
        <p className="soil-feedback" id={readingId} role="status">
          {status === 'loading' ? labels.loading : selection === null ? (
            kind === 'moisture' && !projected ? labels.inspect : analyticsCopy[language].inspectPixel
          ) :
            selection === 'empty' ? labels.noData : selection === 'error' ? labels.pixelError :
              <>{kind === 'moisture' && !projected ? labels.pixelValue : label} <strong>{kind === 'texture' ? USDA_TEXTURE[selection - 1] : format.format(selection)}</strong></>}
        </p>
      )}
      {file && (
        <div className="soil-raster-legend">
          <span>{label}</span>
          {kind === 'texture' ? (
            <div className="analytics-texture-legend">
              {stops.map(([value, color]) => <span key={value}><i style={{ backgroundColor: color }} />{USDA_TEXTURE[value - 1]}</span>)}
            </div>
          ) : <div className="soil-raster-scale">
            <div className="soil-raster-gradient" aria-hidden="true"
              style={{ backgroundImage: `linear-gradient(to right, ${stops.map(([value, color]) => `${color} ${100 * (value - stops[0][0]) / (stops[stops.length - 1][0] - stops[0][0])}%`).join(', ')})` }} />
            <div className="soil-raster-ticks">
              {stops.map(([value], index) => <span key={value}>{format.format(value)}{kind === 'moisture' && index === 4 ? '+' : ''}</span>)}
            </div>
          </div>}
        </div>
      )}
    </div>
  );
}
