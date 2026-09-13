/**
 * 极薄的 fetch 封装：同源 + cookie，统一错误形状。
 *
 * 后端错误体（03 §1）：{ error: { code, message, detail } }
 */
export interface ApiErrorBody {
  error: { code: string; message: string; detail?: unknown };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: unknown;
  readonly retryAfter?: number;

  constructor(status: number, code: string, message: string, detail?: unknown, retryAfter?: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.retryAfter = retryAfter;
  }
}

const JSON_HEADERS = { 'Content-Type': 'application/json' } as const;

async function parseError(res: Response): Promise<ApiError> {
  let code = 'http_error';
  let message = `请求失败（${res.status}）`;
  let detail: unknown;
  try {
    const body = (await res.json()) as Partial<ApiErrorBody>;
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      detail = body.error.detail;
    }
  } catch {
    /* 非 JSON 错误体，保留默认文案 */
  }
  const retryAfterRaw = res.headers.get('Retry-After');
  const retryAfter = retryAfterRaw ? Number(retryAfterRaw) : undefined;
  return new ApiError(res.status, code, message, detail, retryAfter);
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: 'include',
    headers: body === undefined ? undefined : JSON_HEADERS,
    body: body === undefined ? undefined : JSON.stringify(body),
    ...init,
  });
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const http = {
  get: <T>(path: string, init?: RequestInit) => request<T>('GET', path, undefined, init),
  post: <T>(path: string, body?: unknown, init?: RequestInit) =>
    request<T>('POST', path, body, init),
  put: <T>(path: string, body?: unknown, init?: RequestInit) =>
    request<T>('PUT', path, body, init),
  del: <T>(path: string, init?: RequestInit) => request<T>('DELETE', path, undefined, init),
};

/** 拼接查询串，跳过 undefined/null。 */
export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}
