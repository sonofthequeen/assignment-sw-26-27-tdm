import type { HistoricalRun, Lap, TestDetail, TestPlanVsActual } from "../types/api";

export const season = { id: 1, name: "DEMO 2025/26", starts_on: null, ends_on: null };
export const vehicle = { id: 2, code: "DEMO-E25", name: "Demo EV" };
export const driver = { id: 3, code: "DEMO-ADA", full_name: "Ada Demo" };
export const location = { id: 4, name: "Demo Circuit" };
export const layout = {
  id: 5,
  name: "Autocross loop",
  activity_type: "AUTOCROSS" as const,
  verified_length_m: "1150.000",
  track_location_id: 4,
  length_verified_on: "2025-09-15",
  length_verification_note: null,
};
export const compound = { id: 6, manufacturer: "DemoTyre", name: "SOFT-D", notes: null };

const one = <T,>(item: T) => ({ items: [item], limit: 100, offset: 0, total: 1, order_by: [] });

export const referenceRoutes = {
  "/seasons": one(season),
  "/vehicles": one(vehicle),
  "/drivers": one(driver),
  "/track-locations": one(location),
  "/track-layouts": one(layout),
  "/tire-compounds": one(compound),
};

export function historicalRun(overrides: Partial<HistoricalRun> = {}): HistoricalRun {
  return {
    id: 11,
    run_number: 1,
    test: { id: 21, test_date: "2025-10-12", status: "COMPLETED", title: null },
    season,
    vehicle,
    driver,
    track_location: location,
    track_layout: layout,
    planned_run_id: 31,
    unexpected: false,
    setup_snapshot_id: 41,
    started_at: null,
    conditions: { ambient_temperature_c: "19.5", asphalt_temperature_c: "34.5", conditions_source: "MEASURED", weather: "CLEAR", track_state: "DRY" },
    recorded_lap_count: 7,
    physically_completed_lap_count: 7,
    fastest_lap: { lap_id: 51, lap_number: 4, raw_time_ms: 62450, penalty_duration_ms: 0, effective_time_ms: 62450 },
    distance_m: "8050.000",
    ...overrides,
  };
}

export function lap(n: number, overrides: Partial<Lap> = {}): Lap {
  return {
    id: 100 + n,
    run_id: 11,
    lap_number: n,
    lap_classification: "FLYING",
    raw_time_ms: 64000,
    penalty_duration_ms: 0,
    effective_time_ms: 64000,
    timing_valid: true,
    physically_completed: true,
    invalidation_reason: null,
    fastest_lap_eligible: true,
    counts_toward_mileage: true,
    ...overrides,
  };
}

export const testDetail: TestDetail = {
  id: 21,
  season_id: 1,
  vehicle_id: 2,
  track_location_id: 4,
  test_date: "2025-10-12",
  title: "Autocross and skidpad",
  status: "COMPLETED",
  season,
  vehicle,
  track_location: location,
  problems_encountered: "Rain shower",
  engineering_conclusions: "Toe-in helps",
  planned_runs: [],
};

export const planVsActual: TestPlanVsActual = {
  test_id: 21,
  counts: { planned_runs: 3, executed: 1, not_executed: 0, cancelled: 1, replaced: 1, with_repeated_attempts: 1, actual_runs: 3, unexpected_runs: 1 },
  planned_runs: [
    {
      planned_run_id: 31, sequence_number: 1, status: "COMPLETED", category: "EXECUTED", cancellation_reason: null,
      replacement_reason: null, replaced_by_planned_run_id: null, attempt_count: 2, repeated: true,
      attempts: [
        { run_id: 11, run_number: 1, deviation_reason: "Aborted: brake warning", recorded_lap_count: 3, physically_completed_lap_count: 2, fastest_effective_time_ms: null, differing_aspects: ["lap_count"] },
        { run_id: 12, run_number: 3, deviation_reason: "Retry", recorded_lap_count: 6, physically_completed_lap_count: 6, fastest_effective_time_ms: 61870, differing_aspects: [] },
      ],
    },
    {
      planned_run_id: 32, sequence_number: 2, status: "CANCELLED", category: "CANCELLED", cancellation_reason: "Rain shower",
      replacement_reason: null, replaced_by_planned_run_id: null, attempt_count: 0, repeated: false, attempts: [],
    },
    {
      planned_run_id: 33, sequence_number: 3, status: "REPLACED", category: "REPLACED", cancellation_reason: null,
      replacement_reason: "Test toe change", replaced_by_planned_run_id: 31, attempt_count: 0, repeated: false, attempts: [],
    },
  ],
  unexpected_runs: [
    { run_id: 13, run_number: 2, deviation_reason: "Extra skidpad", recorded_lap_count: 4, physically_completed_lap_count: 4, fastest_effective_time_ms: 5390, differing_aspects: [] },
  ],
};
