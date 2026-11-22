// The map module (docs/interfaces.md → The map module, frontend/src/map/README.md).
//
//   initMap(container, ctx): void   called once by main.ts
//
// Draws inside `container` only, reads data only through ctx.api, talks to the rest of the page only
// through ctx.events, and never reads the browser's date: the demo's date is ctx.clock.today.
//
//   sends    field:selected { fieldId }   a click on a field; { fieldId: null } on empty map or closing the panel
//   handles  field:focus { fieldId }      zoom to + highlight the field, open its panel, then send field:selected
//            date:changed { today }       reload colours and the open panel (ctx.clock is already updated)
//            risks:updated { fieldIds }   reload those fields (colours, and the panel if it shows one of them)

import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { readExplanations, type AppContext, type DayRisks, type FieldCollection, type FieldDayRisks, type FieldDetail, type FieldFeature, type FieldRiskSeries, type Level, type Threat } from "./contract";
import {
  CATEGORY_LABEL, CATEGORY_SHORT, LEVEL_INSTR, LEVEL_LABEL, addDays, cropName, daysBetween, esc, ha, levelOf, longDate, shortDate, weekday,
} from "./format";
import { ICON, levelPill, renderPanel, type PanelState } from "./panel";
import "./map.css";

// Below this map width the layout is the phone one (map.css: @container (max-width: 720px), keep both equal).
const NARROW_PX = 720;

type FieldLevel = { level: Level | null; score: number; top: string | null };

/** Status colours (fixed, never themed); the level always comes with its label too. */
const FILL: Record<Level | "none", string> = { high: "#d03b3b", medium: "#fab219", low: "#0ca30c", none: "#8a8f87" };
const LEVELS: Level[] = ["high", "medium", "low"];

const BASEMAPS = {
  satellite: {
    label: "Satelita",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Zdjęcia © Esri, Maxar, Earthstar Geographics",
  },
  map: {
    label: "Mapa",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    attribution: "© Esri, HERE, Garmin, OpenStreetMap",
  },
} as const;

/** A small silhouette of the field's outline (largest ring), for the field list. */
function silhouette(f: FieldFeature): string {
  const g = f.geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon;
  let ring: number[][] | undefined;
  if (g?.type === "Polygon") ring = g.coordinates[0] as number[][];
  else if (g?.type === "MultiPolygon") ring = (g.coordinates.map((p) => p[0]) as number[][][]).sort((a, b) => b.length - a.length)[0];
  if (!ring || ring.length < 3) return "";
  const k = Math.cos((ring[0][1] * Math.PI) / 180);
  const pts = ring.map(([lon, lat]) => [lon * k, -lat]);
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const s = 26 / Math.max(x1 - x0, y1 - y0, 1e-9);
  const ox = (32 - (x1 - x0) * s) / 2;
  const oy = (32 - (y1 - y0) * s) / 2;
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${(ox + (x - x0) * s).toFixed(1)},${(oy + (y - y0) * s).toFixed(1)}`).join("") + "Z";
  return `<svg class="fr-shape" viewBox="0 0 32 32" aria-hidden="true"><path d="${d}"/></svg>`;
}

export function initMap(container: HTMLElement, ctx: AppContext): void {
  const { api, events } = ctx;   // ctx.clock is read at each use: main.ts updates it

  // --- DOM -------------------------------------------------------------------------------------
  container.classList.add("fup-map");
  container.innerHTML = `
    <div class="fup-canvas"></div>
    <aside class="fup-card fup-side" aria-label="Pola gospodarstwa">
      <div class="side-head">
        <div><div class="side-title">Twoje pola</div><div class="side-date"></div></div>
        <button class="side-toggle" aria-expanded="false" aria-label="Pokaż listę pól">Lista pól
          <svg viewBox="0 0 12 12" aria-hidden="true"><path d="m3 4.5 3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></button>
      </div>
      <div class="side-counts" role="group" aria-label="Filtruj według poziomu"></div>
      <div class="side-filter" role="group" aria-label="Koloruj według kategorii"></div>
      <ol class="side-list"></ol>
      <div class="fup-legend-box" aria-label="Legenda"></div>
    </aside>
    <div class="fup-card fup-days" role="group" aria-label="Dzień na mapie"></div>
    <div class="fup-card fup-base" role="group" aria-label="Podkład mapy"></div>
    <aside class="fup-card fup-panel" aria-label="Szczegóły pola" hidden></aside>
    <div class="fup-toast" role="status" hidden></div>`;
  const $ = <T extends HTMLElement>(sel: string) => container.querySelector<T>(sel)!;
  const canvas = $<HTMLDivElement>(".fup-canvas");
  const sideCard = $(".fup-side");
  const side = { date: $(".side-date"), counts: $(".side-counts"), filter: $(".side-filter"), list: $(".side-list") };
  const daysBox = $(".fup-days");
  const panel = $<HTMLElement>(".fup-panel");
  const toast = $(".fup-toast");

  // --- state -----------------------------------------------------------------------------------
  let fields: FieldFeature[] = [];
  const threats = new Map<string, Threat>();
  let viewDate = ctx.clock.today;                // today or one of the coming days
  let dayRisks: DayRisks | null = null;
  let category = "all";
  let levelFilter: Level | null = null;
  let selected: number | null = null;
  let pendingFocus: number | null = null;        // field:focus that arrived before the fields were drawn
  let basemap: keyof typeof BASEMAPS = "satellite";
  const layers = new Map<number, L.GeoJSON>();
  const detailCache = new Map<number, FieldDetail>();
  const seriesCache = new Map<string, FieldRiskSeries>();   // key: field id + the today it was asked for
  const panelState: PanelState = { open: new Set(), range: "recent", lowOpen: false };
  let panelToken = 0;
  let dayToken = 0;

  const narrow = () => container.clientWidth <= NARROW_PX;
  const horizon = () => addDays(ctx.clock.today, ctx.clock.forecastDays);
  const seriesKey = (id: number) => `${id}@${ctx.clock.today}`;

  // --- Leaflet ---------------------------------------------------------------------------------
  const map = L.map(canvas, { zoomControl: false, attributionControl: true, minZoom: 6, maxZoom: 18 })  // whole zoom levels: raster tiles stay crisp, no seams
    .setView([50.36, 17.68], 13);
  L.control.zoom({ position: "topright", zoomInTitle: "Przybliż", zoomOutTitle: "Oddal" }).addTo(map);
  map.attributionControl.setPrefix(false);
  let tiles = L.tileLayer(BASEMAPS[basemap].url, { attribution: BASEMAPS[basemap].attribution, maxZoom: 19 }).addTo(map);
  map.on("click", () => select(null, { emit: true }));
  new ResizeObserver(() => map.invalidateSize()).observe(container);

  function showError(msg: string): void {
    toast.textContent = msg;
    toast.hidden = false;
    window.clearTimeout(Number(toast.dataset.timer));
    toast.dataset.timer = String(window.setTimeout(() => (toast.hidden = true), 6000));
  }
  const fail = (what: string) => (e: unknown) => {
    const detail = (e as { detail?: string })?.detail ?? (e as Error)?.message ?? String(e);
    showError(`${what}: ${detail}`);
  };

  // --- colours ---------------------------------------------------------------------------------
  function fieldLevel(fieldId: number): FieldLevel {
    let best: FieldLevel = { level: null, score: -1, top: null };
    for (const r of dayRisks?.risks ?? []) {
      if (r.field_id !== fieldId) continue;
      if (category !== "all" && threats.get(r.threat_code)?.category !== category) continue;
      const level = r.level ?? levelOf(r.score);   // the endpoint carries only the score (interfaces.md)
      if (best.level === null || r.score > best.score) best = { level, score: r.score, top: r.threat_code };
    }
    return best;
  }

  function styleFor(id: number): L.PathOptions {
    const { level } = fieldLevel(id);
    const isSel = id === selected;
    const dimmed = levelFilter !== null && level !== levelFilter && !isSel;
    return {
      className: `fup-field ${level ? `lvl-${level}` : "lvl-none"}${isSel ? " is-selected" : ""}${dimmed ? " is-dimmed" : ""}`,
      color: "#ffffff",
      opacity: dimmed ? 0.35 : isSel ? 1 : 0.9,
      weight: isSel ? 3.5 : level === "high" ? 3 : 2,
      dashArray: level === "high" && !isSel ? "7 4" : undefined, // not by colour alone: high risk has a dashed edge
      fillColor: FILL[level ?? "none"],
      fillOpacity: dimmed ? 0.12 : isSel ? 0.66 : 0.58,
    };
  }

  /** The permanent label: icon + name + level, so the map never tells the level by colour alone. */
  function labelHtml(f: FieldFeature): string {
    const { level } = fieldLevel(f.id);
    return level
      ? `<span class="lb-ic lvl-${level}">${ICON[level]}</span>${esc(f.properties.name)}<span class="lb-lv"> · ${LEVEL_LABEL[level]}</span>`
      : esc(f.properties.name);
  }

  function recolour(ids?: number[]): void {
    for (const [id, layer] of layers) {
      if (ids && !ids.includes(id)) continue;
      const st = styleFor(id);
      layer.setStyle(st);
      const f = fields.find((x) => x.id === id);
      const tip = layer.getTooltip();
      if (f && tip) {
        tip.setContent(labelHtml(f));
        const level = fieldLevel(id).level;
        tip.getElement()?.classList.toggle("lbl-high", level === "high");
      }
      // className on an existing path is not updated by setStyle: set it on the element
      layer.eachLayer((l) => {
        const el = (l as L.Path & { _path?: SVGElement })._path;
        if (el) el.setAttribute("class", `leaflet-interactive ${st.className}`);
      });
    }
    renderSide();
  }

  // --- side card ---------------------------------------------------------------------------------
  function renderSide(): void {
    const lead = daysBetween(ctx.clock.today, viewDate);
    side.date.innerHTML = lead > 0
      ? `Prognoza na <b>${weekday(viewDate)} ${shortDate(viewDate)}</b> · +${lead} ${lead === 1 ? "dzień" : "dni"}`
      : `Stan na <b>${longDate(viewDate)}</b>`;
    const rows = fields.map((f) => ({ f, lv: fieldLevel(f.id) }))
      .sort((a, b) => (b.lv.score - a.lv.score) || a.f.properties.name.localeCompare(b.f.properties.name, "pl"));
    const counts: Record<Level, number> = { high: 0, medium: 0, low: 0 };
    rows.forEach((r) => r.lv.level && counts[r.lv.level]++);
    side.counts.innerHTML = LEVELS.map((l) =>
      `<button class="count lvl-${l}${levelFilter === l ? " on" : ""}" data-level="${l}" aria-pressed="${levelFilter === l}" title="Pokaż tylko pola z ryzykiem ${LEVEL_INSTR[l]}">` +
      `<span class="count-n">${counts[l]}</span><span class="count-k">${ICON[l]}${LEVEL_LABEL[l]}</span></button>`).join("");
    const shown = levelFilter ? rows.filter((r) => r.lv.level === levelFilter) : rows;
    side.list.innerHTML = shown.map(({ f, lv }) => {
      const top = lv.top ? threats.get(lv.top)?.name ?? lv.top : category === "all" ? "brak oceny" : "brak oceny w tej kategorii";
      return `<li><button class="field-row${f.id === selected ? " on" : ""}" data-id="${f.id}"${f.id === selected ? ' aria-current="true"' : ""} title="${esc(top)}">` +
        `<span class="fr-icon ${lv.level ? `lvl-${lv.level}` : "lvl-none"}">${silhouette(f)}</span>` +
        `<span class="fr-main"><span class="fr-name">${esc(f.properties.name)}</span>` +
        `<span class="fr-sub">${esc(cropName(f.properties.crop))} · ${ha(f.properties.area_ha)}</span>` +
        `<span class="fr-top">${esc(top)}</span></span>` +
        (lv.level ? levelPill(lv.level, "sm") : '<span class="fup-pill lvl-none sm">—</span>') + "</button></li>";
    }).join("") || '<li class="side-empty">Brak pól na tym poziomie.</li>';
  }

  function renderFilter(): void {
    // only the categories of the farm's crops (no "bakterie" chip when no field grows a crop with bacterial threats)
    const crops = new Set(fields.map((f) => f.properties.crop?.code));
    const cats = [...new Set([...threats.values()].filter((t) => crops.has(t.crop.code)).map((t) => t.category))].sort();
    side.filter.innerHTML = ["all", ...cats].map((c) =>
      `<button data-cat="${esc(c)}" class="${c === category ? "on" : ""}" aria-pressed="${c === category}" title="${c === "all" ? "wszystkie zagrożenia" : esc(CATEGORY_LABEL[c] ?? c)}">` +
      `${c === "all" ? "wszystkie" : esc(CATEGORY_SHORT[c] ?? CATEGORY_LABEL[c] ?? c)}</button>`).join("");
  }

  side.filter.addEventListener("click", (ev) => {
    const b = (ev.target as HTMLElement).closest<HTMLButtonElement>("button[data-cat]");
    if (!b) return;
    category = b.dataset.cat!;
    renderFilter();
    recolour();
  });
  side.counts.addEventListener("click", (ev) => {
    const b = (ev.target as HTMLElement).closest<HTMLButtonElement>("button[data-level]");
    if (!b) return;
    const l = b.dataset.level as Level;
    levelFilter = levelFilter === l ? null : l;
    recolour();
  });
  side.list.addEventListener("click", (ev) => {
    const b = (ev.target as HTMLElement).closest<HTMLButtonElement>("button[data-id]");
    if (!b) return;
    setSideOpen(false);
    focusField(Number(b.dataset.id));
  });
  function setSideOpen(open: boolean): void {
    sideCard.classList.toggle("side-open", open);
    const toggle = $(".side-toggle");
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Ukryj listę pól" : "Pokaż listę pól");
  }
  $(".side-toggle").addEventListener("click", () => setSideOpen(!sideCard.classList.contains("side-open")));
  // Esc closes the field panel (keyboard users have no map to click)
  container.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && selected != null) {
      select(null, { emit: true });
      fitAll(true);
    }
  });

  // --- day strip: today + the coming days ----------------------------------------------------------
  function renderDays(): void {
    const n = ctx.clock.forecastDays;
    const items = Array.from({ length: n + 1 }, (_, k) => addDays(ctx.clock.today, k));
    daysBox.innerHTML = '<span class="days-k">Dzień</span>' + items.map((d, k) => {
      const [dd, mm] = shortDate(d).split(" ");
      return `<button data-day="${d}" class="${d === viewDate ? "on" : ""}${k ? "" : " today"}" aria-pressed="${d === viewDate}">` +
        `<span class="d-w">${k ? weekday(d) : "dziś"}</span><span class="d-n">${dd}<span class="d-m"> ${mm}</span></span></button>`;
    }).join("");
  }
  daysBox.addEventListener("click", (ev) => {
    const b = (ev.target as HTMLElement).closest<HTMLButtonElement>("button[data-day]");
    if (!b || b.dataset.day === viewDate) return;
    viewDate = b.dataset.day!;
    renderDays();
    void loadDay();
  });

  // --- legend + basemap + whole farm ---------------------------------------------------------------
  $(".fup-legend-box").innerHTML = '<div class="lg-title">Kolor pola = najwyższe ryzyko na nim</div><div class="lg-items">' +
    LEVELS.map((l) => `<span class="lg-row"><span class="lg-sw lvl-${l}"></span>${LEVEL_LABEL[l]}</span>`).join("") +
    '<span class="lg-row"><span class="lg-sw lvl-none"></span>brak oceny</span></div>';
  const baseBox = $(".fup-base");
  function renderBase(): void {
    baseBox.innerHTML = (Object.keys(BASEMAPS) as (keyof typeof BASEMAPS)[]).map((k) =>
      `<button data-base="${k}" class="${k === basemap ? "on" : ""}" aria-pressed="${k === basemap}">${BASEMAPS[k].label}</button>`).join("") +
      '<button data-fit class="fit" title="Pokaż całe gospodarstwo" aria-label="Pokaż całe gospodarstwo">' +
      '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></button>';
  }
  baseBox.addEventListener("click", (ev) => {
    const t = ev.target as HTMLElement;
    if (t.closest("button[data-fit]")) return fitAll(true);
    const b = t.closest<HTMLButtonElement>("button[data-base]");
    if (!b || b.dataset.base === basemap) return;
    basemap = b.dataset.base as keyof typeof BASEMAPS;
    map.removeLayer(tiles);
    tiles = L.tileLayer(BASEMAPS[basemap].url, { attribution: BASEMAPS[basemap].attribution, maxZoom: 19 }).addTo(map);
    container.dataset.base = basemap;
    renderBase();
  });
  renderBase();
  container.dataset.base = basemap;
  for (const el of [".fup-side", ".fup-days", ".fup-base", ".fup-panel"]) {
    L.DomEvent.disableClickPropagation($(el));
    L.DomEvent.disableScrollPropagation($(el));
  }

  /** Every field in view, in the part of the map the cards leave free. */
  function fitAll(animate: boolean): void {
    if (!layers.size) return;
    const bounds = L.featureGroup([...layers.values()]).getBounds();
    const panelOpen = selected != null;
    const pad = narrow()
      ? { paddingTopLeft: [20, sideCard.offsetHeight + 24] as L.PointTuple, paddingBottomRight: [20, 80] as L.PointTuple }
      : { paddingTopLeft: [340, 40] as L.PointTuple, paddingBottomRight: [panelOpen ? 440 : 70, 96] as L.PointTuple };
    if (animate) map.flyToBounds(bounds, { ...pad, duration: 0.6 });
    else map.fitBounds(bounds, pad);
  }

  // --- fields ------------------------------------------------------------------------------------
  let zoomHooked = false;
  function drawFields(fc: FieldCollection): void {
    for (const layer of layers.values()) map.removeLayer(layer);  // a reload (the scenario was switched)
    layers.clear();
    detailCache.clear();
    seriesCache.clear();
    fields = fc.features;
    for (const f of fields) {
      const layer = L.geoJSON(f as GeoJSON.Feature, { style: () => styleFor(f.id), bubblingMouseEvents: false } as L.GeoJSONOptions);
      layer.on("click", () => focusField(f.id, { zoom: false }));
      layer.on("mouseover", () => container.querySelector(`.field-row[data-id="${f.id}"]`)?.classList.add("hover"));
      layer.on("mouseout", () => container.querySelector(`.field-row[data-id="${f.id}"]`)?.classList.remove("hover"));
      layer.bindTooltip(L.tooltip({ permanent: true, direction: "center", className: "fup-label", opacity: 1 }).setContent(labelHtml(f)));
      layer.addTo(map);
      layers.set(f.id, layer);
    }
    fitAll(false);
    // zoomed out, only the high-risk fields keep their label (map.css: .labels-off .fup-label:not(.lbl-high))
    const toggleLabels = () => container.classList.toggle("labels-off", map.getZoom() < 13);
    if (!zoomHooked) map.on("zoomend", toggleLabels);
    zoomHooked = true;
    toggleLabels();
  }

  async function loadDay(): Promise<void> {
    const token = ++dayToken;
    const asked = viewDate;
    container.classList.add("is-loading");
    try {
      const risks = await api.getRisks(asked);
      if (token !== dayToken || asked !== viewDate) return;      // a newer request (or day) won
      dayRisks = risks;
      recolour();
      if (selected != null) void loadPanel(selected);
    } catch (e) {
      if (token === dayToken) {
        fail("Nie udało się wczytać ryzyk")(e);
        if (dayRisks && dayRisks.date !== viewDate) {  // the strip goes back to the day the colours show
          viewDate = dayRisks.date;
          renderDays();
          renderSide();
        }
      }
    } finally {
      if (token === dayToken) container.classList.remove("is-loading");
    }
  }

  // --- selection + panel ---------------------------------------------------------------------------
  function select(id: number | null, opts: { emit: boolean }): void {
    if (id === selected && id !== null) return;
    if (id === null && selected === null) {
      if (opts.emit) events.emit("field:selected", { fieldId: null });
      return;
    }
    const prev = selected;
    selected = id;
    panelState.open.clear();
    panelState.lowOpen = false;
    recolour([prev, id].filter((x): x is number => x != null));
    if (id == null) {
      panel.hidden = true;
      container.classList.remove("has-panel");
    } else {
      layers.get(id)?.bringToFront();
      void loadPanel(id);
    }
    if (opts.emit) events.emit("field:selected", { fieldId: id });
  }

  /** Zoom so the field sits in the part of the map the cards and the panel leave free. */
  function flyTo(id: number): void {
    const layer = layers.get(id);
    if (!layer) return;
    const pad = narrow()
      ? { paddingTopLeft: [24, 24] as L.PointTuple, paddingBottomRight: [24, Math.round(container.clientHeight * 0.62) + 24] as L.PointTuple }
      : { paddingTopLeft: [340, 60] as L.PointTuple, paddingBottomRight: [440, 100] as L.PointTuple };
    map.flyToBounds(layer.getBounds(), { ...pad, maxZoom: 15, duration: 0.6 });
  }

  function focusField(id: number, opts: { zoom?: boolean } = {}): void {
    if (!layers.has(id)) return;
    if (opts.zoom !== false) flyTo(id);
    if (selected !== id) select(id, { emit: true });
  }

  async function loadPanel(id: number): Promise<void> {
    const token = ++panelToken;
    const asked = { day: viewDate, today: ctx.clock.today };
    const stale = () => token !== panelToken || asked.day !== viewDate || asked.today !== ctx.clock.today;
    panel.hidden = false;
    container.classList.add("has-panel");
    if (!panel.innerHTML || panel.dataset.field !== String(id)) {
      panel.innerHTML = '<div class="p-loading"><div class="skeleton h"></div><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton tall"></div></div>';
    }
    panel.dataset.field = String(id);
    try {
      const detailP = detailCache.get(id) ? Promise.resolve(detailCache.get(id)!) : api.getField(id);
      const dayP: Promise<FieldDayRisks> = api.getFieldDayRisks(id, asked.day).then(readExplanations);
      const [detail, day] = await Promise.all([detailP, dayP]);
      if (stale()) return;
      detailCache.set(id, detail);
      const draw = (series: FieldRiskSeries | null) =>
        renderPanel(panel, { detail, day, series, today: asked.today, forecastDays: ctx.clock.forecastDays, viewDate: asked.day }, panelState);
      const key = seriesKey(id);
      draw(seriesCache.get(key) ?? null);
      if (!seriesCache.get(key)) {
        let series: FieldRiskSeries;
        try {
          series = await api.getFieldRisks(id, { to: horizon() });
        } catch (e) {                                           // the panel stays; only the chart is missing
          if (!stale()) fail("Nie udało się wczytać wykresu sezonu")(e);
          return;
        }
        if (stale()) return;                                    // never cache a series asked for another today
        seriesCache.set(key, series);
        draw(series);
      }
    } catch (e) {
      if (token === panelToken) {
        panel.innerHTML = '<div class="p-error">Nie udało się wczytać pola.</div>';
        fail("Nie udało się wczytać pola")(e);
      }
    }
  }

  panel.addEventListener("click", (ev) => {
    const t = ev.target as HTMLElement;
    if (t.closest(".p-close")) {
      select(null, { emit: true });
      fitAll(true);
      return;
    }
    const low = t.closest<HTMLButtonElement>(".low-head");
    if (low) {
      panelState.lowOpen = !panelState.lowOpen;
      low.closest(".low-group")?.classList.toggle("open", panelState.lowOpen);
      low.setAttribute("aria-expanded", String(panelState.lowOpen));
      return;
    }
    const head = t.closest<HTMLButtonElement>(".threat-head");
    if (head) {
      const li = head.closest<HTMLElement>(".threat")!;
      const code = li.dataset.code!;
      const open = !li.classList.contains("open");
      li.classList.toggle("open", open);
      head.setAttribute("aria-expanded", String(open));
      if (open) panelState.open.add(code); else panelState.open.delete(code);
      return;
    }
    const range = t.closest<HTMLButtonElement>("button[data-range]");
    if (range && selected != null) {
      panelState.range = range.dataset.range as PanelState["range"];
      void loadPanel(selected);
    }
  });

  // --- events from the page ------------------------------------------------------------------------
  function onFocus(fieldId: number): void {
    if (!layers.size) {                            // fields not drawn yet: do it once they are
      pendingFocus = fieldId;
      return;
    }
    if (!layers.has(fieldId)) {                    // unknown id: the scenario was reloaded since this page opened
      void reloadFields().then(() => {
        if (layers.has(fieldId)) onFocus(fieldId);
      });
      return;
    }
    flyTo(fieldId);
    if (selected !== fieldId) select(fieldId, { emit: false });
    events.emit("field:selected", { fieldId });   // the map sends it itself after focusing (interfaces.md)
  }
  events.on("field:focus", ({ fieldId }) => onFocus(fieldId));

  events.on("date:changed", () => {
    viewDate = ctx.clock.today;                   // ctx.clock is already updated by main.ts
    seriesCache.clear();
    renderDays();
    void loadDay();
  });

  events.on("risks:updated", ({ fieldIds }) => {
    for (const id of fieldIds) seriesCache.delete(seriesKey(id));
    void (async () => {
      const token = ++dayToken;
      const asked = viewDate;
      try {
        const risks = await api.getRisks(asked);
        if (token !== dayToken || asked !== viewDate) return;
        dayRisks = risks;
        recolour(fieldIds);
        for (const id of fieldIds) {
          layers.get(id)?.eachLayer((l) => {
            const el = (l as L.Path & { _path?: SVGElement })._path;
            el?.classList.add("pulse");
            window.setTimeout(() => el?.classList.remove("pulse"), 2400);
          });
        }
        if (selected != null && fieldIds.includes(selected)) void loadPanel(selected);
      } catch (e) {
        if (token === dayToken) fail("Nie udało się odświeżyć ryzyk")(e);
      } finally {
        if (token === dayToken) container.classList.remove("is-loading"); // a day load this one replaced set it
      }
    })();
  });

  // --- start ---------------------------------------------------------------------------------------
  renderDays();
  side.list.addEventListener("click", (ev) => {
    if ((ev.target as HTMLElement).closest(".retry")) void boot();
  });
  /** Fields, threats and colours again (new ids after a scenario switch); the panel closes. */
  async function reloadFields(): Promise<void> {
    if (selected != null) select(null, { emit: true });
    try {
      const [fc, th] = await Promise.all([api.getFields(), api.getThreats()]);
      threats.clear();
      th.forEach((t) => threats.set(t.code, t));
      drawFields(fc);
      renderFilter();
      await loadDay();
    } catch (e) {
      fail("Nie udało się odświeżyć pól")(e);
    }
  }

  async function boot(): Promise<void> {
    container.classList.add("is-loading");
    try {
      const [fc, th] = await Promise.all([api.getFields(), api.getThreats()]);
      th.forEach((t) => threats.set(t.code, t));
      drawFields(fc);
      renderFilter();
      await loadDay();
      if (pendingFocus != null) {
        const id = pendingFocus;
        pendingFocus = null;
        onFocus(id);
      }
    } catch (e) {
      fail("Nie udało się wczytać mapy")(e);
      // stays until it works (the toast goes after a few seconds)
      side.list.innerHTML = '<li class="side-empty">Nie udało się wczytać pól. <button type="button" class="retry">Spróbuj ponownie</button></li>';
    } finally {
      container.classList.remove("is-loading");
    }
  }
  void boot();
}
