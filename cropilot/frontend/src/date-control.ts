// The demo date control in the header: ‹ [date] › +7 dni -> PUT /api/clock/. The date box opens the
// browser's date picker. Moving the date makes the engine recompute risks, which can take seconds, so the
// control shows that it is working and ignores clicks until the request returns (it keeps the focus).
// Typed dates are saved on Enter or when the box loses focus, never half-typed ("0002-05-31"); the picker's
// choice is saved at once. Dates outside the server's min_date..max_date are refused here already, and a jump
// of more than a month asks first (it can recompute a whole season).

import { errorMessage } from "./api/client";
import type { Clock } from "./api/types";
import type { AppContext } from "./context";
import { h, isIsoDate, longDate, shiftDate } from "./dom";

const BIG_JUMP_DAYS = 31;
const ERROR_VISIBLE_MS = 8000;

function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}

export function initDateControl(
  container: HTMLElement,
  ctx: AppContext,
  onSaved: (clock: Clock) => void,
  limits: { min: string | null; max: string | null } = { min: null, max: null },
): void {
  const label = h("span", { class: "date-label" });
  const input = h("input", { type: "date", value: ctx.clock.today, "aria-label": "Wybierz datę demo" });
  if (limits.min) input.min = limits.min;
  if (limits.max) input.max = limits.max;
  const box = h("label", { class: "date-box", title: "Zmień datę demo" }, label, input);
  const back = h("button", { type: "button", class: "step", title: "Dzień wcześniej", "aria-label": "Dzień wcześniej" }, "‹");
  const next = h("button", { type: "button", class: "step", title: "Dzień później", "aria-label": "Dzień później" }, "›");
  const week = h("button", { type: "button", class: "wide", title: "Tydzień później" }, "+7 dni");
  const status = h("span", { class: "date-status", role: "status" });
  container.replaceChildren(back, box, next, week, status);

  let busy = false;
  let typing = false; // keys were pressed in the date box since the last save
  let errorTimer: number | undefined;

  const show = () => {
    input.value = ctx.clock.today;
    label.textContent = longDate(ctx.clock.today);
    const atMin = limits.min !== null && ctx.clock.today <= limits.min;
    const atMax = limits.max !== null && ctx.clock.today >= limits.max;
    back.toggleAttribute("aria-disabled", atMin);
    next.toggleAttribute("aria-disabled", atMax);
    week.toggleAttribute("aria-disabled", atMax);
  };

  // aria-disabled, not disabled: a disabled button drops the keyboard focus to <body> after every step
  const setBusy = (value: boolean) => {
    busy = value;
    for (const control of [input, back, next, week]) control.toggleAttribute("aria-disabled", value);
    container.classList.toggle("busy", value);
    container.setAttribute("aria-busy", String(value));
  };

  const showError = (text: string) => {
    status.textContent = text;
    status.dataset.state = "error";
    window.clearTimeout(errorTimer);
    errorTimer = window.setTimeout(clearStatus, ERROR_VISIBLE_MS);
  };
  const clearStatus = () => {
    status.textContent = "";
    delete status.dataset.state;
  };
  status.addEventListener("click", () => {
    if (status.dataset.state === "error") clearStatus();
  });

  const clamp = (day: string): string => {
    if (limits.min && day < limits.min) return limits.min;
    if (limits.max && day > limits.max) return limits.max;
    return day;
  };

  const save = async (wanted: string) => {
    typing = false;
    if (busy || !isIsoDate(wanted) || wanted === ctx.clock.today) return show();
    const today = clamp(wanted);
    if (today !== wanted) {
      showError(`Datę demo można ustawić od ${longDate(limits.min ?? today)} do ${longDate(limits.max ?? today)}.`);
      return show();
    }
    const jump = Math.abs(daysBetween(ctx.clock.today, today));
    if (jump > BIG_JUMP_DAYS && !window.confirm(`Przesunąć datę demo o ${jump} dni (na ${longDate(today)})? Przeliczenie ryzyk może potrwać.`)) {
      return show();
    }
    setBusy(true);
    label.textContent = longDate(today);
    status.textContent = "Przeliczanie ryzyk…";
    status.dataset.state = "busy";
    try {
      const clock = await ctx.api.putClock(today);
      onSaved(clock);
      clearStatus();
    } catch (error) {
      showError(`Nie zmieniono daty: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
      show();
    }
  };

  // the picker fires "change" once with the chosen day; typing fires it for every complete part of the date
  input.addEventListener("change", () => {
    if (typing) {
      if (isIsoDate(input.value)) label.textContent = longDate(input.value); // show what is being typed
      return;
    }
    void save(input.value);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") void save(input.value);
    else if (event.key === "Escape") {
      typing = false;
      show();
      input.blur();
    } else if (event.key.length === 1 || event.key === "Backspace" || event.key.startsWith("Arrow")) typing = true;
  });
  input.addEventListener("blur", () => {
    if (typing) void save(input.value);
  });
  // a click anywhere on the box opens the picker (the input itself is invisible, on top of the label)
  input.addEventListener("click", () => {
    try {
      input.showPicker();
    } catch {
      // older browsers: the focused input still takes typing
    }
  });
  const step = (button: HTMLButtonElement, days: number) =>
    button.addEventListener("click", () => {
      if (!button.hasAttribute("aria-disabled")) void save(shiftDate(ctx.clock.today, days));
    });
  step(back, -1);
  step(next, 1);
  step(week, 7);
  show();
}
