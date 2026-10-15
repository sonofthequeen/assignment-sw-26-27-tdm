import type {
  AlignmentMeasurement,
  DriverRef,
  FastestLapResult,
  HistoricalRun,
  IndexedFile,
  Lap,
  MileageResult,
  Objective,
  Page,
  RankedLap,
  RunCondition,
  RunDetail,
  RunPlanComparison,
  Season,
  SetupDiff,
  SetupSnapshot,
  TestCreate,
  TestDetail,
  TestPlanVsActual,
  TestSummary,
  TireAssignment,
  TireCompound,
  TireMeasurement,
  TireSet,
  TrackLayout,
  TrackLocationRef,
  VehicleRef,
} from "../types/api";
import { type QueryValue, request } from "./client";

type Signal = AbortSignal | undefined;
const ALL = { limit: 100 }; // reference lists are small; the backend caps pages at 100

export const api = {
  seasons: (signal?: Signal) => request<Page<Season>>("/seasons", { query: ALL, signal }),
  vehicles: (signal?: Signal) => request<Page<VehicleRef>>("/vehicles", { query: ALL, signal }),
  drivers: (signal?: Signal) => request<Page<DriverRef>>("/drivers", { query: ALL, signal }),
  trackLocations: (signal?: Signal) =>
    request<Page<TrackLocationRef>>("/track-locations", { query: ALL, signal }),
  trackLayouts: (query: Record<string, QueryValue> = {}, signal?: Signal) =>
    request<Page<TrackLayout>>("/track-layouts", { query: { ...ALL, ...query }, signal }),
  tireCompounds: (signal?: Signal) => request<Page<TireCompound>>("/tire-compounds", { query: ALL, signal }),
  tireSets: (signal?: Signal) => request<Page<TireSet>>("/tire-sets", { query: ALL, signal }),

  searchRuns: (query: Record<string, QueryValue>, signal?: Signal) =>
    request<Page<HistoricalRun>>("/runs", { query, signal }),
  tests: (query: Record<string, QueryValue>, signal?: Signal) =>
    request<Page<TestSummary>>("/tests", { query, signal }),
  test: (id: number, signal?: Signal) => request<TestDetail>(`/tests/${id}`, { signal }),
  createTest: (body: TestCreate) => request<TestDetail>("/tests", { method: "POST", body }),
  planVsActual: (testId: number, signal?: Signal) =>
    request<TestPlanVsActual>(`/tests/${testId}/plan-vs-actual`, { signal }),
  testObjectives: (testId: number, signal?: Signal) =>
    request<Objective[]>(`/tests/${testId}/objectives`, { signal }),

  run: (id: number, signal?: Signal) => request<RunDetail>(`/runs/${id}`, { signal }),
  runConditions: (id: number, signal?: Signal) => request<RunCondition>(`/runs/${id}/conditions`, { signal }),
  runLaps: (id: number, signal?: Signal) => request<Page<Lap>>(`/runs/${id}/laps`, { query: ALL, signal }),
  fastestLap: (id: number, signal?: Signal) => request<FastestLapResult>(`/runs/${id}/fastest-lap`, { signal }),
  planComparison: (id: number, signal?: Signal) =>
    request<RunPlanComparison>(`/runs/${id}/plan-comparison`, { signal }),
  tireAssignments: (id: number, signal?: Signal) =>
    request<TireAssignment[]>(`/runs/${id}/tire-assignments`, { signal }),
  tireMeasurements: (id: number, signal?: Signal) =>
    request<TireMeasurement[]>(`/runs/${id}/tire-measurements`, { signal }),
  alignmentMeasurements: (id: number, signal?: Signal) =>
    request<AlignmentMeasurement[]>(`/runs/${id}/alignment-measurements`, { signal }),
  runObjectives: (id: number, signal?: Signal) => request<Objective[]>(`/runs/${id}/objectives`, { signal }),
  testFiles: (testId: number, query: Record<string, QueryValue>, signal?: Signal) =>
    request<Page<IndexedFile>>(`/tests/${testId}/files`, { query, signal }),

  mileage: (scope: "runs" | "tests" | "seasons" | "vehicles" | "drivers", id: number, signal?: Signal) =>
    request<MileageResult>(`/${scope}/${id}/mileage`, { signal }),
  fastestLaps: (query: Record<string, QueryValue>, signal?: Signal) =>
    request<Page<RankedLap>>("/analytics/fastest-laps", { query, signal }),

  setupSnapshot: (id: number, signal?: Signal) => request<SetupSnapshot>(`/setup-snapshots/${id}`, { signal }),
  setupDiff: (id: number, signal?: Signal) => request<SetupDiff>(`/setup-snapshots/${id}/diff`, { signal }),
};
