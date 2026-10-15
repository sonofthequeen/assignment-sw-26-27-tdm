import type { ErrorDetail, ErrorResponse } from "../types/api";

// Relative by default: in development the Vite proxy forwards /api to the backend.
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

/** The backend answered with its standard error shape (or another non-2xx status). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: ErrorDetail[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Field-level issues keyed by the last segment of the field path. */
  fieldErrors(): Record<string, string> {
    const result: Record<string, string> = {};
    for (const detail of this.details) {
      if (detail.field) result[detail.field.split(".").at(-1) ?? detail.field] = detail.issue;
    }
    return result;
  }
}

/** The request never produced an HTTP response (backend down, offline, proxy failure). */
export class NetworkError extends Error {
  constructor(message = "The backend could not be reached.") {
    super(message);
    this.name = "NetworkError";
  }
}

export type QueryValue = string | number | boolean | null | undefined;

/** Builds `?a=1&b=x`, omitting unset values (undefined, null, empty string). */
export function buildQuery(params: Record<string, QueryValue> = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.append(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return typeof error === "object" && error !== null && "code" in error && "message" in error;
}

interface RequestOptions {
  method?: "GET" | "POST";
  query?: Record<string, QueryValue>;
  body?: unknown;
  signal?: AbortSignal;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", query, body, signal } = options;
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}${buildQuery(query)}`, {
      method,
      signal,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new NetworkError();
  }

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    if (isErrorResponse(payload)) {
      const { code, message, details } = payload.error;
      throw new ApiError(response.status, code, message, Array.isArray(details) ? details : []);
    }
    // e.g. the proxy returning HTML when the backend is down
    throw new ApiError(response.status, "http_error", `Unexpected response (HTTP ${response.status}).`);
  }
  return payload as T;
}
