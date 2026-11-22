// Season chart of one field: risk score (0–1) per threat over time. Solid up to today (season so far),
// dashed for the coming days, the agreed level cut-offs as named bands, crosshair + tooltip (pointer, or the
// arrow keys once the chart has the focus), a marker on the coming day the map shows, and a redraw when the
// panel changes width.

import { CUT_HIGH, CUT_MEDIUM, LEVEL_LABEL, addDays, daysBetween, esc, levelOf, monthShort, num, shortDate } from "./format";

export interface ChartSeries {
  code: string;
  name: string;
  color: string;           // categorical slot, assigned by the caller in a fixed order
  points: { date: string; score: number }[];
}

const SVG = "http://www.w3.org/2000/svg";
const H = 240;
const M = { top: 26, right: 12, bottom: 26, left: 12 };

function el<K extends keyof SVGElementTagNameMap>(name: K, attrs: Record<string, string | number>, parent?: Element) {
  const node = document.createElementNS(SVG, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  parent?.appendChild(node);
  return node;
}

const redraws = new WeakMap<HTMLElement, { width: number; draw: () => void; observer: ResizeObserver }>();

/** Redraw at the new width when the host is resized (one observer per host). */
function watchWidth(host: HTMLElement, draw: () => void): void {
  const known = redraws.get(host);
  if (known) {
    known.draw = draw;
    known.width = host.clientWidth;
    return;
  }
  const entry = { width: host.clientWidth, draw, observer: new ResizeObserver(() => {
    const w = host.clientWidth;
    if (w > 0 && Math.abs(w - entry.width) > 8) {
      entry.width = w;
      entry.draw();
    }
  }) };
  entry.observer.observe(host);
  redraws.set(host, entry);
}

export function renderSeasonChart(host: HTMLElement, series: ChartSeries[], from: string, to: string, today: string,
                                  viewDate: string = today): void {
  watchWidth(host, () => renderSeasonChart(host, series, from, to, today, viewDate));
  host.replaceChildren();
  host.classList.add("fup-chart");
  const W = Math.max(280, Math.round(host.clientWidth || 360));   // drawn at its real width: text stays 10-11 px
  const span = Math.max(1, daysBetween(from, to));
  const iw = W - M.left - M.right;
  const ih = H - M.top - M.bottom;
  const x = (d: string) => M.left + (daysBetween(from, d) / span) * iw;
  const y = (s: number) => M.top + (1 - s) * ih;

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", tabindex: 0,
    "aria-label": "Ryzyko w sezonie. Strzałki w lewo i w prawo pokazują wartości kolejnych dni." }, host);

  // named level bands (the agreed cut-offs), labelled inside the plot
  const bands: [number, number, keyof typeof LEVEL_LABEL][] = [[CUT_HIGH, 1, "high"], [CUT_MEDIUM, CUT_HIGH, "medium"], [0, CUT_MEDIUM, "low"]];
  for (const [lo, hi, lvl] of bands) {
    el("rect", { x: M.left, y: y(hi), width: iw, height: y(lo) - y(hi), class: `band band-${lvl}` }, svg);
    const t = el("text", { x: M.left + 6, y: y(hi) + 13, class: `band-label band-label-${lvl}` }, svg);
    t.textContent = LEVEL_LABEL[lvl];
  }
  for (const s of [CUT_MEDIUM, CUT_HIGH]) el("line", { x1: M.left, x2: M.left + iw, y1: y(s), y2: y(s), class: "grid" }, svg);
  el("line", { x1: M.left, x2: M.left + iw, y1: y(0), y2: y(0), class: "axis" }, svg);

  // month ticks
  let d = from.slice(0, 8) + "01";
  if (d < from) d = addDays(d, 32).slice(0, 8) + "01";
  const step = span > 200 ? 2 : 1;
  let i = 0;
  while (d <= to) {
    if (i++ % step === 0) {
      el("line", { x1: x(d), x2: x(d), y1: M.top + ih, y2: M.top + ih + 4, class: "axis" }, svg);
      const t = el("text", { x: x(d), y: H - 8, class: "tick", "text-anchor": "middle" }, svg);
      t.textContent = monthShort(d);
    }
    d = addDays(d, 32).slice(0, 8) + "01";
  }

  // coming days: shaded zone with its name, and the "today" marker
  if (today < to) {
    el("rect", { x: x(today), y: M.top, width: x(to) - x(today), height: ih, class: "future" }, svg);
  }
  if (today >= from && today <= to) {
    el("line", { x1: x(today), x2: x(today), y1: M.top - 2, y2: M.top + ih, class: "today" }, svg);
    const label = el("g", { class: "today-tag" }, svg);
    const tw = 34;
    const tx = Math.min(Math.max(x(today) - tw / 2, M.left), M.left + iw - tw);
    el("rect", { x: tx, y: 4, width: tw, height: 17, rx: 8.5 }, label);
    const t = el("text", { x: tx + tw / 2, y: 16.5, "text-anchor": "middle" }, label);
    t.textContent = "dziś";
  }

  // the coming day the map shows (day strip), if it is not today
  if (viewDate > today && viewDate >= from && viewDate <= to) {
    el("line", { x1: x(viewDate), x2: x(viewDate), y1: M.top, y2: M.top + ih, class: "viewed" }, svg);
    const t = el("text", { x: Math.min(x(viewDate) + 4, M.left + iw - 24), y: M.top + 11, class: "viewed-tag" }, svg);
    t.textContent = `+${daysBetween(today, viewDate)}`;
  }

  // lines: solid to today, dashed after
  const path = (pts: { date: string; score: number }[]) =>
    pts.map((p, k) => `${k ? "L" : "M"}${x(p.date).toFixed(1)},${y(p.score).toFixed(1)}`).join("");
  for (const s of series) {
    const pts = s.points.filter((p) => p.date >= from && p.date <= to);
    const past = pts.filter((p) => p.date <= today);
    const future = pts.filter((p) => p.date >= today);
    if (past.length > 1) el("path", { d: path(past), class: "line", stroke: s.color }, svg);
    if (future.length > 1) el("path", { d: path(future), class: "line dashed", stroke: s.color }, svg);
    const last = past[past.length - 1];
    if (last) el("circle", { cx: x(last.date), cy: y(last.score), r: 4, fill: s.color, class: "dot" }, svg);
  }

  // hover: crosshair + tooltip on the side of the plot away from the cursor
  const cross = el("line", { y1: M.top, y2: M.top + ih, class: "cross", visibility: "hidden" }, svg);
  const marks = series.map((s) => el("circle", { r: 4, fill: s.color, class: "dot", visibility: "hidden" }, svg));
  const tip = document.createElement("div");
  tip.className = "fup-tip";
  tip.hidden = true;
  host.appendChild(tip);
  const hit = el("rect", { x: M.left, y: 0, width: iw, height: H, fill: "transparent" }, svg);
  const byDate = series.map((s) => new Map(s.points.map((p) => [p.date, p.score])));

  let cursor = viewDate >= from && viewDate <= to ? viewDate : today;
  const show = (day: string, clientX: number | null) => {
    cursor = day;
    cross.setAttribute("x1", String(x(day)));
    cross.setAttribute("x2", String(x(day)));
    cross.setAttribute("visibility", "visible");
    const rows: string[] = [];
    let ys = 0;
    let n = 0;
    series.forEach((s, k) => {
      const v = byDate[k].get(day);
      if (v == null) {
        marks[k].setAttribute("visibility", "hidden");
        return;
      }
      marks[k].setAttribute("cx", String(x(day)));
      marks[k].setAttribute("cy", String(y(v)));
      marks[k].setAttribute("visibility", "visible");
      ys += y(v);
      n++;
      rows.push(`<div class="tip-row"><span class="swatch" style="background:${s.color}"></span><span class="tip-name">${esc(s.name)}</span>` +
        `<span class="tip-val">${num(v, 2)} · ${LEVEL_LABEL[levelOf(v)]}</span></div>`);
    });
    const when = day > today ? ` · prognoza +${daysBetween(today, day)}` : day === today ? " · dziś" : "";
    tip.innerHTML = `<div class="tip-date">${shortDate(day)}${when}</div>${rows.join("") || '<div class="tip-row">brak danych</div>'}`;
    tip.hidden = false;
    const hostBox = host.getBoundingClientRect();
    const svgBox = svg.getBoundingClientRect();
    const left = clientX != null ? clientX - hostBox.left : svgBox.left - hostBox.left + (x(day) / W) * svgBox.width;
    const onRight = left < hostBox.width / 2;
    tip.style.left = onRight ? `${left + 14}px` : "";
    tip.style.right = onRight ? "" : `${hostBox.width - left + 14}px`;
    const pointsHigh = n ? ys / n < M.top + ih / 2 : false;   // the points sit in the upper half: tooltip goes low
    tip.style.top = pointsHigh ? "" : `${M.top}px`;
    tip.style.bottom = pointsHigh ? `${hostBox.height - (M.top + ih) + 4}px` : "";
  };
  const hide = () => {
    cross.setAttribute("visibility", "hidden");
    marks.forEach((m) => m.setAttribute("visibility", "hidden"));
    tip.hidden = true;
  };
  hit.addEventListener("pointermove", (ev) => {
    const box = svg.getBoundingClientRect();
    const px = ((ev.clientX - box.left) / box.width) * W;
    const day = addDays(from, Math.round(((px - M.left) / iw) * span));
    if (day >= from && day <= to) show(day, ev.clientX);
  });
  hit.addEventListener("pointerleave", hide);
  // keyboard: the same crosshair, one day per arrow (a week with Shift), Home/End, Esc hides it
  svg.addEventListener("focus", () => show(cursor, null));
  svg.addEventListener("blur", hide);
  svg.addEventListener("keydown", (ev) => {
    const steps: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1 };
    let day: string | null = null;
    if (ev.key in steps) day = addDays(cursor, steps[ev.key] * (ev.shiftKey ? 7 : 1));
    else if (ev.key === "Home") day = from;
    else if (ev.key === "End") day = to;
    else if (ev.key === "Escape") return hide();
    if (day == null) return;
    ev.preventDefault();
    show(day < from ? from : day > to ? to : day, null);
  });

  // legend: identity never by colour alone
  const legend = document.createElement("div");
  legend.className = "fup-legend";
  legend.innerHTML = series.map((s) => `<span class="leg"><span class="swatch" style="background:${s.color}"></span>${esc(s.name)}</span>`).join("") +
    '<span class="leg muted"><span class="dash"></span>prognoza</span>';
  host.appendChild(legend);
}
