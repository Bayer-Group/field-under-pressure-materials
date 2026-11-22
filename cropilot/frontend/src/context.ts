// The context every module gets (docs/interfaces.md -> Frontend modules). Nothing more.

import type { Api } from "./api/client";
import type { EventBus } from "./events";

export interface AppContext {
  api: Api; // typed calls to the platform API
  events: EventBus; // see events.ts
  clock: { today: string; forecastDays: number }; // updated in place by main.ts before "date:changed"
}
