// Names for the generated API types (schema.d.ts, from openapi.yml: never edit by hand), plus the few
// shapes the schema leaves open: chat citations, the explanation (version 1), and the chat's
// `chart` / `pending_action` keys (docs/interfaces.md -> Chat), typed here more precisely than the schema's objects.

import type { components } from "./schema";

type Schemas = components["schemas"];

export type Health = Schemas["Health"];
export type Clock = Schemas["Clock"];
export type Threat = Schemas["Threat"];
export type ThreatCategory = Schemas["ThreatCategory"];
export type FieldFeatureCollection = Schemas["FieldFeatureCollection"];
export type FieldFeature = Schemas["FieldFeature"];
export type FieldDetail = Schemas["FieldDetail"];
export type Soil = Schemas["Soil"];
export type RiskLevel = Schemas["RiskLevel"];
export type DayRisks = Schemas["DayRisks"];
export type DayRisk = Schemas["DayRisk"];
export type FieldRiskSeries = Schemas["FieldRiskSeries"];
export type RiskPoint = Schemas["RiskPoint"];
export type FieldDayRisks = Schemas["FieldDayRisks"];
export type FieldDayRisk = Schemas["FieldDayRisk"];
export type ConversationItem = Schemas["ConversationItem"];
export type ChatRequest = Schemas["ChatIn"];

// --- Explanation, version 1 (docs/database.md). Every key optional: readers ignore what they don't know,
// and rows from the assistant's dev seed are not version 1.

export interface ExplanationDriver {
  factor?: string;
  label?: string;
  value?: number | string | null;
  unit?: string | null;
  threshold?: string | null;
  effect?: number | null; // how much the score would drop without it; null = context only
}

export interface ExplanationV1 {
  version?: number;
  summary?: string;
  level?: RiskLevel;
  score?: number;
  as_of?: string;
  growth_stage?: { bbch?: number | null; name?: string | null; confidence?: number | null } | null;
  drivers?: ExplanationDriver[];
  action?: {
    type?: "wait" | "monitor" | "treat" | string;
    text?: string;
    threshold?: string | null;
    spray_window?: { date?: string; quality?: string } | null;
  } | null;
  confidence?: number | null;
}

// --- Chat ----------------------------------------------------------------------------------------

/** A passage of a guide: a PDF page (`page`, `printed_page`, `section`) or a spreadsheet row (`sheet`, `row`). */
export interface GuideCitation {
  type: "guide";
  document: string;
  page?: number | null;
  printed_page?: number | string | null;
  section?: string | null;
  sheet?: string | null;
  row?: number | null;
  ref?: number | null; // the number of the [n] marker in the text
}

/** A risk row the answer relies on; the chat shows it as a link that focuses the field. */
export interface RiskCitation {
  type: "risk";
  field_id: number;
  threat_code: string;
  date: string;
}

export type Citation = GuideCitation | RiskCitation;

/** Vega-Lite v5 spec, data inline (docs/interfaces.md -> Chat -> chart). */
export type ChartSpec = Record<string, unknown>;

export interface ConfirmObservationAction {
  type: "confirm_observation";
  draft: { draft_id: string; field_id: number | null; [key: string]: unknown };
}

export type PendingAction = ConfirmObservationAction | { type: string; [key: string]: unknown };

export interface ChatMessage extends Omit<Schemas["ChatMessage"], "citations" | "chart" | "pending_action"> {
  citations: Record<string, unknown>[]; // parse with toCitation(); unknown kinds are ignored
  chart?: ChartSpec | null; // always sent (null when none); optional so a missing key also reads as none
  pending_action?: PendingAction | null;
}

export interface ChatReply {
  conversation_id: number;
  message: ChatMessage;
}

export interface ConversationDetail {
  id: number;
  title: string;
  messages: ChatMessage[];
}

const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** A citation from the API, or null for kinds and shapes this page does not know. */
export function toCitation(raw: Record<string, unknown>): Citation | null {
  if (raw.type === "guide" && typeof raw.document === "string") return raw as unknown as GuideCitation;
  if (raw.type === "risk" && isNumber(raw.field_id) && typeof raw.threat_code === "string") {
    return raw as unknown as RiskCitation;
  }
  return null;
}

export function isConfirmObservation(action: PendingAction | null | undefined): action is ConfirmObservationAction {
  return (
    !!action &&
    action.type === "confirm_observation" &&
    typeof (action as ConfirmObservationAction).draft === "object" &&
    (action as ConfirmObservationAction).draft !== null
  );
}
