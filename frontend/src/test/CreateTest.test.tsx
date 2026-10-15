import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { planVsActual, referenceRoutes, testDetail } from "./fixtures";
import { type MockApi, mockApi, renderAt } from "./mockApi";

const posts = (api: MockApi) => api.requests.filter((r) => r.init?.method === "POST");

async function fillRequired() {
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText("Season *"), "1");
  await user.selectOptions(screen.getByLabelText("Vehicle *"), "2");
  await user.selectOptions(screen.getByLabelText("Track location *"), "4");
  await user.type(screen.getByLabelText("Test date *"), "2026-11-07");
  return user;
}

describe("create test", () => {
  it("validates required fields on the client without sending", async () => {
    const api = mockApi(referenceRoutes);
    renderAt("/tests/new");
    await userEvent.click(await screen.findByRole("button", { name: "Create test" }));
    expect(screen.getByText("Choose a season.")).toBeInTheDocument();
    expect(screen.getByLabelText("Test date *")).toHaveAttribute("aria-invalid", "true");
    expect(posts(api)).toHaveLength(0);
  });

  it("submits a valid test with its first planned run and redirects to it", async () => {
    const api = mockApi({
      ...referenceRoutes,
      "/tests": () => ({ status: 201, body: { ...testDetail, id: 77 } }),
      "/tests/77": { ...testDetail, id: 77 },
      "/tests/77/plan-vs-actual": planVsActual,
      "/tests/77/objectives": [],
    });
    renderAt("/tests/new");
    const user = await fillRequired();
    await user.type(screen.getByLabelText("Problems encountered"), "None");
    await user.click(screen.getByLabelText("Add planned run 1"));
    await user.selectOptions(screen.getByLabelText("Expected layout"), "5");
    await user.type(screen.getByLabelText("Expected laps"), "8");
    await user.click(screen.getByRole("button", { name: "Create test" }));

    expect(await screen.findByRole("heading", { name: "Autocross and skidpad" })).toBeInTheDocument();
    const body = JSON.parse(String(posts(api)[0]?.init?.body));
    expect(body).toEqual({
      season_id: 1,
      vehicle_id: 2,
      track_location_id: 4,
      test_date: "2026-11-07",
      status: "PLANNED",
      title: null,
      problems_encountered: "None",
      engineering_conclusions: null,
      planned_runs: [{ sequence_number: 1, expected_driver_id: null, expected_track_layout_id: 5, expected_lap_count: 8, target_lap_time_ms: null }],
    });
  });

  it("maps backend field errors onto the form", async () => {
    mockApi({
      ...referenceRoutes,
      "/tests": () => ({
        status: 422,
        body: {
          error: {
            code: "track_layout_not_at_test_location",
            message: "Track layout 5 is not at the test's track location.",
            details: [{ field: "planned_runs.0.expected_track_layout_id", issue: "Track layout 5 is not at the test's track location." }],
          },
        },
      }),
    });
    renderAt("/tests/new");
    const user = await fillRequired();
    await user.click(screen.getByLabelText("Add planned run 1"));
    await user.selectOptions(screen.getByLabelText("Expected layout"), "5");
    await user.click(screen.getByRole("button", { name: "Create test" }));

    await waitFor(() => expect(screen.getByLabelText("Expected layout")).toHaveAttribute("aria-invalid", "true"));
    expect(screen.getByRole("alert")).toHaveTextContent("track_layout_not_at_test_location");
    expect(screen.getByRole("button", { name: "Create test" })).toBeEnabled();
  });
});
