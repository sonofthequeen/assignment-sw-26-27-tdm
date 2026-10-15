import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RunDetail } from "../types/api";
import { driver, layout, lap, testDetail } from "./fixtures";
import { mockApi, page, renderAt } from "./mockApi";

const run: RunDetail = {
  id: 11, test_id: 21, planned_run_id: 31, run_number: 1, driver_id: 3, track_layout_id: 5, setup_snapshot_id: 41,
  started_at: null, ended_at: null, driver, track_layout: layout, deviation_reason: null, notes: null,
};

const laps = [
  lap(1, { lap_classification: "OUT_LAP", raw_time_ms: 78400, effective_time_ms: 78400, fastest_lap_eligible: false }),
  lap(2, { raw_time_ms: 62980, penalty_duration_ms: 2000, effective_time_ms: 64980 }),
  lap(3, { raw_time_ms: 62450, effective_time_ms: 62450 }),
  lap(4, { raw_time_ms: 61900, effective_time_ms: 61900, timing_valid: false, invalidation_reason: "Track limits", fastest_lap_eligible: false }),
  lap(5, { raw_time_ms: null, effective_time_ms: null, timing_valid: false, invalidation_reason: "Transponder miss", fastest_lap_eligible: false }),
  lap(6, { lap_classification: "ABORTED", raw_time_ms: null, effective_time_ms: null, timing_valid: false, physically_completed: false, invalidation_reason: "Spin", fastest_lap_eligible: false, counts_toward_mileage: false }),
  lap(7, { lap_classification: "IN_LAP", raw_time_ms: 85100, effective_time_ms: 85100, fastest_lap_eligible: false }),
];

const tire = (corner: string, setId: number | null) => ({
  run_id: 11, corner, tire_id: corner.charCodeAt(0), notes: null,
  tire: { id: corner.charCodeAt(0), serial_number: `SOFT-A-${corner}`, compound_id: 6, tire_set_id: setId, notes: null,
    compound: { id: 6, manufacturer: "DemoTyre", name: "SOFT-D", notes: null } },
});

function routes(overrides: Record<string, unknown> = {}) {
  return {
    "/runs/11": run,
    "/tests/21": testDetail,
    "/runs/11/conditions": { run_id: 11, ambient_temperature_c: "19.5", asphalt_temperature_c: "34.5", conditions_source: "MEASURED", weather: "CLEAR", track_state: "DRY", notes: null },
    "/runs/11/laps": page(laps),
    "/runs/11/fastest-lap": { run_id: 11, recorded_lap_count: 7, eligible_lap_count: 2, lap: laps[2], policy: "" },
    "/runs/11/mileage": { scope: "RUN", resource_id: 11, counted_lap_count: 6, contributing_run_count: 1, distance_m: "6900.000", distance_km: "6.900000", policy: "" },
    "/runs/11/plan-comparison": { run_id: 11, test_id: 21, planned_run_id: 31, planned_run_status: "COMPLETED", unexpected: false, deviation_reason: null, recorded_lap_count: 7, physically_completed_lap_count: 6, fastest_eligible_lap_id: 103,
      items: [{ aspect: "target_lap_time_ms", expected: 63000, actual: 62450, status: "TARGET_MET", note: null }] },
    // Deliberately out of order: the page must show FL, FR, RL, RR.
    "/runs/11/tire-assignments": [tire("RR", 9), tire("FL", 9), tire("RL", null), tire("FR", 9)],
    "/tire-sets": page([{ id: 9, set_code: "SOFT-A", compound_id: 6, introduced_on: null, notes: null }]),
    "/runs/11/tire-measurements": [
      { id: 1, run_id: 11, corner: "FL", phase: "PRE_RUN", tire_id: 70, pressure_kpa: "80.0", temperature_inner_c: "28.0", temperature_center_c: "27.5", temperature_outer_c: "27.0", notes: null },
      { id: 2, run_id: 11, corner: "FL", phase: "POST_RUN", tire_id: 70, pressure_kpa: "92.5", temperature_inner_c: "71.0", temperature_center_c: "66.5", temperature_outer_c: "61.0", notes: null },
    ],
    "/runs/11/alignment-measurements": [{ id: 1, run_id: 11, corner: "FL", phase: "PRE_RUN", camber_deg: "-1.50", toe_deg: null, notes: null }],
    "/runs/11/objectives": [],
    "/tests/21/files": page([]),
    ...overrides,
  };
}

describe("run detail", () => {
  it("renders every lap category, highlights the fastest and keeps untimed laps safe", async () => {
    mockApi(routes());
    renderAt("/runs/11");
    const lapsTable = await screen.findByRole("table", { name: "Laps in order" });
    const row = (n: number) => within(lapsTable).getByTestId(`lap-${n}`);

    expect(within(row(1)).getByText("Out lap")).toBeInTheDocument();
    expect(within(row(7)).getByText("In lap")).toBeInTheDocument();
    expect(within(row(6)).getByText("Aborted")).toBeInTheDocument();
    expect(within(row(6)).getByText("No")).toBeInTheDocument(); // not physically completed
    expect(within(row(3)).getByText("Fastest")).toBeInTheDocument();
    expect(within(row(4)).getByText("Invalid")).toBeInTheDocument();
    expect(within(row(4)).getByText("Track limits")).toBeInTheDocument();
    expect(within(row(5)).getByText("Untimed")).toBeInTheDocument();
    // Penalised lap: raw, penalty and effective time are all shown.
    expect(within(row(2)).getByText("1:02.980")).toBeInTheDocument();
    expect(within(row(2)).getByText("+2.000 s")).toBeInTheDocument();
    expect(within(row(2)).getByText("1:04.980")).toBeInTheDocument();

    expect(await screen.findByText("2 of 7 laps eligible", { exact: false })).toBeInTheDocument();
    expect(await screen.findByText("6 900.000 m")).toBeInTheDocument();
    expect(await screen.findByText("Target met")).toBeInTheDocument();
  });

  it("shows tyres in FL, FR, RL, RR order with set codes and measurements", async () => {
    mockApi(routes());
    renderAt("/runs/11");
    const table = await screen.findByRole("table", { name: "Tyres by corner with pre- and post-run measurements" });
    const corners = within(table).getAllByRole("rowheader").map((cell) => cell.textContent);
    expect(corners).toEqual(["FL", "FR", "RL", "RR"]);
    const fl = within(table).getByTestId("tyre-FL");
    expect(fl).toHaveTextContent("SOFT-A-FL");
    expect(fl).toHaveTextContent("SOFT-A");
    expect(fl).toHaveTextContent("92.5 kPa");
    expect(within(table).getByTestId("tyre-RL")).toHaveTextContent("single tyre");
  });

  it("keeps working sections when one section fails", async () => {
    mockApi(routes({ "/runs/11/tire-assignments": () => ({ status: 500, body: { error: { code: "internal_error", message: "An unexpected error occurred.", details: [] } } }) }));
    renderAt("/runs/11");
    expect(await screen.findByRole("table", { name: "Laps in order" })).toBeInTheDocument();
    expect(await screen.findByText("Request rejected (internal_error)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.getByText("No objectives linked to this run.")).toBeInTheDocument();
  });

  it("treats missing conditions as 'not recorded', not as an error", async () => {
    mockApi(routes({
      "/runs/11/conditions": () => ({ status: 404, body: { error: { code: "run_condition_not_found", message: "Run condition 11 was not found.", details: [] } } }),
    }));
    renderAt("/runs/11");
    expect(await screen.findByText("No conditions recorded for this run.")).toBeInTheDocument();
  });
});
