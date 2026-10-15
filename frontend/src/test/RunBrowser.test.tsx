import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { validateFilters } from "../pages/RunBrowser";
import { historicalRun, referenceRoutes } from "./fixtures";
import { type MockApi, mockApi, page, renderAt } from "./mockApi";

const runsCalls = (api: MockApi) => api.calls.filter((u) => u.pathname === "/api/v1/runs");

describe("historical run browser", () => {
  it("shows a loading state, then the backend's results with fastest lap and distance", async () => {
    mockApi({ ...referenceRoutes, "/runs": page([historicalRun()], { limit: 25 }) });
    renderAt("/runs");
    expect(screen.getByText("Loading runs…")).toBeInTheDocument();
    const row = (await screen.findByRole("link", { name: "Run 1" })).closest("tr")!;
    expect(within(row).getByText("1:02.450")).toBeInTheDocument();
    expect(within(row).getByText("8 050.000 m") /* rendered with U+202F; the matcher sees normalised whitespace */).toBeInTheDocument();
    expect(within(row).getByText("Planned")).toBeInTheDocument();
    expect(within(row).getByText("7/7")).toBeInTheDocument();
  });

  it("sends all active filters in one request and resets to the first page", async () => {
    const api = mockApi({ ...referenceRoutes, "/runs": page([historicalRun()], { limit: 25, total: 60 }) });
    renderAt("/runs?offset=25");
    await screen.findByRole("link", { name: "Run 1" });
    expect(runsCalls(api).at(-1)?.searchParams.get("offset")).toBe("25");

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Season"), "1");
    await user.selectOptions(screen.getByLabelText("Driver"), "3");
    await user.selectOptions(screen.getByLabelText("Tyre compound"), "6");
    await user.type(screen.getByLabelText("Asphalt min °C"), "30");
    await user.type(screen.getByLabelText("Asphalt max °C"), "40");
    await user.selectOptions(screen.getByLabelText("Planned or unexpected"), "false");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() => expect(runsCalls(api).at(-1)?.searchParams.get("season_id")).toBe("1"));
    expect(Object.fromEntries(runsCalls(api).at(-1)!.searchParams)).toEqual({
      season_id: "1",
      driver_id: "3",
      tire_compound_id: "6",
      asphalt_temperature_min_c: "30",
      asphalt_temperature_max_c: "40",
      has_plan: "false",
      limit: "25",
      offset: "0",
    });
    expect(screen.getByText("6 active")).toBeInTheDocument();
  });

  it("uses backend pagination metadata for next/previous", async () => {
    const api = mockApi({
      ...referenceRoutes,
      "/runs": (url) => ({ body: page([historicalRun()], { limit: 25, total: 60, offset: Number(url.searchParams.get("offset")) }) }),
    });
    renderAt("/runs");
    expect(await screen.findByText("1–25 of 60")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("26–50 of 60")).toBeInTheDocument();
    expect(runsCalls(api).at(-1)?.searchParams.get("offset")).toBe("25");
  });

  it("shows an empty state", async () => {
    mockApi({ ...referenceRoutes, "/runs": page([], { limit: 25 }) });
    renderAt("/runs");
    expect(await screen.findByText("No runs match these filters.")).toBeInTheDocument();
  });

  it("displays a backend validation error with its details", async () => {
    mockApi({
      ...referenceRoutes,
      "/runs": () => ({
        status: 422,
        body: {
          error: {
            code: "invalid_date_range",
            message: "date_to must not be lower than date_from.",
            details: [{ field: "date_to", issue: "Must be after date_from." }],
          },
        },
      }),
    });
    renderAt("/runs?date_from=2026-01-01&date_to=2025-01-01");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("invalid_date_range");
    expect(alert).toHaveTextContent("Must be after date_from.");
  });

  it("validates inverted ranges and precision before sending", async () => {
    expect(validateFilters({ date_from: "2026-05-01", date_to: "2026-01-01" })).toEqual({ date_to: "End date is before start date." });
    expect(validateFilters({ asphalt_temperature_min_c: "40", asphalt_temperature_max_c: "30" })).toEqual({
      asphalt_temperature_max_c: "Maximum is below minimum.",
    });
    expect(Object.keys(validateFilters({ ambient_temperature_min_c: "21.25" }))).toEqual(["ambient_temperature_min_c"]);

    const api = mockApi({ ...referenceRoutes, "/runs": page([], { limit: 25 }) });
    renderAt("/runs");
    await screen.findByText("No runs match these filters.");
    await userEvent.type(screen.getByLabelText("Asphalt min °C"), "40");
    await userEvent.type(screen.getByLabelText("Asphalt max °C"), "30");
    const before = runsCalls(api).length;
    await userEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(screen.getByText("Maximum is below minimum.")).toBeInTheDocument();
    expect(screen.getByLabelText("Asphalt max °C")).toHaveAttribute("aria-invalid", "true");
    expect(runsCalls(api).length).toBe(before); // nothing was sent
  });
});
