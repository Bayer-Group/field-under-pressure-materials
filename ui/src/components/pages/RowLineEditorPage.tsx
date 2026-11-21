import { useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  Code2,
  CopyPlus,
  Magnet,
  Map as MapIcon,
  MousePointer2,
  Paintbrush,
  PencilLine,
  RotateCcw,
  Satellite,
  Save,
  Sprout,
  Trash2,
  Undo2,
} from 'lucide-react';
import {
  fetchCropPrefs,
  fetchOrchardBoundary,
  fetchOrchardTrees,
  saveOrchardLayout,
} from '../../api/orchardApi';
import { useLanguage } from '../../contexts/LanguageContext';
import { useOrchard } from '../../contexts/OrchardContext';
import type {
  CropPrefDoc,
  DraftRow,
  DraftTree,
  GeoCoord,
  ObjectIdString,
  OrchardBoundaryDoc,
  SaveOrchardLayoutResponse,
} from '../../types/orchard';
import {
  buildOrchardLayoutPayload,
  calculateRowTrees,
  createParallelRowEndpoints,
  geoToLocalMeters,
  type CalculatedRowResult,
  type Vec2,
} from '../../utils/orchardGeometry';
import {
  RowLineEditorCanvas,
  type CanvasBackdropMode,
  type EditorToolMode,
} from '../editor/RowLineEditorCanvas';

export function RowLineEditorPage() {
  const { t, language } = useLanguage();
  const { selectedOrchardId } = useOrchard();

  const [orchard, setOrchard] = useState<OrchardBoundaryDoc | null>(null);
  const [cropPrefs, setCropPrefs] = useState<CropPrefDoc[]>([]);
  const [orchardEndpoint, setOrchardEndpoint] = useState<string>('');
  const [cropPrefsEndpoint, setCropPrefsEndpoint] = useState<string>('');

  // Drawing configuration & tools
  const [backdropMode, setBackdropMode] = useState<CanvasBackdropMode>('blank');
  const [toolMode, setToolMode] = useState<EditorToolMode>('draw');
  const [angleSnap, setAngleSnap] = useState<boolean>(true);
  const [activeSpeciesId, setActiveSpeciesId] = useState<ObjectIdString>('');
  const [averageSpacingMeters, setAverageSpacingMeters] = useState<number>(3.5);
  const [parallelOffsetMeters, setParallelOffsetMeters] = useState<number>(4.5);
  const [edgeMarginMeters, setEdgeMarginMeters] = useState<number>(1.0);

  // Drawn rows (starts empty for first-time user!) + undo stack
  const [rows, setRows] = useState<DraftRow[]>([]);
  const [history, setHistory] = useState<DraftRow[][]>([]);
  const [selectedRowId, setSelectedRowId] = useState<string | null>(null);
  const [selectedTreeKey, setSelectedTreeKey] = useState<{ rowId: string; indexInRow: number } | null>(null);

  // Save & JSON payload inspection state
  const [isSaving, setIsSaving] = useState(false);
  const [saveBanner, setSaveBanner] = useState<{
    response: SaveOrchardLayoutResponse;
    endpoint: string;
  } | null>(null);
  const [showPayloadPreview, setShowPayloadPreview] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setRows([]);
    setHistory([]);
    setSelectedRowId(null);
    setSelectedTreeKey(null);
    setSaveBanner(null);

    Promise.all([
      fetchOrchardBoundary(selectedOrchardId, controller.signal),
      fetchCropPrefs(controller.signal),
      fetchOrchardTrees(selectedOrchardId, controller.signal).catch(() => null),
    ])
      .then(([orchardRes, cropsRes, treesRes]) => {
        setOrchard(orchardRes.data);
        setOrchardEndpoint(orchardRes.endpoint);
        setCropPrefs(cropsRes.data);
        setCropPrefsEndpoint(cropsRes.endpoint);

        if (cropsRes.data.length > 0) {
          setActiveSpeciesId((prev) => prev || cropsRes.data[0]._id);
          setAverageSpacingMeters((prev) => prev || cropsRes.data[0].recommendedSpacingMeters);
        }

        // Hydrate pre-existing Orchard.rows with actual Tree.species from MongoDB
        const fallbackSpecies = cropsRes.data[0]?._id ?? '';
        const speciesByTreeId = new Map<string, ObjectIdString>();
        for (const tree of treesRes?.data ?? []) {
          if (tree.species) {
            speciesByTreeId.set(tree.id, tree.species);
          }
        }

        if (orchardRes.data.rows.length > 0) {
          setRows(
            orchardRes.data.rows.map((r) => {
              const treeSpeciesList = r.treeIds.map((tid) => speciesByTreeId.get(tid) ?? fallbackSpecies);
              // Dominant species for the row
              const counts = new Map<string, number>();
              for (const sp of treeSpeciesList) {
                if (sp) counts.set(sp, (counts.get(sp) ?? 0) + 1);
              }
              let dominantSpecies = fallbackSpecies;
              let bestCount = -1;
              for (const [sp, cnt] of counts.entries()) {
                if (cnt > bestCount) {
                  bestCount = cnt;
                  dominantSpecies = sp;
                }
              }

              const treeSpeciesOverrides: Record<number, ObjectIdString> = {};
              treeSpeciesList.forEach((sp, idx) => {
                if (sp && sp !== dominantSpecies) {
                  treeSpeciesOverrides[idx] = sp;
                }
              });

              return {
                id: r.id,
                label: r.label,
                start: r.start,
                end: r.end,
                averageSpacingMeters: r.averageSpacingMeters,
                species: dominantSpecies,
                treeSpeciesOverrides,
              };
            }),
          );
        }
      })
      .catch((err) => {
        if ((err as Error).name !== 'AbortError') {
          console.error('Failed to load orchard geometry or crop preferences:', err);
        }
      });

    return () => controller.abort();
  }, [selectedOrchardId]);

  const cropPrefById = useMemo(() => {
    const map = new Map<ObjectIdString, CropPrefDoc>();
    for (const c of cropPrefs) map.set(c._id, c);
    return map;
  }, [cropPrefs]);

  const polygonLocal = useMemo<Vec2[]>(() => {
    if (!orchard) return [];
    return orchard.geometry.map((g) => geoToLocalMeters(g, orchard.center));
  }, [orchard]);

  // Recalculate all individual tree coordinates whenever rows, spacing, or margin change
  const calculatedRows = useMemo<CalculatedRowResult[]>(() => {
    if (!orchard) return [];
    return rows.map((row, idx) =>
      calculateRowTrees(row, idx, polygonLocal, orchard.center, edgeMarginMeters),
    );
  }, [orchard, rows, polygonLocal, edgeMarginMeters]);

  const totalTreesCount = useMemo(
    () => calculatedRows.reduce((sum, r) => sum + r.trees.length, 0),
    [calculatedRows],
  );

  // Per-species tree counts for summary legend
  const speciesCounts = useMemo(() => {
    const counts = new Map<ObjectIdString, number>();
    for (const calc of calculatedRows) {
      for (const tree of calc.trees) {
        counts.set(tree.species, (counts.get(tree.species) ?? 0) + 1);
      }
    }
    return counts;
  }, [calculatedRows]);

  const selectedTree = useMemo<DraftTree | null>(() => {
    if (!selectedTreeKey) return null;
    const calc = calculatedRows.find((r) => r.row.id === selectedTreeKey.rowId);
    return calc?.trees.find((tr) => tr.indexInRow === selectedTreeKey.indexInRow) ?? null;
  }, [calculatedRows, selectedTreeKey]);

  const selectedRowCalc = useMemo<CalculatedRowResult | null>(
    () => calculatedRows.find((r) => r.row.id === selectedRowId) ?? null,
    [calculatedRows, selectedRowId],
  );

  const layoutPayload = useMemo(() => {
    if (!orchard) return null;
    return buildOrchardLayoutPayload(orchard, calculatedRows);
  }, [orchard, calculatedRows]);

  const commitRowsUpdate = (updater: (prev: DraftRow[]) => DraftRow[]) => {
    setRows((prev) => {
      setHistory((h) => [...h.slice(-24), prev]);
      setSaveBanner(null);
      return updater(prev);
    });
  };

  const handleAddRow = (start: GeoCoord, end: GeoCoord) => {
    if (!activeSpeciesId) return;
    commitRowsUpdate((prev) => {
      const nextNum = prev.length + 1;
      const newRow: DraftRow = {
        id: `row-${Date.now()}-${nextNum}`,
        label: `R-${String(nextNum).padStart(2, '0')}`,
        start,
        end,
        averageSpacingMeters,
        species: activeSpeciesId,
        treeSpeciesOverrides: {},
      };
      setSelectedRowId(newRow.id);
      setSelectedTreeKey(null);
      return [...prev, newRow];
    });
  };

  const handleUpdateRowEndpoints = (rowId: string, start: GeoCoord, end: GeoCoord) => {
    setSaveBanner(null);
    setRows((prev) => prev.map((r) => (r.id === rowId ? { ...r, start, end } : r)));
  };

  const handleDeleteRow = (rowId: string) => {
    commitRowsUpdate((prev) =>
      prev
        .filter((r) => r.id !== rowId)
        .map((r, idx) => ({ ...r, label: `R-${String(idx + 1).padStart(2, '0')}` })),
    );
    if (selectedRowId === rowId) setSelectedRowId(null);
    if (selectedTreeKey?.rowId === rowId) setSelectedTreeKey(null);
  };

  const handlePaintTree = (rowId: string, indexInRow: number) => {
    if (!activeSpeciesId) return;
    commitRowsUpdate((prev) =>
      prev.map((r) => {
        if (r.id !== rowId) return r;
        const nextOverrides = { ...r.treeSpeciesOverrides };
        if (activeSpeciesId === r.species) {
          delete nextOverrides[indexInRow];
        } else {
          nextOverrides[indexInRow] = activeSpeciesId;
        }
        return { ...r, treeSpeciesOverrides: nextOverrides };
      }),
    );
  };

  const handlePaintRow = (rowId: string, speciesOverride?: ObjectIdString) => {
    const targetSpecies = speciesOverride ?? activeSpeciesId;
    if (!targetSpecies) return;
    commitRowsUpdate((prev) =>
      prev.map((r) =>
        r.id === rowId ? { ...r, species: targetSpecies, treeSpeciesOverrides: {} } : r,
      ),
    );
  };

  const handleRowSpacingChange = (rowId: string, nextSpacing: number) => {
    const clamped = Math.max(0.8, Math.min(15, Number(nextSpacing.toFixed(1))));
    commitRowsUpdate((prev) =>
      prev.map((r) => (r.id === rowId ? { ...r, averageSpacingMeters: clamped } : r)),
    );
  };

  const handleApplySpacingToAll = () => {
    if (rows.length === 0) return;
    commitRowsUpdate((prev) =>
      prev.map((r) => ({ ...r, averageSpacingMeters })),
    );
  };

  const handleCloneParallelRow = () => {
    if (!orchard || rows.length === 0) return;
    const source = rows.find((r) => r.id === selectedRowId) ?? rows[rows.length - 1];
    if (!source) return;

    const endpoints = createParallelRowEndpoints(source, parallelOffsetMeters, polygonLocal, orchard.center);
    if (!endpoints) return;

    commitRowsUpdate((prev) => {
      const nextNum = prev.length + 1;
      const cloned: DraftRow = {
        id: `row-${Date.now()}-${nextNum}`,
        label: `R-${String(nextNum).padStart(2, '0')}`,
        start: endpoints.start,
        end: endpoints.end,
        averageSpacingMeters: averageSpacingMeters,
        species: activeSpeciesId || source.species,
        treeSpeciesOverrides: {},
      };
      setSelectedRowId(cloned.id);
      setSelectedTreeKey(null);
      return [...prev, cloned];
    });
  };

  const handleUndo = () => {
    setHistory((prev) => {
      if (prev.length === 0) return prev;
      const previousRows = prev[prev.length - 1];
      setRows(previousRows);
      setSaveBanner(null);
      return prev.slice(0, -1);
    });
  };

  const handleClearAll = () => {
    if (rows.length === 0) return;
    commitRowsUpdate(() => []);
    setSelectedRowId(null);
    setSelectedTreeKey(null);
  };

  const handleSelectSpecies = (crop: CropPrefDoc) => {
    setActiveSpeciesId(crop._id);
  };

  const handleSaveLayout = async () => {
    if (!layoutPayload || layoutPayload.orchardRows.length === 0) return;
    setIsSaving(true);
    try {
      const res = await saveOrchardLayout(layoutPayload);
      setSaveBanner({ response: res.data, endpoint: res.endpoint });
    } catch (err) {
      console.error('Failed to save orchard layout:', err);
    } finally {
      setIsSaving(false);
    }
  };

  const activeSpecies = cropPrefById.get(activeSpeciesId);

  return (
    <div className="row-editor-page">
      {/* Top Page Header: Orchard metadata + Backdrop Mode Toggle + Save Action */}
      <div className="editor-header-bar">
        <h1 className="page-title">
          {t.rowEditor.title}
          {orchard ? ` — ${orchard.name}` : ''}
        </h1>

        <div className="editor-header-actions">
          {/* Backdrop mode: Empty shape (default) vs Satellite Map */}
          <div className="segmented-control" role="group" aria-label={t.rowEditor.backdropLabel}>
            <button
              type="button"
              className={`segmented-btn${backdropMode === 'blank' ? ' is-active' : ''}`}
              onClick={() => setBackdropMode('blank')}
            >
              <MapIcon size={14} />
              <span>{t.rowEditor.backdropBlank}</span>
            </button>
            <button
              type="button"
              className={`segmented-btn${backdropMode === 'satellite' ? ' is-active' : ''}`}
              onClick={() => setBackdropMode('satellite')}
            >
              <Satellite size={14} />
              <span>{t.rowEditor.backdropSatellite}</span>
            </button>
          </div>

          <button
            type="button"
            className={`secondary-btn${showPayloadPreview ? ' is-active' : ''}`}
            onClick={() => setShowPayloadPreview((v) => !v)}
          >
            <Code2 size={15} />
            <span>{t.rowEditor.previewPayload}</span>
          </button>

          <button
            type="button"
            className="primary-btn"
            disabled={isSaving || rows.length === 0}
            onClick={handleSaveLayout}
          >
            <Save size={15} />
            <span>
              {isSaving
                ? t.rowEditor.saving
                : `${t.rowEditor.saveLayout} (${totalTreesCount})`}
            </span>
          </button>
        </div>
      </div>

      {/* Save confirmation toast banner */}
      {saveBanner && (
        <div className="editor-save-banner" role="status">
          <div className="editor-save-banner-left">
            <CheckCircle2 size={18} />
            <span>
              <strong>{t.rowEditor.saveSuccessTitle}</strong> — {saveBanner.response.savedRowsCount}{' '}
              {t.rowEditor.rowsUnit}, {saveBanner.response.savedTreesCount} {t.rowEditor.treesUnit}{' '}
              ({t.rowEditor.saveBackendNote})
            </span>
          </div>
          <code className="endpoint-tag">POST {saveBanner.endpoint}</code>
        </div>
      )}

      {/* Main 2-Column Workspace: Left Interactive Canvas + Right Controls & Rows Panel */}
      <div className="editor-workspace">
        <div className="card editor-canvas-card">
          {/* Drawing Toolbar */}
          <div className="editor-toolbar">
            <div className="editor-toolbar-left">
              <div className="segmented-control" role="group" aria-label={t.rowEditor.toolsLabel}>
                <button
                  type="button"
                  className={`segmented-btn${toolMode === 'draw' ? ' is-active' : ''}`}
                  onClick={() => setToolMode('draw')}
                >
                  <PencilLine size={14} />
                  <span>{t.rowEditor.toolDraw}</span>
                </button>
                <button
                  type="button"
                  className={`segmented-btn${toolMode === 'select' ? ' is-active' : ''}`}
                  onClick={() => setToolMode('select')}
                >
                  <MousePointer2 size={14} />
                  <span>{t.rowEditor.toolSelect}</span>
                </button>
                <button
                  type="button"
                  className={`segmented-btn${toolMode === 'paint' ? ' is-active' : ''}`}
                  onClick={() => setToolMode('paint')}
                >
                  <Paintbrush size={14} />
                  <span>{t.rowEditor.toolPaint}</span>
                </button>
              </div>

              <button
                type="button"
                className={`toggle-pill${angleSnap ? ' is-active' : ''}`}
                onClick={() => setAngleSnap((s) => !s)}
                title={t.rowEditor.angleSnapHint}
              >
                <Magnet size={14} />
                <span>{t.rowEditor.angleSnap}</span>
              </button>
            </div>

            <div className="editor-toolbar-right">
              <button
                type="button"
                className="secondary-btn"
                disabled={rows.length === 0}
                onClick={handleCloneParallelRow}
                title={t.rowEditor.parallelRowHint}
              >
                <CopyPlus size={14} />
                <span>{t.rowEditor.parallelRow}</span>
              </button>

              <button
                type="button"
                className="secondary-btn"
                disabled={history.length === 0}
                onClick={handleUndo}
                title={t.rowEditor.undo}
              >
                <Undo2 size={14} />
              </button>

              <button
                type="button"
                className="secondary-btn danger-hover"
                disabled={rows.length === 0}
                onClick={handleClearAll}
                title={t.rowEditor.clearAll}
              >
                <RotateCcw size={14} />
              </button>
            </div>
          </div>

          {/* Interactive Vector + Satellite Drawing Surface */}
          {orchard && (
            <RowLineEditorCanvas
              key={orchard._id}
              orchard={orchard}
              cropPrefs={cropPrefs}
              activeSpeciesId={activeSpeciesId}
              activeSpacingMeters={averageSpacingMeters}
              edgeMarginMeters={edgeMarginMeters}
              angleSnapEnabled={angleSnap}
              toolMode={toolMode}
              backdropMode={backdropMode}
              calculatedRows={calculatedRows}
              selectedRowId={selectedRowId}
              selectedTreeKey={selectedTreeKey}
              onAddRow={handleAddRow}
              onUpdateRowEndpoints={handleUpdateRowEndpoints}
              onSelectRow={setSelectedRowId}
              onSelectTree={(tree) =>
                setSelectedTreeKey(tree ? { rowId: tree.rowId, indexInRow: tree.indexInRow } : null)
              }
              onPaintTree={handlePaintTree}
              onPaintRow={(rowId) => handlePaintRow(rowId)}
            />
          )}

          {/* Canvas Footer Meta */}
          <div className="card-footer-meta">
            <div className="editor-summary-stats">
              <span className="stat-chip">
                <span className="stat-label">{t.rowEditor.rowsCountLabel}:</span>
                <strong className="stat-value">{rows.length}</strong>
              </span>
              <span className="stat-chip">
                <span className="stat-label">{t.rowEditor.treesCountLabel}:</span>
                <strong className="stat-value">{totalTreesCount}</strong>
              </span>
              {activeSpecies && (
                <span className="stat-chip">
                  <span className="species-dot-sm" style={{ backgroundColor: activeSpecies.colorHex }} />
                  <span className="stat-label">{t.rowEditor.activeSpeciesLabel}:</span>
                  <strong className="stat-value">
                    {language === 'pl' ? activeSpecies.namePl : activeSpecies.nameEn} ({activeSpecies.variety})
                  </strong>
                </span>
              )}
            </div>
            <code className="endpoint-tag">
              GET {orchardEndpoint} · GET {cropPrefsEndpoint}
            </code>
          </div>
        </div>

        {/* Right Side Control Panel: Species Picker (CropPref), Spacing, Selected Item, Rows List */}
        <aside className="editor-side-panel">
          {/* 1. Intuitive Species Selector (CropPref collection) */}
          <section className="card editor-panel-card">
            <div className="panel-section-head">
              <div className="panel-section-title-row">
                <Sprout size={16} className="panel-accent-icon" />
                <h2 className="panel-section-title">{t.rowEditor.speciesTitle}</h2>
              </div>
              <code className="mini-collection-tag">CropPref</code>
            </div>

            <div className="species-grid">
              {cropPrefs.map((crop) => {
                const isActive = crop._id === activeSpeciesId;
                const count = speciesCounts.get(crop._id) ?? 0;
                const displayName = language === 'pl' ? crop.namePl : crop.nameEn;

                return (
                  <button
                    key={crop._id}
                    type="button"
                    className={`species-card-btn${isActive ? ' is-active' : ''}`}
                    onClick={() => handleSelectSpecies(crop)}
                    title={`CropPref ObjectId: ${crop._id}`}
                  >
                    <span className="species-card-top">
                      <span
                        className="species-swatch-lg"
                        style={{ backgroundColor: crop.colorHex }}
                      />
                      <span className="species-card-names">
                        <strong>{displayName}</strong>
                        <span className="species-variety">{crop.variety}</span>
                      </span>
                    </span>
                    <span className="species-card-meta">
                      <span>~{crop.recommendedSpacingMeters.toFixed(1)} m</span>
                      {count > 0 && <span className="species-count-pill">{count}</span>}
                    </span>
                  </button>
                );
              })}
            </div>

            {activeSpecies && (
              <div className="active-species-footer">
                <span className="muted-caption">
                  ObjectId: <code>{activeSpecies._id}</code>
                </span>
                <button
                  type="button"
                  className="text-action-btn"
                  onClick={() => setAverageSpacingMeters(activeSpecies.recommendedSpacingMeters)}
                >
                  {t.rowEditor.useRecommendedSpacing} ({activeSpecies.recommendedSpacingMeters.toFixed(1)} m)
                </button>
              </div>
            )}
          </section>

          {/* 2. Tree Spacing & Geometry Parameters */}
          <section className="card editor-panel-card">
            <div className="panel-section-head">
              <h2 className="panel-section-title">{t.rowEditor.spacingTitle}</h2>
            </div>

            <div className="param-field">
              <div className="param-label-row">
                <label htmlFor="tree-spacing-input">{t.rowEditor.treeSpacingLabel}</label>
                <div className="param-number-wrap">
                  <input
                    id="tree-spacing-input"
                    type="number"
                    min={0.8}
                    max={15}
                    step={0.1}
                    value={averageSpacingMeters}
                    onChange={(e) => {
                      const val = Number(e.target.value);
                      if (!Number.isNaN(val)) setAverageSpacingMeters(Math.max(0.8, Math.min(15, val)));
                    }}
                    className="param-number-input"
                  />
                  <span>m</span>
                </div>
              </div>
              <input
                type="range"
                min={1.0}
                max={10.0}
                step={0.1}
                value={Math.min(10, averageSpacingMeters)}
                onChange={(e) => setAverageSpacingMeters(Number(e.target.value))}
                className="param-range-slider"
              />
              {rows.length > 0 && (
                <button type="button" className="text-action-btn" onClick={handleApplySpacingToAll}>
                  {t.rowEditor.applySpacingAll}
                </button>
              )}
            </div>

            <div className="param-grid-2">
              <div className="param-field">
                <div className="param-label-row">
                  <label htmlFor="row-offset-input">{t.rowEditor.rowOffsetLabel}</label>
                  <span className="param-val-pill">{parallelOffsetMeters.toFixed(1)} m</span>
                </div>
                <input
                  id="row-offset-input"
                  type="range"
                  min={2.0}
                  max={10.0}
                  step={0.5}
                  value={parallelOffsetMeters}
                  onChange={(e) => setParallelOffsetMeters(Number(e.target.value))}
                  className="param-range-slider"
                />
              </div>

              <div className="param-field">
                <div className="param-label-row">
                  <label htmlFor="edge-margin-input">{t.rowEditor.edgeMarginLabel}</label>
                  <span className="param-val-pill">{edgeMarginMeters.toFixed(1)} m</span>
                </div>
                <input
                  id="edge-margin-input"
                  type="range"
                  min={0}
                  max={5}
                  step={0.5}
                  value={edgeMarginMeters}
                  onChange={(e) => setEdgeMarginMeters(Number(e.target.value))}
                  className="param-range-slider"
                />
              </div>
            </div>
          </section>

          {/* 3. Selected Individual Tree Inspector (if clicked in Select mode) */}
          {selectedTree && (
            <section className="card editor-panel-card is-highlighted">
              <div className="panel-section-head">
                <h2 className="panel-section-title">
                  {t.rowEditor.selectedTreeTitle} #{selectedTree.indexInRow + 1}
                </h2>
                <code className="mini-collection-tag">Tree</code>
              </div>

              <div className="tree-meta-mini">
                <div className="inspector-row">
                  <span>_id</span>
                  <code>{selectedTree.tempId}</code>
                </div>
                <div className="inspector-row">
                  <span>coordinates</span>
                  <strong>
                    {selectedTree.coordinates.lat.toFixed(6)}, {selectedTree.coordinates.lng.toFixed(6)}
                  </strong>
                </div>
                <div className="inspector-row">
                  <span>healthIndex</span>
                  <code>null ({t.rowEditor.computedByBackend})</code>
                </div>
              </div>

              <div className="selected-tree-species-row">
                <span className="muted-caption">{t.rowEditor.changeTreeSpecies}:</span>
                <div className="mini-species-pills">
                  {cropPrefs.map((crop) => {
                    const active = crop._id === selectedTree.species;
                    return (
                      <button
                        key={crop._id}
                        type="button"
                        className={`mini-species-pill${active ? ' is-active' : ''}`}
                        onClick={() => {
                          commitRowsUpdate((prev) =>
                            prev.map((r) => {
                              if (r.id !== selectedTree.rowId) return r;
                              const nextOverrides = { ...r.treeSpeciesOverrides };
                              if (crop._id === r.species) {
                                delete nextOverrides[selectedTree.indexInRow];
                              } else {
                                nextOverrides[selectedTree.indexInRow] = crop._id;
                              }
                              return { ...r, treeSpeciesOverrides: nextOverrides };
                            }),
                          );
                        }}
                      >
                        <span className="species-dot-sm" style={{ backgroundColor: crop.colorHex }} />
                        <span>{crop.variety}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </section>
          )}

          {/* 4. Drawn Rows List (Orchard.rows) */}
          <section className="card editor-panel-card editor-rows-card">
            <div className="panel-section-head">
              <h2 className="panel-section-title">
                {t.rowEditor.rowsListTitle} ({rows.length})
              </h2>
              <code className="mini-collection-tag">Orchard.rows</code>
            </div>

            {calculatedRows.length === 0 ? (
              <div className="empty-rows-state">{t.rowEditor.emptyRowsList}</div>
            ) : (
              <div className="rows-list-scroll">
                {calculatedRows.map((calc) => {
                  const isSel = calc.row.id === selectedRowId;
                  const sp = cropPrefById.get(calc.row.species);

                  return (
                    <div
                      key={calc.row.id}
                      className={`row-list-item${isSel ? ' is-selected' : ''}`}
                      onClick={() => {
                        setSelectedRowId(calc.row.id);
                        setSelectedTreeKey(null);
                      }}
                    >
                      <div className="row-item-main">
                        <span
                          className="species-dot-sm"
                          style={{ backgroundColor: sp?.colorHex ?? '#16a34a' }}
                        />
                        <strong className="row-item-label">{calc.row.label}</strong>
                        <span className="row-item-stats">
                          {calc.insideLengthMeters.toFixed(1)} m · <strong>{calc.trees.length}</strong>{' '}
                          {t.rowEditor.treesUnit}
                        </span>
                        <button
                          type="button"
                          className="row-delete-btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteRow(calc.row.id);
                          }}
                          aria-label={t.rowEditor.deleteRow}
                          title={t.rowEditor.deleteRow}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>

                      {isSel && (
                        <div className="row-item-controls" onClick={(e) => e.stopPropagation()}>
                          <label className="row-inline-control">
                            <span>{t.rowEditor.rowSpeciesShort}</span>
                            <select
                              value={calc.row.species}
                              onChange={(e) => handlePaintRow(calc.row.id, e.target.value)}
                              className="row-inline-select"
                            >
                              {cropPrefs.map((c) => (
                                <option key={c._id} value={c._id}>
                                  {language === 'pl' ? c.namePl : c.nameEn} ({c.variety})
                                </option>
                              ))}
                            </select>
                          </label>

                          <label className="row-inline-control">
                            <span>{t.rowEditor.rowSpacingShort}</span>
                            <input
                              type="number"
                              min={0.8}
                              max={15}
                              step={0.1}
                              value={calc.row.averageSpacingMeters}
                              onChange={(e) => {
                                const v = Number(e.target.value);
                                if (!Number.isNaN(v)) handleRowSpacingChange(calc.row.id, v);
                              }}
                              className="param-number-input"
                            />
                          </label>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {selectedRowCalc && (
              <div className="selected-row-coords-foot">
                <span>
                  A: {selectedRowCalc.row.start.lat.toFixed(5)}, {selectedRowCalc.row.start.lng.toFixed(5)}
                </span>
                <span>
                  B: {selectedRowCalc.row.end.lat.toFixed(5)}, {selectedRowCalc.row.end.lng.toFixed(5)}
                </span>
              </div>
            )}
          </section>
        </aside>
      </div>

      {/* Collapsible MongoDB Payload Inspector (Orchard.rows + Tree[]) */}
      {showPayloadPreview && layoutPayload && (
        <section className="card payload-preview-card">
          <div className="card-header">
            <h2 className="card-title">{t.rowEditor.payloadPreviewTitle}</h2>
            <code className="endpoint-tag">
              POST /api/v1/orchards/{layoutPayload.orchardId}/layout
            </code>
          </div>

          <div className="payload-columns">
            <div className="payload-pane">
              <div className="payload-pane-title">
                Collection <code>Orchard.rows</code> ({layoutPayload.orchardRows.length})
              </div>
              <pre className="payload-json">
                {JSON.stringify(layoutPayload.orchardRows, null, 2)}
              </pre>
            </div>

            <div className="payload-pane">
              <div className="payload-pane-title">
                Collection <code>Tree</code> ({layoutPayload.trees.length})
              </div>
              <pre className="payload-json">
                {JSON.stringify(layoutPayload.trees.slice(0, 12), null, 2)}
                {layoutPayload.trees.length > 12
                  ? `\n// ... +${layoutPayload.trees.length - 12} more Tree documents`
                  : ''}
              </pre>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
