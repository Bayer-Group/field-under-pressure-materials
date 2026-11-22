// Charts in the chat (docs/interfaces.md -> Chat -> chart): a Vega-Lite v5 spec with inline data,
// drawn with vega-embed. vega-embed is large, so it is a separate chunk, loaded only when a message
// has a chart. The answer text stands on its own, so a chart that can't be drawn is just left out.

import type { ChartSpec } from "../api/types";

/** True if the spec loads data from a URL anywhere (`data.url`, also inside layers or lookups). */
export function hasDataUrl(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(hasDataUrl);
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  const data = record.data;
  if (data && typeof data === "object" && !Array.isArray(data) && "url" in data) return true;
  return Object.values(record).some(hasDataUrl);
}

// Polish dates and numbers on the axes (d3 locale definitions).
const TIME_LOCALE_PL = {
  dateTime: "%A, %e %B %Y, %X",
  date: "%d.%m.%Y",
  time: "%H:%M:%S",
  periods: ["AM", "PM"],
  days: ["niedziela", "poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota"],
  shortDays: ["nd", "pn", "wt", "śr", "cz", "pt", "sb"],
  months: ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień"],
  shortMonths: ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"],
};
const NUMBER_LOCALE_PL = { decimal: ",", thousands: "\u00a0", grouping: [3], currency: ["", " zł"] };

// Vega views keep timers and listeners until finalised: release the ones whose message left the page (F-13k).
const views: { container: HTMLElement; finalize: () => void }[] = [];

/** Finalises the charts no longer on the page (call after replacing the message list). */
export function releaseDetachedCharts(): void {
  for (let k = views.length - 1; k >= 0; k--) {
    if (!views[k].container.isConnected) {
      try {
        views[k].finalize();
      } catch {
        // already gone
      }
      views.splice(k, 1);
    }
  }
}

export async function renderChart(container: HTMLElement, spec: ChartSpec): Promise<void> {
  if (hasDataUrl(spec)) return; // never fetch chart data from a URL
  try {
    const { default: embed } = await import("vega-embed");
    const dark =
      document.documentElement.dataset.theme === "dark" ||
      (document.documentElement.dataset.theme !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    const result = await embed(container, { ...spec, width: "container", background: "transparent" } as Parameters<typeof embed>[1], {
      actions: false,
      renderer: "svg",
      theme: dark ? "dark" : undefined,
      timeFormatLocale: TIME_LOCALE_PL,
      formatLocale: NUMBER_LOCALE_PL,
    });
    views.push({ container, finalize: () => result.finalize() });
  } catch {
    container.replaceChildren();
    container.classList.add("chart-failed");
    container.textContent = "Nie udało się narysować wykresu.";
  }
}
