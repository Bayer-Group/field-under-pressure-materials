// Typed client for the platform API: one function per endpoint (docs/interfaces.md -> Platform API).
// A non-2xx response throws ApiError(status, detail); a stopped server is ApiError(0, …). Callers show
// `error.detail` (see errorMessage), so nothing ends up as an unhandled rejection or a blank page.

import type {
  ChatReply,
  ChatRequest,
  Clock,
  ConversationDetail,
  ConversationItem,
  DayRisks,
  FieldDayRisks,
  FieldDetail,
  FieldFeatureCollection,
  FieldRiskSeries,
  Health,
  Threat,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

// The API's error details are English (a contract shared with scripts and tests); the farmer reads Polish.
const POLISH_DETAILS: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^(\w+) must be YYYY-MM-DD$/, () => "Niepoprawna data (oczekiwany format RRRR-MM-DD)."],
  [/^(\w+) is after today \+ (\d+)$/, (m) => `Ta data jest za daleko: dane sięgają ${m[2]} dni po dacie demo.`],
  [/^from is after to$/, () => "Początek zakresu jest po jego końcu."],
  [/^to is before the default from \((.+)\)$/, (m) => `Koniec zakresu jest przed początkiem sezonu (${m[1]}).`],
  [/^today must be between (\S+) and (\S+)/, (m) => `Datę demo można ustawić od ${m[1]} do ${m[2]} (dni z danymi pogodowymi).`],
  [/^field (\d+) not found$/, () => "Nie ma już tego pola (dane zostały przeładowane). Odśwież stronę."],
  [/^conversation (\d+) not found$/, () => "Ta rozmowa już nie istnieje."],
  [/^The demo date is not set/, () => "Data demo nie jest ustawiona."],
  [/^Not found\.?$/, () => "Nie znaleziono."],
];

/** A message for the user, whatever was thrown (API details translated to Polish when known). */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    for (const [pattern, polish] of POLISH_DETAILS) {
      const match = error.detail.match(pattern);
      if (match) return polish(match);
    }
    return error.detail;
  }
  if (error instanceof Error) return error.message;
  return String(error);
}

type Method = "GET" | "PUT" | "POST";

function detailOf(data: unknown): string | null {
  if (data && typeof data === "object") {
    const detail = (data as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    // DRF validation errors: {"field": ["message", …], …}
    const parts = Object.entries(data as Record<string, unknown>).map(
      ([key, value]) => `${key}: ${Array.isArray(value) ? value.join(" ") : String(value)}`,
    );
    if (parts.length) return parts.join("; ");
  }
  return null;
}

async function request<T>(method: Method, path: string, body?: unknown, okStatuses: number[] = []): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Serwer nie odpowiada. Spróbuj ponownie za chwilę.");
  }
  let data: unknown = undefined;
  if ((response.headers.get("Content-Type") ?? "").includes("application/json")) {
    try {
      data = await response.json();
    } catch {
      data = undefined;
    }
  }
  if (!response.ok && !okStatuses.includes(response.status)) {
    const detail =
      detailOf(data) ??
      (response.status === 404
        ? "Nie znaleziono (HTTP 404)."
        : `Błąd serwera (HTTP ${response.status}). Spróbuj ponownie za chwilę.`);
    throw new ApiError(response.status, detail);
  }
  if (data === undefined) throw new ApiError(response.status, "Niepoprawna odpowiedź serwera.");
  return data as T;
}

function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined) search.set(key, value);
  const text = search.toString();
  return text ? `?${text}` : "";
}

export class Api {
  /** Health answers 503 with a body when the database is down, so 503 is not an error here. */
  health(): Promise<Health> {
    return request<Health>("GET", "/api/health/", undefined, [503]);
  }

  getClock(): Promise<Clock> {
    return request<Clock>("GET", "/api/clock/");
  }

  /** Moves the demo date; the engine recomputes the risks that change, so this can take seconds. */
  putClock(today: string): Promise<Clock> {
    return request<Clock>("PUT", "/api/clock/", { today });
  }

  getThreats(): Promise<Threat[]> {
    return request<Threat[]>("GET", "/api/threats/");
  }

  getFields(): Promise<FieldFeatureCollection> {
    return request<FieldFeatureCollection>("GET", "/api/fields/");
  }

  getField(fieldId: number): Promise<FieldDetail> {
    return request<FieldDetail>("GET", `/api/fields/${fieldId}/`);
  }

  /** Every field's risks on one day (default today; at most today + 7). */
  getRisks(date?: string): Promise<DayRisks> {
    return request<DayRisks>("GET", `/api/risks/${query({ date })}`);
  }

  /** One field's risks over time; `to` is cut at today + 7 and the response says where it stopped. */
  getFieldRisks(fieldId: number, range: { from?: string; to?: string } = {}): Promise<FieldRiskSeries> {
    return request<FieldRiskSeries>("GET", `/api/fields/${fieldId}/risks/${query(range)}`);
  }

  /** One field's risks on one day, highest first, with explanations. */
  getFieldDayRisks(fieldId: number, date: string): Promise<FieldDayRisks> {
    return request<FieldDayRisks>("GET", `/api/fields/${fieldId}/risks/${encodeURIComponent(date)}/`);
  }

  sendChat(body: ChatRequest): Promise<ChatReply> {
    return request<ChatReply>("POST", "/api/chat/", body);
  }

  listConversations(): Promise<ConversationItem[]> {
    return request<ConversationItem[]>("GET", "/api/chat/conversations/");
  }

  getConversation(conversationId: number): Promise<ConversationDetail> {
    return request<ConversationDetail>("GET", `/api/chat/conversations/${conversationId}/`);
  }
}
