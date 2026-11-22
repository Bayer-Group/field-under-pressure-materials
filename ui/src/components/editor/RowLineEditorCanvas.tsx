import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Compass, LocateFixed, Minus, Plus } from 'lucide-react';
import { useLanguage } from '../../contexts/LanguageContext';
import type { CropPrefDoc, DraftRow, DraftTree, GeoCoord, ObjectIdString, OrchardBoundaryDoc } from '../../types/orchard';
import {
  buildSatelliteTiles,
  calculateRowTrees,
  geoToLocalMeters,
  localMetersToGeo,
  snapEndpointAngle,
  type CalculatedRowResult,
  type Vec2,
} from '../../utils/orchardGeometry';
import { getZoomModifierLabel } from '../../utils/platform';

export type EditorToolMode = 'draw' | 'select' | 'paint';
export type CanvasBackdropMode = 'blank' | 'satellite';

interface RowLineEditorCanvasProps {
  orchard: OrchardBoundaryDoc;
  cropPrefs: CropPrefDoc[];
  activeSpeciesId: ObjectIdString;
  activeSpacingMeters: number;
  edgeMarginMeters: number;
  angleSnapEnabled: boolean;
  toolMode: EditorToolMode;
  backdropMode: CanvasBackdropMode;
  calculatedRows: CalculatedRowResult[];
  selectedRowId: string | null;
  selectedTreeKey: { rowId: string; indexInRow: number } | null;
  onAddRow: (start: GeoCoord, end: GeoCoord) => void;
  onUpdateRowEndpoints: (rowId: string, start: GeoCoord, end: GeoCoord) => void;
  onSelectRow: (rowId: string | null) => void;
  onSelectTree: (tree: DraftTree | null) => void;
  onPaintTree: (rowId: string, indexInRow: number) => void;
  onPaintRow: (rowId: string) => void;
}

interface ViewState {
  /** World-center in local meters (x East, y North) */
  centerX: number;
  centerY: number;
  /** Zoom factor in SVG units per meter */
  ppm: number;
}

export function RowLineEditorCanvas({
  orchard,
  cropPrefs,
  activeSpeciesId,
  activeSpacingMeters,
  edgeMarginMeters,
  angleSnapEnabled,
  toolMode,
  backdropMode,
  calculatedRows,
  selectedRowId,
  selectedTreeKey,
  onAddRow,
  onUpdateRowEndpoints,
  onSelectRow,
  onSelectTree,
  onPaintTree,
  onPaintRow,
}: RowLineEditorCanvasProps) {
  const { t, language } = useLanguage();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [viewportSize, setViewportSize] = useState({ width: 900, height: 560 });

  const polygonLocal = useMemo<Vec2[]>(
    () => orchard.geometry.map((g) => geoToLocalMeters(g, orchard.center)),
    [orchard.geometry, orchard.center],
  );

  const bounds = useMemo(() => {
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const p of polygonLocal) {
      if (p.x < minX) minX = p.x;
      if (p.x > maxX) maxX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.y > maxY) maxY = p.y;
    }
    return { minX, maxX, minY, maxY };
  }, [polygonLocal]);

  const computeFitView = useCallback(
    (w: number, h: number): ViewState => {
      const spanX = Math.max(20, bounds.maxX - bounds.minX);
      const spanY = Math.max(20, bounds.maxY - bounds.minY);
      const padFactor = 0.76;
      const ppm = Math.min((w * padFactor) / spanX, (h * padFactor) / spanY);
      return {
        centerX: (bounds.minX + bounds.maxX) / 2,
        centerY: (bounds.minY + bounds.maxY) / 2,
        ppm: Math.max(1.5, Math.min(24, ppm)),
      };
    },
    [bounds],
  );

  const [view, setView] = useState<ViewState>(() => computeFitView(900, 560));
  const [hasInitializedFit, setHasInitializedFit] = useState(false);

  // Drawing, panning, and endpoint-dragging state
  const [drawStartLocal, setDrawStartLocal] = useState<Vec2 | null>(null);
  const [cursorLocal, setCursorLocal] = useState<Vec2 | null>(null);
  const [shiftHeld, setShiftHeld] = useState(false);
  const [isPaintingDrag, setIsPaintingDrag] = useState(false);
  const [panDrag, setPanDrag] = useState<{ startClientX: number; startClientY: number; origCenterX: number; origCenterY: number } | null>(null);
  const [endpointDrag, setEndpointDrag] = useState<{ rowId: string; which: 'start' | 'end' } | null>(null);
  const [hoveredTree, setHoveredTree] = useState<DraftTree | null>(null);
  const [failedTiles, setFailedTiles] = useState<Record<string, boolean>>({});
  const [showZoomHint, setShowZoomHint] = useState<boolean>(false);
  const zoomHintTimerRef = useRef<number | null>(null);

  const minPpm = useMemo(
    () => Math.max(0.65, computeFitView(viewportSize.width, viewportSize.height).ppm * 0.58),
    [computeFitView, viewportSize.width, viewportSize.height],
  );
  const zoomMod = getZoomModifierLabel();

  // Observe container resize
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const parent = svg.parentElement;
    if (!parent) return;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = Math.max(320, Math.round(entry.contentRect.width));
        const h = Math.max(340, Math.round(entry.contentRect.height));
        setViewportSize({ width: w, height: h });
        if (!hasInitializedFit) {
          setView(computeFitView(w, h));
          setHasInitializedFit(true);
        }
      }
    });
    ro.observe(parent);
    return () => ro.disconnect();
  }, [computeFitView, hasInitializedFit]);

  // Keyboard shortcuts (Escape cancels drawing, Shift toggles snap)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Shift') setShiftHeld(true);
      if (e.key === 'Escape') {
        setDrawStartLocal(null);
        setEndpointDrag(null);
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key === 'Shift') setShiftHeld(false);
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, []);

  // Cancel active draw when switching away from draw tool
  useEffect(() => {
    if (toolMode !== 'draw') {
      setDrawStartLocal(null);
    }
  }, [toolMode]);

  const cropPrefById = useMemo(() => {
    const map = new Map<ObjectIdString, CropPrefDoc>();
    for (const c of cropPrefs) map.set(c._id, c);
    return map;
  }, [cropPrefs]);

  // Reference angle of the most recent row for intuitive parallel snapping
  const referenceRowAngleRad = useMemo<number | null>(() => {
    const last = calculatedRows[calculatedRows.length - 1];
    if (!last) return null;
    const a = geoToLocalMeters(last.row.start, orchard.center);
    const b = geoToLocalMeters(last.row.end, orchard.center);
    if (Math.hypot(b.x - a.x, b.y - a.y) < 0.5) return null;
    return Math.atan2(b.y - a.y, b.x - a.x);
  }, [calculatedRows, orchard.center]);

  // Coordinate conversions between local meters (East+, North+) and SVG viewport pixels
  const localToScreen = useCallback(
    (pt: Vec2): { sx: number; sy: number } => ({
      sx: viewportSize.width / 2 + (pt.x - view.centerX) * view.ppm,
      sy: viewportSize.height / 2 - (pt.y - view.centerY) * view.ppm,
    }),
    [viewportSize, view],
  );

  const clientToLocal = useCallback(
    (clientX: number, clientY: number): Vec2 => {
      const svg = svgRef.current;
      if (!svg) return { x: 0, y: 0 };
      const rect = svg.getBoundingClientRect();
      const sx = clientX - rect.left;
      const sy = clientY - rect.top;
      return {
        x: view.centerX + (sx - viewportSize.width / 2) / view.ppm,
        y: view.centerY - (sy - viewportSize.height / 2) / view.ppm,
      };
    },
    [viewportSize, view],
  );

  // Live rubber-band preview calculation while drawing a new row
  const draftEndLocal = useMemo<Vec2 | null>(() => {
    if (!drawStartLocal || !cursorLocal) return null;
    if (angleSnapEnabled || shiftHeld) {
      return snapEndpointAngle(drawStartLocal, cursorLocal, referenceRowAngleRad);
    }
    return cursorLocal;
  }, [drawStartLocal, cursorLocal, angleSnapEnabled, shiftHeld, referenceRowAngleRad]);

  const draftPreview = useMemo<CalculatedRowResult | null>(() => {
    if (!drawStartLocal || !draftEndLocal) return null;
    const tempRow: DraftRow = {
      id: '__draft__',
      label: 'DRAFT',
      start: localMetersToGeo(drawStartLocal, orchard.center),
      end: localMetersToGeo(draftEndLocal, orchard.center),
      averageSpacingMeters: activeSpacingMeters,
      species: activeSpeciesId,
      treeSpeciesOverrides: {},
    };
    return calculateRowTrees(tempRow, calculatedRows.length, polygonLocal, orchard.center, edgeMarginMeters);
  }, [
    drawStartLocal,
    draftEndLocal,
    orchard.center,
    activeSpacingMeters,
    activeSpeciesId,
    calculatedRows.length,
    polygonLocal,
    edgeMarginMeters,
  ]);

  // Satellite tiles covering extended field bounds
  const satelliteTiles = useMemo(() => {
    if (backdropMode !== 'satellite') return [];
    const padMeters = 120;
    return buildSatelliteTiles(
      orchard.center,
      { x: bounds.minX - padMeters, y: bounds.minY - padMeters },
      { x: bounds.maxX + padMeters, y: bounds.maxY + padMeters },
      18,
    );
  }, [backdropMode, orchard.center, bounds]);

  // Metric blueprint gridlines
  const gridLines = useMemo(() => {
    if (backdropMode !== 'blank') return { vertical: [] as number[], horizontal: [] as number[] };
    const halfW = viewportSize.width / (2 * view.ppm);
    const halfH = viewportSize.height / (2 * view.ppm);
    const step = view.ppm > 7 ? 5 : view.ppm > 3.5 ? 10 : 20;

    const xStart = Math.floor((view.centerX - halfW) / step) * step;
    const xEnd = Math.ceil((view.centerX + halfW) / step) * step;
    const yStart = Math.floor((view.centerY - halfH) / step) * step;
    const yEnd = Math.ceil((view.centerY + halfH) / step) * step;

    const vertical: number[] = [];
    for (let x = xStart; x <= xEnd; x += step) vertical.push(x);

    const horizontal: number[] = [];
    for (let y = yStart; y <= yEnd; y += step) horizontal.push(y);

    return { vertical, horizontal };
  }, [backdropMode, viewportSize, view]);

  // Dynamic scale bar length in meters
  const scaleBar = useMemo(() => {
    const candidates = [5, 10, 20, 25, 50, 100];
    const targetPx = 96;
    let chosen = 20;
    for (const m of candidates) {
      if (m * view.ppm >= targetPx * 0.65) {
        chosen = m;
        break;
      }
      chosen = m;
    }
    return { meters: chosen, widthPx: chosen * view.ppm };
  }, [view.ppm]);

  const polygonPointsAttr = useMemo(
    () =>
      polygonLocal
        .map((p) => {
          const { sx, sy } = localToScreen(p);
          return `${sx.toFixed(1)},${sy.toFixed(1)}`;
        })
        .join(' '),
    [polygonLocal, localToScreen],
  );

  // Even-odd mask path to slightly dim satellite area outside the orchard polygon
  const satelliteOuterMaskPath = useMemo(() => {
    const outer = `M 0 0 H ${viewportSize.width} V ${viewportSize.height} H 0 Z`;
    if (polygonLocal.length < 3) return outer;
    const inner =
      polygonLocal
        .map((p, idx) => {
          const { sx, sy } = localToScreen(p);
          return `${idx === 0 ? 'M' : 'L'} ${sx.toFixed(1)} ${sy.toFixed(1)}`;
        })
        .join(' ') + ' Z';
    return `${outer} ${inner}`;
  }, [viewportSize, polygonLocal, localToScreen]);

  // Require Cmd/Ctrl + scroll to zoom; plain scroll scrolls the page naturally
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;

    const handleNativeWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) {
        setShowZoomHint(true);
        if (zoomHintTimerRef.current !== null) {
          window.clearTimeout(zoomHintTimerRef.current);
        }
        zoomHintTimerRef.current = window.setTimeout(() => setShowZoomHint(false), 1400);
        return;
      }

      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.14 : 0.88;
      const rect = svg.getBoundingClientRect();
      const sx = event.clientX - rect.left;
      const sy = event.clientY - rect.top;

      setView((prev) => {
        const pointerX = prev.centerX + (sx - viewportSize.width / 2) / prev.ppm;
        const pointerY = prev.centerY - (sy - viewportSize.height / 2) / prev.ppm;
        const nextPpm = Math.max(minPpm, Math.min(30, prev.ppm * factor));
        const nextCenterX = pointerX - (sx - viewportSize.width / 2) / nextPpm;
        const nextCenterY = pointerY + (sy - viewportSize.height / 2) / nextPpm;
        return { centerX: nextCenterX, centerY: nextCenterY, ppm: nextPpm };
      });
    };

    svg.addEventListener('wheel', handleNativeWheel, { passive: false });
    return () => {
      svg.removeEventListener('wheel', handleNativeWheel);
      if (zoomHintTimerRef.current !== null) {
        window.clearTimeout(zoomHintTimerRef.current);
      }
    };
  }, [viewportSize.width, viewportSize.height, minPpm]);

  const handlePointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    // Middle or right mouse button -> pan viewport
    if (event.button === 1 || event.button === 2) {
      event.preventDefault();
      if (event.button === 2 && drawStartLocal) {
        setDrawStartLocal(null);
        return;
      }
      setPanDrag({
        startClientX: event.clientX,
        startClientY: event.clientY,
        origCenterX: view.centerX,
        origCenterY: view.centerY,
      });
      return;
    }

    if (event.button !== 0) return;

    const localPt = clientToLocal(event.clientX, event.clientY);

    if (toolMode === 'draw') {
      if (!drawStartLocal) {
        setDrawStartLocal(localPt);
        setCursorLocal(localPt);
      } else {
        const finalEnd =
          angleSnapEnabled || shiftHeld
            ? snapEndpointAngle(drawStartLocal, localPt, referenceRowAngleRad)
            : localPt;

        const len = Math.hypot(finalEnd.x - drawStartLocal.x, finalEnd.y - drawStartLocal.y);
        if (len >= 1.0) {
          onAddRow(
            localMetersToGeo(drawStartLocal, orchard.center),
            localMetersToGeo(finalEnd, orchard.center),
          );
        }
        setDrawStartLocal(null);
      }
    } else if (toolMode === 'paint') {
      setIsPaintingDrag(true);
    } else if (toolMode === 'select') {
      // Clicking empty canvas clears selection & allows panning with left-drag
      onSelectRow(null);
      onSelectTree(null);
      setPanDrag({
        startClientX: event.clientX,
        startClientY: event.clientY,
        origCenterX: view.centerX,
        origCenterY: view.centerY,
      });
    }
  };

  const handlePointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const localPt = clientToLocal(event.clientX, event.clientY);
    setCursorLocal(localPt);

    if (panDrag) {
      const dxPx = event.clientX - panDrag.startClientX;
      const dyPx = event.clientY - panDrag.startClientY;
      setView((prev) => ({
        ...prev,
        centerX: panDrag.origCenterX - dxPx / prev.ppm,
        centerY: panDrag.origCenterY + dyPx / prev.ppm,
      }));
      return;
    }

    if (endpointDrag) {
      const target = calculatedRows.find((r) => r.row.id === endpointDrag.rowId);
      if (target) {
        const anchorLocal = geoToLocalMeters(
          endpointDrag.which === 'start' ? target.row.end : target.row.start,
          orchard.center,
        );
        const movedLocal =
          angleSnapEnabled || shiftHeld
            ? snapEndpointAngle(anchorLocal, localPt, null)
            : localPt;
        const movedGeo = localMetersToGeo(movedLocal, orchard.center);
        if (endpointDrag.which === 'start') {
          onUpdateRowEndpoints(target.row.id, movedGeo, target.row.end);
        } else {
          onUpdateRowEndpoints(target.row.id, target.row.start, movedGeo);
        }
      }
    }
  };

  const handlePointerUp = () => {
    setPanDrag(null);
    setEndpointDrag(null);
    setIsPaintingDrag(false);
  };

  const activeSpecies = cropPrefById.get(activeSpeciesId);
  const activeColor = activeSpecies?.colorHex ?? '#16a34a';
  const cursorGeo = cursorLocal ? localMetersToGeo(cursorLocal, orchard.center) : null;

  const canvasCursorClass =
    panDrag || endpointDrag
      ? 'is-grabbing'
      : toolMode === 'draw'
        ? 'is-crosshair'
        : toolMode === 'paint'
          ? 'is-paint'
          : 'is-select';

  return (
    <div className={`editor-canvas-frame ${backdropMode === 'satellite' ? 'is-satellite' : 'is-blank'}`}>
      <svg
        ref={svgRef}
        className={`editor-svg ${canvasCursorClass}`}
        width={viewportSize.width}
        height={viewportSize.height}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={() => {
          setPanDrag(null);
          setIsPaintingDrag(false);
          setHoveredTree(null);
        }}
        onContextMenu={(e) => e.preventDefault()}
      >
        <defs>
          {/* Fallback satellite-style organic ground pattern if offline */}
          <pattern id="satFallbackPattern" width="36" height="36" patternUnits="userSpaceOnUse">
            <rect width="36" height="36" fill="#233324" />
            <circle cx="8" cy="10" r="2.2" fill="#2e442f" opacity="0.65" />
            <circle cx="24" cy="22" r="3" fill="#1d2b1e" opacity="0.55" />
            <path d="M 0 18 L 36 18" stroke="#2c3f2c" strokeWidth="1" opacity="0.45" />
          </pattern>
        </defs>

        {/* Backdrop: Satellite Imagery OR Blueprint Metric Grid */}
        {backdropMode === 'satellite' ? (
          <g>
            <rect width={viewportSize.width} height={viewportSize.height} fill="url(#satFallbackPattern)" />
            {/* Live tile backdrop outside local raster bounds (or fallback when no local asset is provided) */}
            {satelliteTiles.map((tile) => {
              if (failedTiles[tile.key]) return null;
              const topLeft = localToScreen({ x: tile.xMin, y: tile.yMax });
              const bottomRight = localToScreen({ x: tile.xMax, y: tile.yMin });
              const w = bottomRight.sx - topLeft.sx;
              const h = bottomRight.sy - topLeft.sy;
              if (w <= 0 || h <= 0) return null;
              return (
                <image
                  key={tile.key}
                  href={tile.url}
                  x={topLeft.sx}
                  y={topLeft.sy}
                  width={w + 0.6}
                  height={h + 0.6}
                  preserveAspectRatio="none"
                  onError={() =>
                    setFailedTiles((prev) => (prev[tile.key] ? prev : { ...prev, [tile.key]: true }))
                  }
                />
              );
            })}
            {/* Exact georeferenced EPSG:4326 satellite image downloaded for this orchard parcel */}
            {orchard.satelliteOverlay &&
              (() => {
                const { bounds: satBounds, imageUrl } = orchard.satelliteOverlay;
                const nwLocal = geoToLocalMeters(
                  { lat: satBounds.northLat, lng: satBounds.westLng },
                  orchard.center,
                );
                const seLocal = geoToLocalMeters(
                  { lat: satBounds.southLat, lng: satBounds.eastLng },
                  orchard.center,
                );
                const topLeft = localToScreen(nwLocal);
                const bottomRight = localToScreen(seLocal);
                const w = bottomRight.sx - topLeft.sx;
                const h = bottomRight.sy - topLeft.sy;
                if (w <= 0 || h <= 0) return null;
                return (
                  <image
                    href={imageUrl}
                    x={topLeft.sx}
                    y={topLeft.sy}
                    width={w}
                    height={h}
                    preserveAspectRatio="none"
                  />
                );
              })()}
            {/* Dim area outside the orchard polygon so field shape stands out cleanly */}
            <path
              d={satelliteOuterMaskPath}
              fill="rgba(7, 13, 23, 0.42)"
              fillRule="evenodd"
              pointerEvents="none"
            />
          </g>
        ) : (
          <g pointerEvents="none">
            {gridLines.vertical.map((x) => {
              const { sx } = localToScreen({ x, y: 0 });
              const isMajor = Math.abs(x) % 20 === 0;
              return (
                <line
                  key={`vx-${x}`}
                  x1={sx}
                  y1={0}
                  x2={sx}
                  y2={viewportSize.height}
                  className={isMajor ? 'editor-grid-major' : 'editor-grid-minor'}
                />
              );
            })}
            {gridLines.horizontal.map((y) => {
              const { sy } = localToScreen({ x: 0, y });
              const isMajor = Math.abs(y) % 20 === 0;
              return (
                <line
                  key={`hy-${y}`}
                  x1={0}
                  y1={sy}
                  x2={viewportSize.width}
                  y2={sy}
                  className={isMajor ? 'editor-grid-major' : 'editor-grid-minor'}
                />
              );
            })}
          </g>
        )}

        {/* Orchard Field Polygon Geometry */}
        <polygon
          points={polygonPointsAttr}
          className={backdropMode === 'satellite' ? 'orchard-polygon-satellite' : 'orchard-polygon-blank'}
          pointerEvents="none"
        />

        {/* Orchard boundary corner vertices */}
        {polygonLocal.map((pt, idx) => {
          const { sx, sy } = localToScreen(pt);
          return (
            <circle
              key={`vtx-${idx}`}
              cx={sx}
              cy={sy}
              r={3.2}
              className="orchard-vertex-dot"
              pointerEvents="none"
            />
          );
        })}

        {/* Committed Drawn Rows & Calculated Trees */}
        {calculatedRows.map((calc) => {
          const isSelected = calc.row.id === selectedRowId;
          const startScreen = localToScreen(geoToLocalMeters(calc.row.start, orchard.center));
          const endScreen = localToScreen(geoToLocalMeters(calc.row.end, orchard.center));
          const rowSpecies = cropPrefById.get(calc.row.species);
          const rowColor = rowSpecies?.colorHex ?? '#16a34a';

          return (
            <g key={calc.row.id}>
              {/* Full drawn straight line (faded dashed outside polygon) */}
              <line
                x1={startScreen.sx}
                y1={startScreen.sy}
                x2={endScreen.sx}
                y2={endScreen.sy}
                stroke={rowColor}
                strokeWidth={isSelected ? 2.4 : 1.5}
                strokeDasharray="5 5"
                opacity={0.42}
                pointerEvents="none"
              />

              {/* Wide transparent hit target for clicking/painting the row */}
              <line
                x1={startScreen.sx}
                y1={startScreen.sy}
                x2={endScreen.sx}
                y2={endScreen.sy}
                stroke="transparent"
                strokeWidth={14}
                style={{ cursor: toolMode === 'draw' ? 'crosshair' : 'pointer' }}
                onPointerDown={(e) => {
                  if (e.button !== 0 || toolMode === 'draw') return;
                  e.stopPropagation();
                  if (toolMode === 'paint') {
                    onPaintRow(calc.row.id);
                  } else {
                    onSelectRow(calc.row.id);
                    onSelectTree(null);
                  }
                }}
              />

              {/* Active inside-polygon clipped segments */}
              {calc.clippedSegments.map((seg, segIdx) => {
                const aS = localToScreen(seg.a);
                const bS = localToScreen(seg.b);
                return (
                  <line
                    key={`${calc.row.id}-seg-${segIdx}`}
                    x1={aS.sx}
                    y1={aS.sy}
                    x2={bS.sx}
                    y2={bS.sy}
                    stroke={isSelected ? '#38bdf8' : rowColor}
                    strokeWidth={isSelected ? 3.2 : 2.1}
                    strokeLinecap="round"
                    opacity={0.92}
                    pointerEvents="none"
                  />
                );
              })}

              {/* Row label pill near start endpoint */}
              <g
                transform={`translate(${startScreen.sx - 18}, ${startScreen.sy - 14})`}
                pointerEvents="none"
              >
                <rect
                  x={-14}
                  y={-10}
                  width={32}
                  height={17}
                  rx={5}
                  className={`row-label-bg${isSelected ? ' is-selected' : ''}`}
                />
                <text x={2} y={2} textAnchor="middle" className="row-label-text">
                  {calc.row.label}
                </text>
              </g>

              {/* Calculated Individual Trees along the row */}
              {calc.trees.map((tree) => {
                const pos = localToScreen(geoToLocalMeters(tree.coordinates, orchard.center));
                const speciesColor = cropPrefById.get(tree.species)?.colorHex ?? rowColor;
                const isTreeSelected =
                  selectedTreeKey?.rowId === tree.rowId &&
                  selectedTreeKey?.indexInRow === tree.indexInRow;
                const dotRadius = Math.max(3.6, Math.min(7.5, view.ppm * 0.72));

                return (
                  <g key={tree.tempId}>
                    {isTreeSelected && (
                      <circle
                        cx={pos.sx}
                        cy={pos.sy}
                        r={dotRadius + 4.5}
                        fill="none"
                        stroke="#38bdf8"
                        strokeWidth={2}
                        pointerEvents="none"
                      />
                    )}
                    <circle
                      cx={pos.sx}
                      cy={pos.sy}
                      r={dotRadius}
                      fill={speciesColor}
                      stroke={backdropMode === 'satellite' ? '#ffffff' : 'var(--bg-surface)'}
                      strokeWidth={1.6}
                      style={{ cursor: toolMode === 'draw' ? 'crosshair' : 'pointer' }}
                      onPointerEnter={() => {
                        setHoveredTree(tree);
                        if (toolMode === 'paint' && isPaintingDrag) {
                          onPaintTree(tree.rowId, tree.indexInRow);
                        }
                      }}
                      onPointerLeave={() => setHoveredTree(null)}
                      onPointerDown={(e) => {
                        if (e.button !== 0 || toolMode === 'draw') return;
                        e.stopPropagation();
                        if (toolMode === 'paint') {
                          setIsPaintingDrag(true);
                          onPaintTree(tree.rowId, tree.indexInRow);
                        } else {
                          onSelectRow(tree.rowId);
                          onSelectTree(tree);
                        }
                      }}
                    />
                  </g>
                );
              })}

              {/* Draggable Start / End handles when row is selected in Select mode */}
              {isSelected && toolMode === 'select' && (
                <>
                  {(
                    [
                      { which: 'start', pos: startScreen, tag: 'A' },
                      { which: 'end', pos: endScreen, tag: 'B' },
                    ] as const
                  ).map((handle) => (
                    <g
                      key={handle.which}
                      transform={`translate(${handle.pos.sx}, ${handle.pos.sy})`}
                      style={{ cursor: 'move' }}
                      onPointerDown={(e) => {
                        if (e.button !== 0) return;
                        e.stopPropagation();
                        setEndpointDrag({ rowId: calc.row.id, which: handle.which });
                      }}
                    >
                      <circle r={9} fill="#0ea5e9" stroke="#ffffff" strokeWidth={2} />
                      <text y={3.5} textAnchor="middle" fill="#ffffff" fontSize="9.5" fontWeight="700">
                        {handle.tag}
                      </text>
                    </g>
                  ))}
                </>
              )}
            </g>
          );
        })}

        {/* Live Rubber-Band Row Drawing Preview */}
        {drawStartLocal && draftEndLocal && draftPreview && (
          <g pointerEvents="none">
            {(() => {
              const aS = localToScreen(drawStartLocal);
              const bS = localToScreen(draftEndLocal);
              return (
                <>
                  <line
                    x1={aS.sx}
                    y1={aS.sy}
                    x2={bS.sx}
                    y2={bS.sy}
                    stroke={activeColor}
                    strokeWidth={1.8}
                    strokeDasharray="6 4"
                    opacity={0.65}
                  />
                  {draftPreview.clippedSegments.map((seg, idx) => {
                    const sA = localToScreen(seg.a);
                    const sB = localToScreen(seg.b);
                    return (
                      <line
                        key={`draft-seg-${idx}`}
                        x1={sA.sx}
                        y1={sA.sy}
                        x2={sB.sx}
                        y2={sB.sy}
                        stroke={activeColor}
                        strokeWidth={3}
                        strokeLinecap="round"
                      />
                    );
                  })}
                  {draftPreview.trees.map((tree) => {
                    const pos = localToScreen(geoToLocalMeters(tree.coordinates, orchard.center));
                    return (
                      <circle
                        key={`draft-tree-${tree.indexInRow}`}
                        cx={pos.sx}
                        cy={pos.sy}
                        r={Math.max(3.4, Math.min(6.8, view.ppm * 0.68))}
                        fill={activeColor}
                        stroke="#ffffff"
                        strokeWidth={1.5}
                        opacity={0.92}
                      />
                    );
                  })}
                  <circle cx={aS.sx} cy={aS.sy} r={5.5} fill={activeColor} stroke="#ffffff" strokeWidth={2} />
                  <circle cx={bS.sx} cy={bS.sy} r={5} fill="#ffffff" stroke={activeColor} strokeWidth={2.2} />

                  {/* Live measurement pill near cursor */}
                  <g transform={`translate(${Math.min(viewportSize.width - 150, bS.sx + 14)}, ${Math.max(26, bS.sy - 26)})`}>
                    <rect x={0} y={0} width={144} height={24} rx={7} fill="rgba(15, 23, 42, 0.88)" />
                    <text x={72} y={15.5} textAnchor="middle" fill="#f8fafc" fontSize="11.5" fontWeight="600">
                      {draftPreview.insideLengthMeters.toFixed(1)} m · {draftPreview.trees.length}{' '}
                      {t.rowEditor.treesUnit}
                    </text>
                  </g>
                </>
              );
            })()}
          </g>
        )}
      </svg>

      {/* Top-left empty-orchard onboarding hint */}
      {calculatedRows.length === 0 && !drawStartLocal && (
        <div className="editor-empty-banner">
          <strong>{t.rowEditor.emptyOrchardBadge}</strong>
          <span>{t.rowEditor.emptyOrchardGuide}</span>
        </div>
      )}

      {showZoomHint && (
        <div className="map-zoom-hint-toast" role="status">
          {t.orchard3d.zoomModifierHint.replace('{mod}', zoomMod)}
        </div>
      )}

      {/* Top-right floating zoom controls & North indicator */}
      <div className="editor-map-controls">
        <div className="editor-compass" title="North">
          <Compass size={15} />
          <span>N</span>
        </div>
        <div className="editor-zoom-stack">
          <button
            type="button"
            className="editor-zoom-btn"
            onClick={() => setView((v) => ({ ...v, ppm: Math.min(30, v.ppm * 1.25) }))}
            aria-label="Zoom in"
          >
            <Plus size={15} />
          </button>
          <button
            type="button"
            className="editor-zoom-btn"
            onClick={() => setView((v) => ({ ...v, ppm: Math.max(minPpm, v.ppm * 0.8) }))}
            aria-label="Zoom out"
          >
            <Minus size={15} />
          </button>
          <button
            type="button"
            className="editor-zoom-btn"
            onClick={() => setView(computeFitView(viewportSize.width, viewportSize.height))}
            title={t.rowEditor.fitView}
            aria-label={t.rowEditor.fitView}
          >
            <LocateFixed size={15} />
          </button>
        </div>
      </div>

      {/* Bottom-left metric scale bar & live coordinates */}
      <div className="editor-hud-bottom-left">
        <div className="scale-bar-box">
          <div className="scale-bar-line" style={{ width: `${Math.round(scaleBar.widthPx)}px` }} />
          <span>{scaleBar.meters} m</span>
        </div>
        {cursorGeo && (
          <span className="cursor-coords-chip">
            {cursorGeo.lat.toFixed(6)}°N, {cursorGeo.lng.toFixed(6)}°E
          </span>
        )}
      </div>

      {/* Bottom-right hovered tree tooltip or interaction hint */}
      <div className="editor-hud-bottom-right">
        {hoveredTree ? (
          (() => {
            const sp = cropPrefById.get(hoveredTree.species);
            const spName = sp
              ? `${language === 'pl' ? sp.namePl : sp.nameEn} (${sp.variety})`
              : hoveredTree.species;
            return (
              <span className="hovered-tree-hud">
                <span className="species-dot-sm" style={{ backgroundColor: sp?.colorHex ?? '#16a34a' }} />
                <strong>#{hoveredTree.indexInRow + 1}</strong> · {spName} ·{' '}
                {hoveredTree.coordinates.lat.toFixed(5)}, {hoveredTree.coordinates.lng.toFixed(5)}
              </span>
            );
          })()
        ) : (
          <span>
            {drawStartLocal
              ? t.rowEditor.hintFinishLine
              : toolMode === 'draw'
                ? t.rowEditor.hintDrawMode.replace('{mod}', zoomMod)
                : toolMode === 'paint'
                  ? t.rowEditor.hintPaintMode
                  : t.rowEditor.hintSelectMode}
          </span>
        )}
      </div>

      {/* Satellite imagery attribution when satellite backdrop is active */}
      {backdropMode === 'satellite' && (
        <div className="satellite-attribution">
          {orchard.satelliteOverlay?.sourceLabel ?? 'Imagery © Esri World Imagery'}
        </div>
      )}
    </div>
  );
}
