import { fromBlob } from 'geotiff';
import Map from 'ol/Map.js';
import View from 'ol/View.js';
import TileLayer from 'ol/layer/Tile.js';
import WebGLTileLayer from 'ol/layer/WebGLTile.js';
import { transform, transformExtent } from 'ol/proj.js';
import GeoTIFF from 'ol/source/GeoTIFF.js';
import OSM from 'ol/source/OSM.js';
import { useEffect, useRef, useState } from 'react';
import { useLanguage } from '../../contexts/LanguageContext';
import 'ol/ol.css';

const MAP_PROJECTION = 'EPSG:3857';
const PALETTE = ['#c47a36', '#ead287', '#78b9a0', '#347fc1', '#203e7d'] as const;
const MOISTURE_BAND = ['band', 1];

export default function SoilRasterMap({ file }: { file: File }) {
  const { language, t: { soilMoisture: { raster: labels } } } = useLanguage();
  const target = useRef<HTMLDivElement>(null);
  const resetView = useRef<(() => void) | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [selection, setSelection] = useState<number | 'empty' | 'error' | null>(null);
  const percent = new Intl.NumberFormat(language, { style: 'percent', maximumFractionDigits: 1 });

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let map: Map | undefined;
    let overlay: WebGLTileLayer | undefined;
    let firstFitObserver: ResizeObserver | undefined;
    let selectionId = 0;

    async function openRaster() {
      if (!target.current) return;
      const tiff = await fromBlob(file, signal);
      const image = await tiff.getImage();
      const bandCount = image.getSamplesPerPixel();
      if (bandCount !== 1 && bandCount !== 3) throw new Error('Unsupported band count');
      const moistureBand = bandCount === 3 ? 3 : 1;
      const noData = image.getGDALNoData() ?? -9999;
      if (signal.aborted || !target.current) return;
      const source = new GeoTIFF({
        sources: [{ blob: file, bands: [moistureBand], nodata: noData }],
        normalize: false,
        interpolate: false,
        transition: 0,
      });
      const { extent, projection } = await source.getView();
      if (signal.aborted || !target.current) return;
      if (!extent || !extent.every(Number.isFinite) || !projection) throw new Error('Missing georeferencing');
      const mapExtent = transformExtent(extent, projection, MAP_PROJECTION, 8);
      if (!mapExtent.every(Number.isFinite)) throw new Error('Unsupported projection');

      overlay = new WebGLTileLayer({
        source,
        style: {
          color: [
            'case',
            ['all', ['>', ['band', 2], 0], ['>=', MOISTURE_BAND, 0], ['<=', MOISTURE_BAND, 1]],
            ['interpolate', ['linear'], MOISTURE_BAND,
              0, PALETTE[0], 0.125, PALETTE[1], 0.25, PALETTE[2],
              0.375, PALETTE[3], 0.5, PALETTE[4]],
            [0, 0, 0, 0],
          ],
        },
      });
      const view = new View({ projection: MAP_PROJECTION, maxZoom: 22 });
      const mapTarget = target.current;
      map = new Map({
        target: mapTarget,
        view,
        layers: [new TileLayer({ source: new OSM(), maxZoom: 20 }), overlay],
      });
      resetView.current = () => view.fit(mapExtent, { padding: [25, 25, 25, 25], maxZoom: 19 });
      // Restored tasks can download while the map's tab is still hidden.
      if (mapTarget.clientWidth && mapTarget.clientHeight) {
        resetView.current();
      } else {
        firstFitObserver = new ResizeObserver(() => {
          if (signal.aborted || !mapTarget.clientWidth || !mapTarget.clientHeight) return;
          firstFitObserver?.disconnect();
          map?.updateSize();
          resetView.current?.();
        });
        firstFitObserver.observe(mapTarget);
      }
      source.on('tileloaderror', () => {
        if (!signal.aborted) setStatus('error');
      });
      source.once('tileloadend', () => {
        if (!signal.aborted) setStatus((state) => state === 'loading' ? 'ready' : state);
      });
      map.once('rendercomplete', () => {
        if (!signal.aborted) setStatus((state) => state === 'loading' ? 'ready' : state);
      });
      map.on('singleclick', async (event) => {
        const requestId = ++selectionId;
        try {
          const [x, y] = transform(event.coordinate, MAP_PROJECTION, projection);
          const [originX, originY] = image.getOrigin();
          const [stepX, stepY] = image.getResolution();
          const col = Math.floor((x - originX) / stepX);
          const row = Math.floor((y - originY) / stepY);
          const outside = col < 0 || col >= image.getWidth() || row < 0 || row >= image.getHeight();
          const value = outside ? NaN : (await image.readRasters({
            window: [col, row, col + 1, row + 1],
            samples: [moistureBand - 1],
            interleave: true,
            signal,
          }))[0];
          if (!signal.aborted && requestId === selectionId) {
            setSelection(Number.isFinite(value) && value !== noData && value >= 0 && value <= 1 ? value : 'empty');
          }
        } catch {
          if (!signal.aborted && requestId === selectionId) setSelection('error');
        }
      });
    }

    void openRaster().catch(() => {
      if (!signal.aborted) setStatus('error');
    });
    return () => {
      controller.abort();
      firstFitObserver?.disconnect();
      resetView.current = null;
      map?.dispose();
      overlay?.dispose();
    };
  }, [file]);

  return (
    <div className="soil-raster">
      <div className="soil-raster-bar">
        <button
          type="button"
          className="soil-map-reset"
          onClick={() => resetView.current?.()}
          disabled={status !== 'ready'}
        >
          {labels.reset}
        </button>
      </div>
      <div
        ref={target}
        className="soil-raster-map"
        role="region"
        aria-label={labels.title}
        aria-describedby="soil-raster-reading"
        tabIndex={0}
      />
      {status === 'error' ? (
        <p className="soil-feedback soil-error" id="soil-raster-reading" role="alert">{labels.error}</p>
      ) : (
        <p className="soil-feedback" id="soil-raster-reading" role="status">
          {status === 'loading' ? labels.loading : selection === null ? labels.inspect :
            selection === 'empty' ? labels.noData : selection === 'error' ? labels.pixelError :
              <>{labels.pixelValue} <strong>{percent.format(selection)}</strong></>}
        </p>
      )}
      <div className="soil-raster-legend">
        <span>{labels.legend}</span>
        <div className="soil-raster-scale">
          <div
            className="soil-raster-gradient"
            role="img"
            aria-label={`${percent.format(0)}–${percent.format(0.5)}+`}
            style={{ backgroundImage: `linear-gradient(to right, ${PALETTE.join(', ')})` }}
          />
          <div className="soil-raster-ticks" aria-hidden="true">
            {[0, 0.125, 0.25, 0.375, 0.5].map((value) => (
              <span key={value}>{percent.format(value)}{value === 0.5 ? '+' : ''}</span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
