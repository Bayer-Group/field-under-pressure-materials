// Entry point of the frontend bundle (built to static/frontend/dist/main.js).
// Creates the event bus and the context, loads the demo date, mounts the chat and the map once, and
// runs the demo date control (docs/interfaces.md -> Frontend modules).

import { Api, errorMessage } from "./api/client";
import type { Clock } from "./api/types";
import { initChat } from "./chat";
import type { AppContext } from "./context";
import { initDateControl } from "./date-control";
import { h } from "./dom";
import { EventBus } from "./events";
import { initMap } from "./map";

function byId(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (!element) throw new Error(`#${id} is missing from the page template`);
  return element;
}

function setStatus(element: HTMLElement, text: string, state: "ok" | "error" | "busy"): void {
  element.textContent = text;
  element.title = text; // the header may cut a long message short
  element.dataset.state = state;
}

const HEALTH_EVERY_MS = 60_000;

async function showPlatformStatus(api: Api, element: HTMLElement, events?: EventBus): Promise<void> {
  try {
    const health = await api.health();
    const assistant = health.assistant;
    if (events && assistant) {
      events.emit("assistant:status", { available: assistant.available, rag: assistant.rag, reason: assistant.reason ?? null });
    }
    if (!health.database) setStatus(element, "Brak połączenia z bazą danych", "error");
    else if (assistant && !assistant.available) setStatus(element, "Połączono · asystent wyłączony", "ok");
    else setStatus(element, "Połączono", "ok");
  } catch (error) {
    setStatus(element, `Serwer niedostępny: ${errorMessage(error)}`, "error");
  }
}

/**
 * Phones: the map and the chat do not fit one above the other (the chat's input ended below the screen), so a
 * tab bar shows one of them. The chat sending field:focus (or a click on a source) switches to the map; selecting
 * a field leaves the user where they are. Hidden on wider screens (style.css).
 */
function initPhoneTabs(main: HTMLElement, events: EventBus): void {
  const tabs = (["map", "chat"] as const).map((tab) =>
    h("button", { type: "button", role: "tab", "data-tab": tab, "aria-controls": tab },
      tab === "map" ? "Mapa" : "Asystent"),
  );
  const bar = h("nav", { class: "phone-tabs", role: "tablist", "aria-label": "Widok" }, ...tabs);
  const show = (tab: "map" | "chat") => {
    main.dataset.tab = tab;
    for (const button of tabs) button.setAttribute("aria-selected", String(button.dataset.tab === tab));
  };
  for (const button of tabs) button.addEventListener("click", () => show(button.dataset.tab as "map" | "chat"));
  events.on("field:focus", () => show("map"));
  main.before(bar);
  show("map");
}

async function start(): Promise<void> {
  const status = byId("platform-status");
  const main = byId("app-main");
  const api = new Api();
  const events = new EventBus();

  // Safety net: an error nobody caught still becomes a visible message, never a silent failure; the status
  // goes back to the real one after a while (one failed chunk load must not say "error" for the whole demo).
  let errorTimer: number | undefined;
  window.addEventListener("unhandledrejection", (event) => {
    event.preventDefault();
    setStatus(status, `Błąd: ${errorMessage(event.reason)}`, "error");
    window.clearTimeout(errorTimer);
    errorTimer = window.setTimeout(() => void showPlatformStatus(api, status, events), 8000);
  });

  let clock: Clock;
  try {
    clock = await api.getClock();
  } catch (error) {
    // No date, no date-dependent requests (and never the browser's date).
    setStatus(status, "Nie można wczytać daty demo", "error");
    main.replaceChildren(
      h(
        "div",
        { class: "page-error" },
        h("h2", {}, "Nie można wczytać daty demo"),
        h("p", {}, errorMessage(error)),
        h("p", { class: "muted" }, "Załaduj scenariusz (python manage.py scenario switch demo_2024) albo ustaw datę w /admin/, a potem odśwież stronę."),
      ),
    );
    return;
  }

  const ctx: AppContext = { api, events, clock: { today: clock.today, forecastDays: clock.forecast_days } };

  initDateControl(
    byId("date-control"),
    ctx,
    (saved) => {
      // Update the object the modules already hold, then tell them.
      ctx.clock.today = saved.today;
      ctx.clock.forecastDays = saved.forecast_days;
      events.emit("date:changed", { today: saved.today });
    },
    { min: clock.min_date ?? null, max: clock.max_date ?? null },
  );

  initChat(byId("chat"), ctx);
  initMap(byId("map"), ctx);
  initPhoneTabs(main, events);
  // after the chat listens: it learns whether it can answer; checked again every minute
  void showPlatformStatus(api, status, events);
  window.setInterval(() => void showPlatformStatus(api, status, events), HEALTH_EVERY_MS);
}

void start();
