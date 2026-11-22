// Small DOM and date helpers for the page and the chat (the map has its own, in map/format.ts).

type Child = Node | string | number | null | undefined | false;
type Attrs = Record<string, string | number | boolean | null | undefined | EventListener>;

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Attrs = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") element.addEventListener(key.slice(2), value);
    else if (key === "class") element.className = String(value);
    else element.setAttribute(key, value === true ? "" : String(value));
  }
  append(element, ...children);
  return element;
}

export function append(parent: Node & ParentNode, ...children: Child[]): void {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    parent.append(typeof child === "number" ? String(child) : child);
  }
}

/** A decorative inline SVG icon. Only for the fixed icon strings in this codebase, never for data. */
export function icon(svg: string, className = "icon"): HTMLSpanElement {
  const span = document.createElement("span");
  span.className = className;
  span.setAttribute("aria-hidden", "true");
  span.innerHTML = svg;
  return span;
}

export const ICONS = {
  send: '<svg viewBox="0 0 20 20"><path d="M10 16V4m0 0-5 5m5-5 5 5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  plus: '<svg viewBox="0 0 16 16"><path d="M8 3v10M3 8h10" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
  field: '<svg viewBox="0 0 16 16"><path d="M2.5 5.5 8 2.5l5.5 3v5L8 13.5l-5.5-3z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M2.5 5.5 8 8.5l5.5-3M8 8.5v5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
  chat: '<svg viewBox="0 0 24 24"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4h0A1.5 1.5 0 0 1 4 14.5z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M8.5 8.5h7M8.5 11.5h4.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  doc: '<svg viewBox="0 0 16 16"><path d="M4 1.75h5.5L12.5 4.75v9.5H4z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M9.25 1.75v3.25h3.25M6 8h4.5M6 10.75h4.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
  pin: '<svg viewBox="0 0 16 16"><path d="M8 14.5s4.75-4.4 4.75-8.1a4.75 4.75 0 0 0-9.5 0c0 3.7 4.75 8.1 4.75 8.1z" fill="none" stroke="currentColor" stroke-width="1.4"/><circle cx="8" cy="6.4" r="1.7" fill="currentColor"/></svg>',
};

// --- Dates as YYYY-MM-DD strings. Never the browser's own date: the demo's date comes from the API.

/** The date `days` after a YYYY-MM-DD date (pure calendar arithmetic). */
export function shiftDate(iso: string, days: number): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10);
}

export const isIsoDate = (value: string): boolean => /^\d{4}-\d{2}-\d{2}$/.test(value);

const MONTHS_GENITIVE = [
  "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
  "lipca", "sierpnia", "września", "października", "listopada", "grudnia",
];

/** 2024-05-15 -> 15 maja 2024 */
export function longDate(iso: string): string {
  if (!isIsoDate(iso)) return iso;
  return `${Number(iso.slice(8, 10))} ${MONTHS_GENITIVE[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`;
}

/** 2024-05-15 -> 15.05.2024 */
export function formatDate(iso: string): string {
  return isIsoDate(iso) ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : iso;
}
