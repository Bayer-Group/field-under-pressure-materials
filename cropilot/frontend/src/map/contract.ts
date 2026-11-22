// What the map needs from the rest of the page. The API types come from the generated schema
// (api/types.ts <- api/schema.d.ts <- frontend/openapi.yml); only the explanation is typed here, because the
// schema passes it through untyped (docs/database.md → "Explanation, version 1").

import type * as Api from "../api/types";
import type { EventBus } from "../events";
import { levelOf } from "./format";

// --- Platform API responses (generated) ------------------------------------------------------------

export type Level = Api.RiskLevel;
export type CropRef = Api.FieldDetail["crop"];
export type Clock = Api.Clock;
export type Threat = Api.Threat;
export type FieldFeature = Api.FieldFeature;
export type FieldCollection = Api.FieldFeatureCollection;
export type FieldDetail = Api.FieldDetail;
export type DayRisks = Api.DayRisks;
export type FieldRiskSeries = Api.FieldRiskSeries;

// --- Explanation, version 1 (database.md). Readers ignore keys they don't know. --------------------

export interface Driver {
  factor: string;
  label: string;
  value?: number | string | null;
  unit?: string | null;
  threshold?: string | null;
  multiplier?: number | null;
  effect: number | null;
  kind?: string;
  observed_on?: string;
  text?: string;
}

export interface SprayWindow {
  date: string;
  quality: "optimal" | "acceptable" | string;
  conditions?: unknown;
  rule?: string;
  note?: string;
}

export interface Explanation {
  version: number;
  summary: string;
  level: Level;
  score: number;
  threat?: { code: string; name_pl?: string; name_en?: string; category?: string };
  as_of?: string;
  crop?: { code: number; source: string };
  growth_stage?: { bbch: number; name: string; method?: string; sowing_assumed?: string | null; confidence?: number };
  drivers?: Driver[];
  action?: { type: "wait" | "monitor" | "treat" | string; text: string; threshold?: string | null; spray_window?: SprayWindow | null };
  severity?: number;
  expected_loss?: number;
  confidence?: number;
  confidence_observed?: number;
  forecast_lead_days?: number;
  notes?: string[];
}

/** GET /api/fields/{id}/risks/{date}/, with each explanation read as version 1 (readExplanations). */
export interface FieldDayRisks {
  field_id: number;
  date: string;
  risks: { threat: Api.FieldDayRisk["threat"]; score: number; explanation: Explanation }[];
}

/**
 * The API passes `explanation` through as the engine wrote it. The engine always writes version 1, but rows
 * from other writers (the assistant's dev seed) may lack keys: the level then comes from the score with the
 * agreed cut-offs (as the API does for /api/risks/), and drivers or an action without their text are left out.
 */
export function readExplanations(day: Api.FieldDayRisks): FieldDayRisks {
  return {
    field_id: day.field_id,
    date: day.date,
    risks: day.risks.map((r) => {
      const raw = (r.explanation ?? {}) as Record<string, unknown> & Partial<Explanation>;
      const level = raw.level === "low" || raw.level === "medium" || raw.level === "high" ? raw.level : levelOf(r.score);
      const drivers = Array.isArray(raw.drivers) ? raw.drivers.filter((d) => typeof d?.label === "string") : undefined;
      const action = raw.action && typeof raw.action.text === "string" ? raw.action : undefined;
      const explanation: Explanation = {
        ...raw,
        version: typeof raw.version === "number" ? raw.version : 0,
        summary: typeof raw.summary === "string" ? raw.summary : "",
        level,
        score: typeof raw.score === "number" ? raw.score : r.score,
        drivers,
        action,
      };
      return { threat: r.threat, score: r.score, explanation };
    }),
  };
}

// --- The context (interfaces.md → Frontend modules) --------------------------------------------------

/** The calls of `ctx.api` the map uses: one per agreed endpoint (api/client.ts has them all). */
export interface MapApi {
  getThreats(): Promise<Threat[]>;
  getFields(): Promise<FieldCollection>;
  getField(id: number): Promise<FieldDetail>;
  getRisks(date?: string): Promise<DayRisks>;
  getFieldRisks(id: number, range?: { from?: string; to?: string }): Promise<FieldRiskSeries>;
  getFieldDayRisks(id: number, date: string): Promise<Api.FieldDayRisks>;
}

/** The part of the page's AppContext (../context.ts) the map uses; main.ts passes the full one. */
export interface AppContext {
  api: MapApi;
  events: EventBus;
  clock: { today: string; forecastDays: number }; // updated in place by main.ts before "date:changed"
}
