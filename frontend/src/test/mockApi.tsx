import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import { AppRoutes } from "../App";

type Handler = (url: URL, init?: RequestInit) => { status?: number; body: unknown } | undefined;

export interface MockApi {
  calls: URL[];
  requests: { url: URL; init?: RequestInit }[];
}

/**
 * Replaces fetch. `routes` maps an API path (without /api/v1, e.g. "/runs/5") to a
 * JSON body or a handler; unknown paths answer 404 in the backend's error shape.
 */
export function mockApi(routes: Record<string, Handler | object>): MockApi {
  const record: MockApi = { calls: [], requests: [] };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      record.calls.push(url);
      record.requests.push({ url, init });
      const path = url.pathname.replace(/^\/api\/v1/, "");
      const route = routes[path];
      const result =
        typeof route === "function" ? (route as Handler)(url, init) : route === undefined ? undefined : { body: route };
      if (!result) {
        return json(404, { error: { code: "not_found", message: `No mock for ${path}`, details: [] } });
      }
      return json(result.status ?? 200, result.body);
    }),
  );
  return record;
}

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export function page<T>(items: T[], extra: Partial<{ limit: number; offset: number; total: number }> = {}) {
  return { items, limit: extra.limit ?? 100, offset: extra.offset ?? 0, total: extra.total ?? items.length, order_by: ["id asc"] };
}

export function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}
