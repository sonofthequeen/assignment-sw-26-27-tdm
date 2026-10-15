// Types for the backend responses this frontend consumes, copied from the
// FastAPI OpenAPI schema (/openapi.json). Decimal quantities arrive as strings
// and are displayed as-is: they are never converted to binary floats.

export type ActivityType = "SKIDPAD" | "AUTOCROSS" | "ENDURANCE" | "ACCELERATION" | "GENERIC_TESTING";
export type TestStatus = "PLANNED" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED";
export type PlannedRunStatus = "PLANNED" | "COMPLETED" | "MODIFIED" | "CANCELLED" | "REPLACED";
export type LapClassification = "FLYING" | "IN_LAP" | "OUT_LAP" | "ABORTED";
export type Corner = "FL" | "FR" | "RL" | "RR";
export type MeasurementPhase = "PRE_RUN" | "POST_RUN";
export type ConditionsSource = "MEASURED" | "ESTIMATED";
export type Weather = "CLEAR" | "CLOUDY" | "OVERCAST" | "DRIZZLE" | "RAIN";
export type TrackState = "DRY" | "DAMP" | "WET";
export type ComparisonStatus =
  | "MATCH"
  | "DIFFERENT"
  | "NO_PLAN"
  | "NOT_PLANNED"
  | "ACTUAL_NOT_RECORDED"
  | "NOT_YET_SUPPORTED"
  | "TARGET_MET"
  | "TARGET_MISSED";
export type Decimal = string;

export const ACTIVITY_TYPES: ActivityType[] = ["SKIDPAD", "AUTOCROSS", "ENDURANCE", "ACCELERATION", "GENERIC_TESTING"];
export const TEST_STATUSES: TestStatus[] = ["PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"];
export const CORNERS: Corner[] = ["FL", "FR", "RL", "RR"];

export interface Page<T> {
  items: T[];
  limit: number;
  offset: number;
  total: number;
  order_by: string[];
}

export interface ErrorDetail {
  field: string | null;
  issue: string;
}

export interface ErrorResponse {
  error: { code: string; message: string; details: ErrorDetail[] };
}

// --- Reference data ----------------------------------------------------------------

export interface SeasonRef { id: number; name: string }
export interface VehicleRef { id: number; code: string; name: string }
export interface DriverRef { id: number; code: string; full_name: string }
export interface TrackLocationRef { id: number; name: string }
export interface TrackLayoutRef { id: number; name: string; activity_type: ActivityType; verified_length_m: Decimal }
export interface Season extends SeasonRef { starts_on: string | null; ends_on: string | null }
export interface TrackLayout extends TrackLayoutRef {
  track_location_id: number;
  length_verified_on: string;
  length_verification_note: string | null;
}
export interface TireCompound { id: number; manufacturer: string; name: string; notes: string | null }
export interface TireSet { id: number; set_code: string; compound_id: number; introduced_on: string | null; notes: string | null }

// --- Tests and plans ---------------------------------------------------------------

export interface TestSummary {
  id: number;
  season_id: number;
  vehicle_id: number;
  track_location_id: number;
  test_date: string;
  title: string | null;
  status: TestStatus;
}

export interface PlannedRun {
  id: number;
  test_id: number;
  sequence_number: number;
  status: PlannedRunStatus;
  expected_driver_id: number | null;
  expected_track_layout_id: number | null;
  expected_setup_snapshot_id: number | null;
  expected_lap_count: number | null;
  target_lap_time_ms: number | null;
  expected_energy_limit_kwh: Decimal | null;
  expected_control_map: string | null;
  cancellation_reason: string | null;
  replacement_reason: string | null;
  replaced_by_planned_run_id: number | null;
  notes: string | null;
}

export interface TestDetail extends TestSummary {
  season: SeasonRef;
  vehicle: VehicleRef;
  track_location: TrackLocationRef;
  problems_encountered: string | null;
  engineering_conclusions: string | null;
  planned_runs: PlannedRun[];
}

export interface PlannedRunCreate {
  sequence_number: number;
  expected_driver_id?: number | null;
  expected_track_layout_id?: number | null;
  expected_lap_count?: number | null;
  target_lap_time_ms?: number | null;
}

export interface TestCreate {
  season_id: number;
  vehicle_id: number;
  track_location_id: number;
  test_date: string;
  title?: string | null;
  status?: TestStatus;
  problems_encountered?: string | null;
  engineering_conclusions?: string | null;
  planned_runs?: PlannedRunCreate[];
}

export interface AttemptSummary {
  run_id: number;
  run_number: number;
  deviation_reason: string | null;
  recorded_lap_count: number;
  physically_completed_lap_count: number;
  fastest_effective_time_ms: number | null;
  differing_aspects: string[];
}

export interface PlanOutcome {
  planned_run_id: number;
  sequence_number: number;
  status: PlannedRunStatus;
  category: "EXECUTED" | "NOT_EXECUTED" | "CANCELLED" | "REPLACED";
  cancellation_reason: string | null;
  replacement_reason: string | null;
  replaced_by_planned_run_id: number | null;
  attempt_count: number;
  repeated: boolean;
  attempts: AttemptSummary[];
}

export interface TestPlanVsActual {
  test_id: number;
  counts: {
    planned_runs: number;
    executed: number;
    not_executed: number;
    cancelled: number;
    replaced: number;
    with_repeated_attempts: number;
    actual_runs: number;
    unexpected_runs: number;
  };
  planned_runs: PlanOutcome[];
  unexpected_runs: AttemptSummary[];
}

// --- Runs ------------------------------------------------------------------------

export interface ConditionsSummary {
  ambient_temperature_c: Decimal | null;
  asphalt_temperature_c: Decimal | null;
  conditions_source: ConditionsSource | null;
  weather: Weather | null;
  track_state: TrackState | null;
}

export interface RunCondition extends ConditionsSummary {
  run_id: number;
  notes: string | null;
}

export interface FastestLapSummary {
  lap_id: number;
  lap_number: number;
  raw_time_ms: number;
  penalty_duration_ms: number;
  effective_time_ms: number;
}

export interface HistoricalRun {
  id: number;
  run_number: number;
  test: { id: number; test_date: string; status: TestStatus; title: string | null };
  season: SeasonRef;
  vehicle: VehicleRef;
  driver: DriverRef;
  track_location: TrackLocationRef;
  track_layout: TrackLayoutRef;
  planned_run_id: number | null;
  unexpected: boolean;
  setup_snapshot_id: number | null;
  started_at: string | null;
  conditions: ConditionsSummary | null;
  recorded_lap_count: number;
  physically_completed_lap_count: number;
  fastest_lap: FastestLapSummary | null;
  distance_m: Decimal;
}

export interface RunDetail {
  id: number;
  test_id: number;
  planned_run_id: number | null;
  run_number: number;
  driver_id: number;
  track_layout_id: number;
  setup_snapshot_id: number | null;
  started_at: string | null;
  ended_at: string | null;
  driver: DriverRef;
  track_layout: TrackLayoutRef;
  deviation_reason: string | null;
  notes: string | null;
}

export interface Lap {
  id: number;
  run_id: number;
  lap_number: number;
  lap_classification: LapClassification;
  raw_time_ms: number | null;
  penalty_duration_ms: number;
  effective_time_ms: number | null;
  timing_valid: boolean;
  physically_completed: boolean;
  invalidation_reason: string | null;
  fastest_lap_eligible: boolean;
  counts_toward_mileage: boolean;
}

export interface FastestLapResult {
  run_id: number;
  recorded_lap_count: number;
  eligible_lap_count: number;
  lap: Lap | null;
  policy: string;
}

export interface MileageResult {
  scope: "RUN" | "TEST" | "SEASON" | "VEHICLE" | "DRIVER";
  resource_id: number;
  counted_lap_count: number;
  contributing_run_count: number;
  distance_m: Decimal;
  distance_km: Decimal;
  policy: string;
}

export interface PlanComparisonItem {
  aspect: string;
  expected: string | number | null;
  actual: string | number | null;
  status: ComparisonStatus;
  note: string | null;
}

export interface RunPlanComparison {
  run_id: number;
  test_id: number;
  planned_run_id: number | null;
  planned_run_status: PlannedRunStatus | null;
  unexpected: boolean;
  deviation_reason: string | null;
  recorded_lap_count: number;
  physically_completed_lap_count: number;
  fastest_eligible_lap_id: number | null;
  items: PlanComparisonItem[];
}

export interface RankedLap {
  rank: number;
  lap_id: number;
  lap_number: number;
  raw_time_ms: number;
  penalty_duration_ms: number;
  effective_time_ms: number;
  run_id: number;
  run_number: number;
  test: { id: number; test_date: string; status: TestStatus; title: string | null };
  driver: DriverRef;
  track_layout: TrackLayoutRef;
}

// --- Setup ---------------------------------------------------------------------------

export interface SetupCorner {
  corner: Corner;
  static_camber_deg: Decimal | null;
  static_toe_deg: Decimal | null;
  spring_rate_n_per_mm: Decimal | null;
}

export interface SetupSnapshot {
  id: number;
  vehicle_id: number;
  name: string | null;
  based_on_snapshot_id: number | null;
  change_reason: string | null;
  created_at: string;
  vehicle: VehicleRef;
  based_on: { id: number; name: string | null; created_at: string } | null;
  power_limit_kw: Decimal | null;
  rpm_limit_rpm: number | null;
  torque_vectoring_mode: string | null;
  control_map: string | null;
  corners: SetupCorner[];
  is_derived: boolean;
  missing_corners: Corner[];
}

export type SetupValue = string | number | null;

export interface SetupDiff {
  setup_snapshot_id: number;
  against_snapshot_id: number | null;
  baseline: "BASED_ON" | "EXPLICIT" | "NONE";
  vehicle_changes: { field: string; previous: SetupValue; current: SetupValue }[];
  corner_changes: { corner: Corner; field: string; previous: SetupValue; current: SetupValue }[];
  corners_added: Corner[];
  corners_removed: Corner[];
  has_changes: boolean;
}

// --- Tyres, measurements, objectives, files -------------------------------------------

export interface Tire {
  id: number;
  serial_number: string;
  compound_id: number;
  tire_set_id: number | null;
  notes: string | null;
  compound: TireCompound;
}

export interface TireAssignment {
  run_id: number;
  corner: Corner;
  tire_id: number;
  notes: string | null;
  tire: Tire;
}

export interface TireMeasurement {
  id: number;
  run_id: number;
  corner: Corner;
  phase: MeasurementPhase;
  tire_id: number;
  pressure_kpa: Decimal | null;
  temperature_inner_c: Decimal | null;
  temperature_center_c: Decimal | null;
  temperature_outer_c: Decimal | null;
  notes: string | null;
}

export interface AlignmentMeasurement {
  id: number;
  run_id: number;
  corner: Corner;
  phase: MeasurementPhase;
  camber_deg: Decimal | null;
  toe_deg: Decimal | null;
  notes: string | null;
}

export interface Objective {
  id: number;
  season_id: number;
  description: string;
  priority: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  desired_repetitions: number;
  status: "OPEN" | "IN_PROGRESS" | "ACHIEVED" | "DROPPED";
  notes: string | null;
}

export interface IndexedFile {
  id: number;
  test_id: number;
  run_id: number | null;
  file_type: "TELEMETRY" | "DATA_LOG" | "VIDEO" | "SETUP_SHEET" | "OTHER";
  original_filename: string;
  storage_uri: string;
  checksum_sha256: string;
  size_bytes: number;
  // Auxiliary, source-dependent metadata: a flat object of scalars by backend contract.
  metadata: Record<string, string | number | boolean | null>;
  imported_at: string;
}
