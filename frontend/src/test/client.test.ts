import { describe, expect, it, vi } from "vitest";
import { ApiError, NetworkError, buildQuery, request } from "../api/client";
import { mockApi } from "./mockApi";

describe("buildQuery", () => {
  it("omits unset values and encodes the rest", () => {
    expect(buildQuery({ season_id: 1, driver_id: undefined, date_from: "", has_plan: false, note: null, q: "a b&c" })).toBe(
      "?season_id=1&has_plan=false&q=a+b%26c",
    );
    expect(buildQuery({})).toBe("");
  });
});

describe("request", () => {
  it("returns parsed JSON on success, using the relative /api/v1 base", async () => {
    const api = mockApi({ "/seasons": { items: [], total: 0 } });
    await expect(request("/seasons", { query: { limit: 5 } })).resolves.toEqual({ items: [], total: 0 });
    expect(api.calls[0]?.pathname).toBe("/api/v1/seasons");
    expect(api.calls[0]?.search).toBe("?limit=5");
  });

  it("turns the standard error shape into an ApiError with field details", async () => {
    mockApi({
      "/tests": () => ({
        status: 422,
        body: {
          error: {
            code: "referenced_resource_not_found",
            message: "Season 9 does not exist.",
            details: [{ field: "planned_runs.0.expected_driver_id", issue: "missing" }],
          },
        },
      }),
    });
    const error = await request("/tests", { method: "POST", body: {} }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect([apiError.status, apiError.code, apiError.message]).toEqual([422, "referenced_resource_not_found", "Season 9 does not exist."]);
    expect(apiError.fieldErrors()).toEqual({ expected_driver_id: "missing" });
  });

  it("reports a non-JSON error response without inventing details", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>Bad gateway</html>", { status: 502 })));
    const error = (await request("/runs").catch((e: unknown) => e)) as ApiError;
    expect([error.status, error.code, error.details]).toEqual([502, "http_error", []]);
  });

  it("distinguishes network failures from backend errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }));
    await expect(request("/runs")).rejects.toBeInstanceOf(NetworkError);
  });

  it("sends JSON bodies for POST", async () => {
    const api = mockApi({ "/tests": () => ({ status: 201, body: { id: 1 } }) });
    await request("/tests", { method: "POST", body: { season_id: 1 } });
    expect(api.requests[0]?.init?.method).toBe("POST");
    expect(api.requests[0]?.init?.body).toBe('{"season_id":1}');
  });
});
