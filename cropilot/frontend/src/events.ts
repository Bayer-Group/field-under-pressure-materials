// The typed event bus between the page's modules (docs/interfaces.md -> Events between map and chat).
// One private EventTarget, created in main.ts and passed in the context; never `document`.

export interface AppEvents {
  "field:selected": { fieldId: number | null }; // null = no field selected
  "field:focus": { fieldId: number };
  "date:changed": { today: string };
  "risks:updated": { fieldIds: number[] };
  // from main.ts (GET /api/health/): can the chat answer? (no LLM keys -> the chat is greyed out)
  "assistant:status": { available: boolean; rag: boolean; reason: string | null };
}

export class EventBus {
  private target = new EventTarget();

  emit<K extends keyof AppEvents>(type: K, detail: AppEvents[K]): void {
    this.target.dispatchEvent(new CustomEvent(type, { detail }));
  }

  on<K extends keyof AppEvents>(type: K, handler: (detail: AppEvents[K]) => void): () => void {
    const listener = (event: Event) => handler((event as CustomEvent<AppEvents[K]>).detail);
    this.target.addEventListener(type, listener);
    return () => this.target.removeEventListener(type, listener); // call to stop listening
  }
}
