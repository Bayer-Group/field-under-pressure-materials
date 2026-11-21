import { apiConfig } from '../config/apiConfig';

export class ApiError extends Error {
  readonly status: number;
  readonly endpoint: string;
  readonly detail: unknown;

  constructor(message: string, status: number, endpoint: string, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.endpoint = endpoint;
    this.detail = detail;
  }
}

interface RequestOptions {
  params?: Record<string, string | number | undefined>;
  signal?: AbortSignal;
  body?: unknown;
  timeoutMs?: number;
}

function buildUrl(path: string, params?: Record<string, string | number | undefined>): string {
  const url = new URL(`${apiConfig.baseUrl}${path}`, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

async function request<T>(
  method: 'GET' | 'POST',
  path: string,
  options: RequestOptions = {},
  decode: (response: Response) => Promise<T> = (response) => response.json() as Promise<T>,
  accept = 'application/json',
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(new DOMException('Request timed out', 'TimeoutError')),
    options.timeoutMs ?? apiConfig.requestTimeoutMs,
  );

  const onExternalAbort = () => controller.abort(options.signal?.reason);
  if (options.signal?.aborted) {
    onExternalAbort();
  } else {
    options.signal?.addEventListener('abort', onExternalAbort, { once: true });
  }

  try {
    const response = await fetch(buildUrl(path, options.params), {
      method,
      headers: {
        Accept: accept,
        ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });

    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { detail?: unknown } | null;
      const detail = payload?.detail;
      const message =
        typeof detail === 'string'
          ? detail
          : detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string'
            ? detail.message
            : `HTTP ${response.status}: ${response.statusText}`;
      throw new ApiError(message, response.status, path, detail);
    }

    return await decode(response);
  } finally {
    window.clearTimeout(timeout);
    options.signal?.removeEventListener('abort', onExternalAbort);
  }
}

export const httpClient = {
  get: <T>(path: string, options?: Omit<RequestOptions, 'body'>) => request<T>('GET', path, options),
  getBlob: (path: string, options?: Omit<RequestOptions, 'body'>) =>
    request('GET', path, options, (response) => response.blob(), 'image/tiff'),
  post: <T>(path: string, body: unknown, options?: Omit<RequestOptions, 'body'>) =>
    request<T>('POST', path, { ...options, body }),
};
