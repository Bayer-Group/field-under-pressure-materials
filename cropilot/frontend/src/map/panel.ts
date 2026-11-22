// The field panel: details, that day's threats with the "why", the season chart and the field's background
// (crop history, soil). Pure rendering: index.ts loads the data and wires events.
//
// From Risk.explanation the panel reads exactly the keys database.md ("Who reads what", Map) and the map README
// give the map: `level`, `summary`, `drivers` (`label`, `effect`), `action` (`type`, `text`,
// `spray_window.date`), `growth_stage.name` and `confidence`. Everything else in the explanation is ignored.

import { renderSeasonChart, type ChartSeries } from "./chart";
import type { Driver, Explanation, FieldDayRisks, FieldDetail, FieldRiskSeries, Level } from "./contract";
import {
  ACTION_LABEL, CATEGORY_LABEL, LEVEL_LABEL, LEVEL_TITLE, addDays, cropName, daysBetween, esc, ha, longDate, num, pct,
  shortDate, weekday,
} from "./format";

/** Categorical slots 1–3 of the validated default palette (light, dark): fixed order, never cycled. */
const SERIES = ["var(--fup-series-1)", "var(--fup-series-2)", "var(--fup-series-3)"];

const TEXTURE_PL: Record<string, string> = {
  "sand": "piasek", "loamy sand": "piasek gliniasty", "sandy loam": "glina piaszczysta", "loam": "glina",
  "silt loam": "pył gliniasty", "silt": "pył", "sandy clay loam": "glina piaszczysto-ilasta", "clay loam": "glina ilasta",
  "silty clay loam": "glina ilasto-pylasta", "sandy clay": "ił piaszczysty", "silty clay": "ił pylasty", "clay": "ił",
};

export interface PanelData {
  detail: FieldDetail;
  day: FieldDayRisks;
  series: FieldRiskSeries | null;
  today: string;
  forecastDays: number;
  viewDate: string;
}

export interface PanelState {
  open: Set<string>;               // expanded threat codes
  range: "recent" | "season";
  lowOpen: boolean;                // the group of low threats is expanded
}

export const ICON: Record<Level, string> = {
  high: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5 15 14H1z" fill="currentColor"/><path d="M8 6v3.6M8 11.4v.1" stroke="var(--fup-on-status)" stroke-width="1.6" stroke-linecap="round"/></svg>',
  // a dark mark on the yellow (white on #fab219 is 1.8:1)
  medium: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.5" fill="currentColor"/><path d="M8 4.6v4M8 10.9v.1" stroke="#2b2100" stroke-width="1.6" stroke-linecap="round"/></svg>',
  low: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.5" fill="currentColor"/><path d="m5 8.2 2 2 4-4.2" fill="none" stroke="var(--fup-on-status)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

const ACTION_ICON: Record<string, string> = {
  treat: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 16 15 5m-3-1 4 4M6 9l5 5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  monitor: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M2 10s3-5.5 8-5.5S18 10 18 10s-3 5.5-8 5.5S2 10 2 10Z" fill="none" stroke="currentColor" stroke-width="1.6"/><circle cx="10" cy="10" r="2.4" fill="currentColor"/></svg>',
  wait: '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="m6.8 10.2 2.2 2.2 4.3-4.6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

const CHEVRON = '<svg class="chev" viewBox="0 0 12 12" aria-hidden="true"><path d="m3 4.5 3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>';

export function levelPill(level: Level, extra = ""): string {
  return `<span class="fup-pill lvl-${level} ${extra}">${ICON[level]}${LEVEL_LABEL[level]}</span>`;
}

/**
 * The "why": drivers sorted by `effect` (how much the score would drop without the factor), as the contract
 * asks; `effect: null` = context only, listed after them. Bars show the size of the effect.
 */
const NO_EFFECT = 0.0005;

/** "25 h", "0,6": the factor's own value, unless the label already says it (growth stage, crop codes). */
function driverValue(d: Driver): string {
  if (d.value == null || d.factor === "growth_stage" || d.unit === "kod uprawy") return "";
  const v = typeof d.value === "number" ? num(d.value) : String(d.value);
  if (d.label.includes(v)) return "";
  const unit = d.unit && d.unit !== "0-1" ? ` ${d.unit}` : "";
  return `<span class="drv-val">${esc(v + unit)}</span>`;
}

/**
 * The "why": drivers sorted by `effect` (how much the score would drop without the factor), as the contract
 * asks. Factors without an effect (null, or ~0: e.g. an old report that no longer changes anything) are
 * background, listed once each under "Tło". Bars show the size of the effect; the threshold is the tooltip.
 */
function driverRows(drivers: Driver[] | undefined): string {
  const seen = new Set<string>();
  const list = (drivers ?? []).filter((d) => !seen.has(d.label) && seen.add(d.label));
  const ranked = list.filter((d) => d.effect != null && Math.abs(d.effect) >= NO_EFFECT)
    .sort((a, b) => (b.effect ?? 0) - (a.effect ?? 0));
  const context = list.filter((d) => !ranked.includes(d));
  const max = Math.max(0.0001, ...ranked.map((d) => Math.abs(d.effect ?? 0)));
  const title = (d: Driver) => (d.threshold ? ` title="Próg: ${esc(d.threshold)}"` : "");
  const row = (d: Driver) => {
    const e = d.effect ?? 0;
    const dir = e > 0 ? "up" : "down";
    const tag = dir === "up" ? `podnosi o ${num(e, 2)}` : `obniża o ${num(-e, 2)}`;
    return `<li class="drv ${dir}"${title(d)}><div class="drv-head"><span class="drv-label">${esc(d.label)}${driverValue(d)}</span>` +
      `<span class="drv-tag">${tag}</span></div>` +
      `<div class="drv-bar"><span style="width:${Math.max(4, (Math.abs(e) / max) * 100)}%"></span></div></li>`;
  };
  return (ranked.length ? `<h5>Dlaczego</h5><ul class="drivers">${ranked.map(row).join("")}</ul>` : "") +
    (context.length ? `<h5>Tło</h5><ul class="context">${context.map((d) => `<li${title(d)}>${esc(d.label)}${driverValue(d)}</li>`).join("")}</ul>` : "");
}

function actionBox(e: Explanation, level: Level): string {
  const a = e.action;
  if (!a) return "";
  const date = a.type === "treat" ? a.spray_window?.date : undefined;
  const quality = a.spray_window?.quality;
  const qualityText = quality ? ` <small>(${esc(SPRAY_QUALITY[quality] ?? quality)})</small>` : "";
  const window = a.type !== "treat" ? ""
    : date ? `<div class="spray"><span class="spray-k">Najbliższe okno zabiegu</span><span class="spray-v">${weekday(date)} ${shortDate(date)}${qualityText}</span></div>`
    : '<div class="spray none">Brak dobrego okna zabiegu w prognozie.</div>';
  const threshold = a.threshold && a.type !== "wait" ? `<p class="thr"><b>Próg szkodliwości:</b> ${esc(a.threshold)}</p>` : "";
  return `<div class="action act-${esc(a.type)} lvl-${level}"><div class="act-icon">${ACTION_ICON[a.type] ?? ACTION_ICON.wait}</div><div class="act-main">` +
    `<div class="act-title">${esc(ACTION_LABEL[a.type] ?? a.type)}</div><p>${esc(a.text)}</p>${threshold}${window}</div></div>`;
}

/** One threat's category (the filter chips use the plural). */
const CATEGORY_ONE: Record<string, string> = {
  fungal: "choroba grzybowa", bacterial: "choroba bakteryjna", viral: "choroba wirusowa", pest: "szkodnik", weed: "chwast",
};
const SPRAY_QUALITY: Record<string, string> = { optimal: "dobre warunki", acceptable: "warunki dopuszczalne" };

function capital(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

function meta(e: Explanation, lead: number): string {
  const parts: string[] = [];
  if (e.growth_stage?.name) parts.push(`<span><b>Faza</b> ${esc(e.growth_stage.name)}</span>`);
  if (e.confidence != null) {
    parts.push(`<span class="conf" title="Pewność oceny">` +
      `<b>Pewność</b> <span class="conf-bar"><span style="width:${Math.round(e.confidence * 100)}%"></span></span> ${pct(e.confidence)}</span>`);
  }
  if (lead > 0) parts.push(`<span class="lead">prognoza +${lead} ${lead === 1 ? "dzień" : "dni"}</span>`);
  return `<div class="meta">${parts.join("")}</div>`;
}

/** The summary without an opening "<Poziom> ryzyko – <zagrożenie>: ", which the row already shows. */
function reasonText(summary: string): string {
  const m = /^(Wysokie|Średnie|Niskie) ryzyko – [^:]+:\s*/.exec(summary ?? "");
  const rest = m ? summary.slice(m[0].length) : summary ?? "";
  return rest ? rest[0].toUpperCase() + rest.slice(1) : "";
}

function threatRow(r: FieldDayRisks["risks"][number], expanded: boolean, lead: number): string {
  const e = r.explanation;
  const level = e.level;
  const cat = CATEGORY_ONE[r.threat.category] ?? CATEGORY_LABEL[r.threat.category] ?? r.threat.category;
  return `<li class="threat lvl-${level}${expanded ? " open" : ""}" data-code="${esc(r.threat.code)}">` +
    `<button class="threat-head" aria-expanded="${expanded}">` +
    `<span class="threat-name">${esc(capital(r.threat.name))}<small>${esc(cat)}</small></span>${levelPill(level, "sm")}${CHEVRON}</button>` +
    `<div class="threat-body">${actionBox(e, level)}<p class="summary">${esc(reasonText(e.summary))}</p>${driverRows(e.drivers)}${meta(e, lead)}</div></li>`;
}

function about(d: FieldDetail): string {
  const hist = d.crop_history
    .filter((y) => y.classes.length)
    .map((y) => {
      const top = y.classes[0];
      return `<li><span class="yr">${y.year}</span>${esc(cropName(top))}<small>${Math.round(top.share * 100)}%</small></li>`;
    })
    .join("");
  const s = d.soil;
  const frac = (v: unknown) => (typeof v === "number" ? `${Math.round(v <= 1 ? v * 100 : v)}%` : "—");
  const soil = s
    ? `<dl class="soil"><div class="wide"><dt>Tekstura</dt><dd>${esc(TEXTURE_PL[String(s.soil_texture ?? "").toLowerCase()] ?? s.soil_texture ?? "—")}</dd></div>` +
      `<div><dt>pH</dt><dd>${typeof s.ph === "number" ? num(s.ph) : "—"}</dd></div>` +
      `<div><dt>Ił</dt><dd>${frac(s.clay)}</dd></div><div><dt>Piasek</dt><dd>${frac(s.sand)}</dd></div>` +
      `<div><dt>Pył</dt><dd>${frac(s.silt)}</dd></div></dl>`
    : '<p class="muted">Brak danych glebowych.</p>';
  return `<section class="sec"><h4>Historia upraw</h4><ul class="history">${hist || '<li class="muted">brak</li>'}</ul></section>` +
    `<section class="sec"><h4>Gleba</h4>${soil}</section>`;
}

/** First day worth showing in the whole-season view: a little before the first non-zero risk. */
function seasonStart(series: ChartSeries[], from: string, today: string): string {
  let first: string | null = null;
  for (const s of series) {
    const p = s.points.find((x) => x.score > 0.02);
    if (p && (!first || p.date < first)) first = p.date;
  }
  const start = first ? addDays(first, -14) : from;
  const latest = addDays(today, -60);
  return start < from ? from : start > latest ? latest : start;
}

export function renderPanel(host: HTMLElement, data: PanelData, state: PanelState): void {
  const { detail, day, series, today, viewDate, forecastDays } = data;
  const risks = [...day.risks].sort((a, b) => b.score - a.score);
  const worst = risks[0];
  const stage = risks.find((r) => r.explanation.growth_stage?.name)?.explanation.growth_stage?.name;
  const counts = { high: 0, medium: 0, low: 0 } as Record<Level, number>;
  risks.forEach((r) => counts[r.explanation.level]++);
  if (state.open.size === 0 && worst && worst.explanation.level !== "low") state.open.add(worst.threat.code);
  const lead = daysBetween(today, viewDate);
  const when = lead > 0 ? `prognoza na ${weekday(viewDate)} ${shortDate(viewDate)} (+${lead})` : longDate(viewDate);
  const raised = risks.filter((r) => r.explanation.level !== "low");
  const low = risks.filter((r) => r.explanation.level === "low");

  const overall = worst
    ? `<div class="overall lvl-${worst.explanation.level}"><div class="overall-k">${ICON[worst.explanation.level]}${LEVEL_TITLE[worst.explanation.level]}</div>` +
      `<div class="overall-v">${worst.explanation.level === "low" ? "Wszystkie zagrożenia niskie" : esc(capital(worst.threat.name))}</div>` +
      `<div class="overall-counts">${(["high", "medium", "low"] as Level[]).map((l) => `<span class="cnt lvl-${l}">${counts[l]} ${LEVEL_LABEL[l]}</span>`).join("")}</div></div>`
    : '<div class="overall empty">Brak ocen ryzyka na ten dzień.</div>';

  const lowWord = low.length === 1 ? "zagrożenie niskie" : low.length % 10 >= 2 && low.length % 10 <= 4 && (low.length < 10 || low.length > 20) ? "zagrożenia niskie" : "zagrożeń niskich";
  const lowGroup = low.length
    ? `<li class="low-group${state.lowOpen ? " open" : ""}"><button class="low-head" aria-expanded="${state.lowOpen}">` +
      `${ICON.low}<span>${low.length} ${lowWord}</span>${CHEVRON}</button>` +
      `<ul class="threats inner">${low.map((r) => threatRow(r, state.open.has(r.threat.code), lead)).join("")}</ul></li>`
    : "";

  host.innerHTML =
    `<header class="p-head"><div><div class="p-crop">${esc(cropName(detail.crop))}</div><h3>${esc(detail.name)}</h3>` +
    `<div class="p-sub">${ha(detail.area_ha)}${stage ? ` · ${esc(stage)}` : ""}</div></div>` +
    '<button class="p-close" aria-label="Zamknij panel pola"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 4 8 8m0-8-8 8" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg></button></header>' +
    `<div class="p-scroll">${overall}` +
    `<section class="sec"><h4>Zagrożenia <span class="when">${esc(when)}</span></h4>` +
    `<ul class="threats">${raised.map((r) => threatRow(r, state.open.has(r.threat.code), lead)).join("")}${lowGroup}</ul></section>` +
    `<section class="sec"><div class="sec-row"><h4>Ryzyko w sezonie</h4><div class="seg" role="group" aria-label="Zakres wykresu">` +
    `<button data-range="recent" class="${state.range === "recent" ? "on" : ""}" aria-pressed="${state.range === "recent"}">3 miesiące</button>` +
    `<button data-range="season" class="${state.range === "season" ? "on" : ""}" aria-pressed="${state.range === "season"}">sezon</button></div></div>` +
    `<div class="chart-host"></div><p class="chart-note">Trzy najwyższe zagrożenia tego dnia. Linia przerywana: ${forecastDays === 1 ? "najbliższy dzień" : `najbliższe ${forecastDays} dni`} z prognozy.</p></section>` +
    `${about(detail)}</div>`;

  const chartHost = host.querySelector<HTMLElement>(".chart-host")!;
  if (!series) {
    chartHost.innerHTML = '<div class="skeleton chart-skel"></div>';
    return;
  }
  const names = new Map(risks.map((r) => [r.threat.code, r.threat.name]));
  const top = risks.slice(0, 3).map((r) => r.threat.code).sort();  // fixed slot order within the chart
  const picked: ChartSeries[] = top
    .map((code, k) => {
      const s = series.threats.find((t) => t.threat_code === code);
      return s ? { code, name: names.get(code) ?? code, color: SERIES[k], points: s.points } : null;
    })
    .filter((s): s is ChartSeries => s != null);
  const to = series.to;
  const recent = addDays(today, -90) > series.from ? addDays(today, -90) : series.from;
  const from = state.range === "season" ? seasonStart(picked, series.from, today) : recent;
  if (picked.length) renderSeasonChart(chartHost, picked, from, to, today, viewDate);
  else chartHost.innerHTML = '<p class="muted">Brak danych do wykresu.</p>';
}
