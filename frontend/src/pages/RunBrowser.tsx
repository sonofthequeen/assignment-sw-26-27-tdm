import { type FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/endpoints";
import { useResource } from "../api/useResource";
import {
  Badge,
  Empty,
  ErrorPanel,
  Loading,
  PageHeader,
  Pagination,
  Resource,
  buttonPrimary,
  buttonSecondary,
  inputClass,
  tableClass,
  tdClass,
  thClass,
} from "../components/ui";
import { ACTIVITY_TYPES, type HistoricalRun } from "../types/api";
import { formatDistance, formatLapTime, humanize, withUnit } from "../utils/format";

export const PAGE_SIZE = 25;

// Every filter the backend's GET /runs accepts that this page exposes.
export const FILTER_KEYS = [
  "season_id",
  "vehicle_id",
  "driver_id",
  "track_location_id",
  "track_layout_id",
  "activity_type",
  "tire_compound_id",
  "has_plan",
  "date_from",
  "date_to",
  "asphalt_temperature_min_c",
  "asphalt_temperature_max_c",
  "ambient_temperature_min_c",
  "ambient_temperature_max_c",
] as const;
type FilterKey = (typeof FILTER_KEYS)[number];
type Filters = Partial<Record<FilterKey, string>>;

const TEMPERATURE = /^-?\d{1,3}(\.\d)?$/; // the backend accepts one decimal place

export function validateFilters(filters: Filters): Partial<Record<FilterKey, string>> {
  const errors: Partial<Record<FilterKey, string>> = {};
  for (const key of FILTER_KEYS.filter((k) => k.includes("temperature"))) {
    const value = filters[key];
    if (value && !TEMPERATURE.test(value)) errors[key] = "Use a number with at most one decimal, e.g. 30 or 30.5.";
  }
  const ranges: [FilterKey, FilterKey, string][] = [
    ["date_from", "date_to", "End date is before start date."],
    ["asphalt_temperature_min_c", "asphalt_temperature_max_c", "Maximum is below minimum."],
    ["ambient_temperature_min_c", "ambient_temperature_max_c", "Maximum is below minimum."],
  ];
  for (const [low, high, message] of ranges) {
    const a = filters[low];
    const b = filters[high];
    if (!a || !b || errors[low] || errors[high]) continue;
    const inverted = low.startsWith("date") ? b < a : Number(b) < Number(a);
    if (inverted) errors[high] = message;
  }
  return errors;
}

function readFilters(params: URLSearchParams): Filters {
  const filters: Filters = {};
  for (const key of FILTER_KEYS) {
    const value = params.get(key);
    if (value) filters[key] = value;
  }
  return filters;
}

function loadReferenceData(signal: AbortSignal) {
  return Promise.all([
    api.seasons(signal),
    api.vehicles(signal),
    api.drivers(signal),
    api.trackLocations(signal),
    api.trackLayouts({}, signal),
    api.tireCompounds(signal),
  ]).then(([seasons, vehicles, drivers, locations, layouts, compounds]) => ({
    seasons: seasons.items,
    vehicles: vehicles.items,
    drivers: drivers.items,
    locations: locations.items,
    layouts: layouts.items,
    compounds: compounds.items,
  }));
}

export function RunBrowser() {
  const [params, setParams] = useSearchParams();
  const applied = readFilters(params);
  const offset = Math.max(Number(params.get("offset") ?? 0) || 0, 0);
  const [draft, setDraft] = useState<Filters>(applied);
  const [errors, setErrors] = useState<Partial<Record<FilterKey, string>>>({});

  const reference = useResource(loadReferenceData, "reference");
  const query = { ...applied, limit: PAGE_SIZE, offset };
  const runs = useResource((signal) => api.searchRuns(query, signal), JSON.stringify(query));

  function apply(event: FormEvent) {
    event.preventDefault();
    const found = validateFilters(draft);
    setErrors(found);
    if (Object.keys(found).length) return;
    const next = new URLSearchParams();
    for (const [key, value] of Object.entries(draft)) if (value) next.set(key, value);
    setParams(next); // a new filter set always starts at the first page
  }

  function clear() {
    setDraft({});
    setErrors({});
    setParams(new URLSearchParams());
  }

  function goTo(nextOffset: number) {
    const next = new URLSearchParams(params);
    if (nextOffset) next.set("offset", String(nextOffset));
    else next.delete("offset");
    setParams(next);
  }

  const activeCount = Object.keys(applied).length;
  const set = (key: FilterKey) => (value: string) => setDraft((d) => ({ ...d, [key]: value }));

  return (
    <>
      <PageHeader
        title="Run history"
        subtitle="Every filter is combined with AND and evaluated by the backend over the full history."
      />
      <details open className="mb-6 rounded-lg border border-slate-200 bg-white shadow-sm">
        <summary className="cursor-pointer px-4 py-3 text-sm font-semibold">
          Filters {activeCount > 0 && <Badge tone="info">{activeCount} active</Badge>}
        </summary>
        <form onSubmit={apply} noValidate className="border-t border-slate-200 p-4" aria-label="Run filters">
          {reference.status === "loading" && <Loading label="Loading filter options…" />}
          {reference.status === "error" && <ErrorPanel error={reference.error} onRetry={reference.reload} />}
          {reference.status === "success" && (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Select label="Season" value={draft.season_id} onChange={set("season_id")}
                  options={reference.data.seasons.map((s) => [String(s.id), s.name])} />
                <Select label="Vehicle" value={draft.vehicle_id} onChange={set("vehicle_id")}
                  options={reference.data.vehicles.map((v) => [String(v.id), `${v.code} · ${v.name}`])} />
                <Select label="Driver" value={draft.driver_id} onChange={set("driver_id")}
                  options={reference.data.drivers.map((d) => [String(d.id), `${d.code} · ${d.full_name}`])} />
                <Select label="Track layout" value={draft.track_layout_id} onChange={set("track_layout_id")}
                  options={reference.data.layouts.map((l) => [String(l.id), `${l.name} (${humanize(l.activity_type)})`])} />
                <Select label="Activity type" value={draft.activity_type} onChange={set("activity_type")}
                  options={ACTIVITY_TYPES.map((a) => [a, humanize(a)])} />
                <Select label="Tyre compound" value={draft.tire_compound_id} onChange={set("tire_compound_id")}
                  options={reference.data.compounds.map((c) => [String(c.id), `${c.manufacturer} ${c.name}`])} />
                <Select label="Planned or unexpected" value={draft.has_plan} onChange={set("has_plan")}
                  options={[["true", "Planned runs only"], ["false", "Unexpected runs only"]]} />
                <div className="grid grid-cols-2 gap-2">
                  <Field label="From date" type="date" value={draft.date_from} onChange={set("date_from")} error={errors.date_from} />
                  <Field label="To date" type="date" value={draft.date_to} onChange={set("date_to")} error={errors.date_to} />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Asphalt min °C" value={draft.asphalt_temperature_min_c} onChange={set("asphalt_temperature_min_c")} error={errors.asphalt_temperature_min_c} inputMode="decimal" />
                  <Field label="Asphalt max °C" value={draft.asphalt_temperature_max_c} onChange={set("asphalt_temperature_max_c")} error={errors.asphalt_temperature_max_c} inputMode="decimal" />
                </div>
              </div>
              <details className="mt-3">
                <summary className="cursor-pointer text-sm text-slate-700">Advanced filters</summary>
                <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Select label="Track location" value={draft.track_location_id} onChange={set("track_location_id")}
                    options={reference.data.locations.map((l) => [String(l.id), l.name])} />
                  <Field label="Ambient min °C" value={draft.ambient_temperature_min_c} onChange={set("ambient_temperature_min_c")} error={errors.ambient_temperature_min_c} inputMode="decimal" />
                  <Field label="Ambient max °C" value={draft.ambient_temperature_max_c} onChange={set("ambient_temperature_max_c")} error={errors.ambient_temperature_max_c} inputMode="decimal" />
                </div>
              </details>
              <div className="mt-4 flex gap-2">
                <button type="submit" className={buttonPrimary}>Apply filters</button>
                <button type="button" className={buttonSecondary} onClick={clear}>Clear</button>
              </div>
            </>
          )}
        </form>
      </details>

      <Resource state={runs} label="Loading runs…">
        {(page) =>
          page.items.length === 0 ? (
            <Empty>No runs match these filters.</Empty>
          ) : (
            <>
              <RunTable runs={page.items} />
              <Pagination offset={page.offset} limit={page.limit} total={page.total} onChange={goTo} />
            </>
          )
        }
      </Resource>
    </>
  );
}

function RunTable({ runs }: { runs: HistoricalRun[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
      <table className={tableClass}>
        <caption className="sr-only">Historical runs, newest test first</caption>
        <thead className="bg-slate-50">
          <tr>
            {["Test date", "Run", "Season · Vehicle", "Driver", "Track", "Plan", "Conditions", "Laps (done/recorded)", "Fastest eligible", "Distance"].map((h) => (
              <th key={h} scope="col" className={thClass}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {runs.map((run) => (
            <tr key={run.id} className="hover:bg-slate-50">
              <td className={tdClass}>
                <Link to={`/tests/${run.test.id}`} className="text-accent-700 underline-offset-2 hover:underline">{run.test.test_date}</Link>
              </td>
              <td className={tdClass}>
                <Link to={`/runs/${run.id}`} className="font-medium text-accent-700 underline-offset-2 hover:underline">Run {run.run_number}</Link>
              </td>
              <td className={tdClass}>{run.season.name}<br /><span className="text-slate-500">{run.vehicle.code}</span></td>
              <td className={tdClass}>{run.driver.code}</td>
              <td className={tdClass}>
                {run.track_location.name}<br />
                <span className="text-slate-500">{run.track_layout.name} · {humanize(run.track_layout.activity_type)}</span>
              </td>
              <td className={tdClass}>{run.unexpected ? <Badge tone="warn">Unexpected</Badge> : <Badge tone="info">Planned</Badge>}</td>
              <td className={tdClass}>
                {run.conditions ? (
                  <>asphalt {withUnit(run.conditions.asphalt_temperature_c, "°C")}<br />
                    <span className="text-slate-500">ambient {withUnit(run.conditions.ambient_temperature_c, "°C")}</span></>
                ) : (
                  <span className="text-slate-500">not recorded</span>
                )}
              </td>
              <td className={`${tdClass} font-mono`}>{run.physically_completed_lap_count}/{run.recorded_lap_count}</td>
              <td className={`${tdClass} font-mono`} title={run.fastest_lap ? `${run.fastest_lap.effective_time_ms} ms` : undefined}>
                {run.fastest_lap ? formatLapTime(run.fastest_lap.effective_time_ms) : "—"}
              </td>
              <td className={`${tdClass} whitespace-nowrap font-mono`}>{formatDistance(run.distance_m)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Select({ label, value, onChange, options }: { label: string; value?: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <label className="block text-sm font-medium text-slate-700">
      {label}
      <select className={inputClass} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">Any</option>
        {options.map(([v, text]) => (
          <option key={v} value={v}>{text}</option>
        ))}
      </select>
    </label>
  );
}

function Field({ label, value, onChange, error, type = "text", inputMode }: {
  label: string; value?: string; onChange: (v: string) => void; error?: string; type?: string; inputMode?: "decimal";
}) {
  const id = `filter-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <div className="text-sm">
      <label htmlFor={id} className="block font-medium text-slate-700">{label}</label>
      <input id={id} type={type} inputMode={inputMode} className={inputClass} value={value ?? ""}
        onChange={(e) => onChange(e.target.value)} aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined} />
      {error && <p id={`${id}-error`} className="mt-1 text-xs text-red-700">{error}</p>}
    </div>
  );
}
