// Levels, colours, dates and Polish labels used across the map. Dates are always "YYYY-MM-DD" strings from
// the API or ctx.clock; the browser's own date is never read.

import type { Level } from "./contract";

/** Agreed cut-offs (database.md → Risk): low < 0.33 <= medium < 0.66 <= high. */
export const CUT_MEDIUM = 0.33;
export const CUT_HIGH = 0.66;

/** For rows that carry only a score (GET /api/risks/?date=); explanations always carry their own `level`. */
export function levelOf(score: number): Level {
  return score >= CUT_HIGH ? "high" : score >= CUT_MEDIUM ? "medium" : "low";
}

export const LEVEL_RANK: Record<Level, number> = { low: 0, medium: 1, high: 2 };

export const LEVEL_LABEL: Record<Level, string> = { low: "niskie", medium: "średnie", high: "wysokie" };
export const LEVEL_TITLE: Record<Level, string> = { low: "Niskie ryzyko", medium: "Średnie ryzyko", high: "Wysokie ryzyko" };
/** "Pokaż tylko pola z ryzykiem wysokim" */
export const LEVEL_INSTR: Record<Level, string> = { low: "niskim", medium: "średnim", high: "wysokim" };

/** Short labels for the filter chips. */
export const CATEGORY_SHORT: Record<string, string> = {
  fungal: "grzyby", bacterial: "bakterie", viral: "wirusy", pest: "szkodniki", weed: "chwasty",
};

export const CATEGORY_LABEL: Record<string, string> = {
  fungal: "choroby grzybowe",
  bacterial: "choroby bakteryjne",
  viral: "wirusy",
  pest: "szkodniki",
  weed: "chwasty",
};

const CROP_PL: Record<number, string> = {
  1110: "Pszenica", 1120: "Jęczmień", 1130: "Kukurydza", 1140: "Ryż", 1150: "Inne zboża", 1210: "Warzywa",
  1220: "Strączkowe", 1310: "Ziemniaki", 1320: "Burak cukrowy", 1410: "Słonecznik", 1420: "Soja", 1430: "Rzepak",
  1440: "Len, bawełna, konopie", 2100: "Winorośl", 2310: "Owoce", 3100: "Inna uprawa polowa", 0: "Bez uprawy",
};

/** Display name of a crop class: the platform sends English names; the interface is Polish. */
export function cropName(crop: { code: number; name: string } | null | undefined): string {
  if (!crop) return "—";
  return CROP_PL[crop.code] ?? crop.name;
}

export const ACTION_LABEL: Record<string, string> = { wait: "Bez zabiegu", monitor: "Obserwuj", treat: "Rozważ zabieg" };

// --- dates ---------------------------------------------------------------------------------------

function toUtc(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

export function addDays(iso: string, days: number): string {
  const t = toUtc(iso);
  t.setUTCDate(t.getUTCDate() + days);
  return t.toISOString().slice(0, 10);
}

export function daysBetween(a: string, b: string): number {
  return Math.round((toUtc(b).getTime() - toUtc(a).getTime()) / 86_400_000);
}

const MONTHS_GEN = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
  "października", "listopada", "grudnia"];
const MONTHS_SHORT = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"];
const WEEKDAYS_SHORT = ["nd", "pn", "wt", "śr", "cz", "pt", "sb"];

/** "15 czerwca 2024" */
export function longDate(iso: string): string {
  const t = toUtc(iso);
  return `${t.getUTCDate()} ${MONTHS_GEN[t.getUTCMonth()]} ${t.getUTCFullYear()}`;
}

/** "15 cze", "30 maja" (May has no abbreviation, so it takes the genitive like a written date) */
export function shortDate(iso: string): string {
  const t = toUtc(iso);
  const m = t.getUTCMonth();
  return `${t.getUTCDate()} ${m === 4 ? "maja" : MONTHS_SHORT[m]}`;
}

export function monthShort(iso: string): string {
  return MONTHS_SHORT[toUtc(iso).getUTCMonth()];
}

/** "pt" */
export function weekday(iso: string): string {
  return WEEKDAYS_SHORT[toUtc(iso).getUTCDay()];
}

/** A number in Polish notation (decimal comma). */
export function num(v: number, digits = 1): string {
  return (+v.toFixed(digits)).toLocaleString("pl-PL");
}

export function pct(x: number | null | undefined): string {
  return x == null ? "—" : `${Math.round(x * 100)}%`;
}

export function ha(x: number): string {
  return `${x.toLocaleString("pl-PL", { maximumFractionDigits: 1 })} ha`;
}

export function esc(s: unknown): string {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}
