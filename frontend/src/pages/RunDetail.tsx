import { Link, useParams } from "react-router";
import { ApiError } from "../api/client";
import { api } from "../api/endpoints";
import { useResource } from "../api/useResource";
import {
  Badge,
  Empty,
  ErrorPanel,
  Facts,
  Loading,
  PageHeader,
  Resource,
  Section,
  statusTone,
  tableClass,
  tdClass,
  thClass,
} from "../components/ui";
import { CORNERS, type Lap, type MeasurementPhase, type RunDetail, type TireMeasurement } from "../types/api";
import { formatDistance, formatLapTime, formatPenalty, formatTimestamp, humanize, withUnit } from "../utils/format";

export function RunDetailPage() {
  const runId = Number(useParams().runId);
  const run = useResource((signal) => api.run(runId, signal), `run-${runId}`);
  if (run.status === "loading") return <Loading label="Loading run…" />;
  if (run.status === "error") {
    if (run.error instanceof ApiError && run.error.status === 404) {
      return (
        <div role="alert">
          <h1 className="text-xl font-semibold">Run not found</h1>
          <Link to="/runs" className="text-accent-700 underline">Back to run history</Link>
        </div>
      );
    }
    return <ErrorPanel error={run.error} onRetry={run.reload} />;
  }
  return <RunSections run={run.data} />;
}

/** Each section loads independently (in parallel) and fails independently. */
function RunSections({ run }: { run: RunDetail }) {
  const id = run.id;
  const test = useResource((s) => api.test(run.test_id, s), `test-${run.test_id}`);
  const conditions = useResource(
    (s) => api.runConditions(id, s).catch((error: unknown) => {
      if (error instanceof ApiError && error.code === "run_condition_not_found") return null;
      throw error;
    }),
    `conditions-${id}`,
  );
  const laps = useResource((s) => api.runLaps(id, s), `laps-${id}`);
  const fastest = useResource((s) => api.fastestLap(id, s), `fastest-${id}`);
  const mileage = useResource((s) => api.mileage("runs", id, s), `mileage-${id}`);
  const comparison = useResource((s) => api.planComparison(id, s), `comparison-${id}`);
  const tyres = useResource(
    (s) => Promise.all([api.tireAssignments(id, s), api.tireSets(s), api.tireMeasurements(id, s)]),
    `tyres-${id}`,
  );
  const alignment = useResource((s) => api.alignmentMeasurements(id, s), `alignment-${id}`);
  const objectives = useResource((s) => api.runObjectives(id, s), `run-objectives-${id}`);
  const files = useResource((s) => api.testFiles(run.test_id, { run_id: id, limit: 100 }, s), `files-${id}`);

  return (
    <>
      <PageHeader
        title={`Run ${run.run_number}`}
        subtitle={
          test.status === "success" ? (
            <>
              <Link to={`/tests/${run.test_id}`} className="text-accent-700 underline">
                {test.data.test_date} · {test.data.track_location.name}
              </Link>{" "}
              · {test.data.vehicle.code} · {test.data.season.name}
            </>
          ) : (
            <Link to={`/tests/${run.test_id}`} className="text-accent-700 underline">Test {run.test_id}</Link>
          )
        }
        actions={run.planned_run_id ? <Badge tone="info">Planned run</Badge> : <Badge tone="warn">Unexpected run</Badge>}
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Run context">
          <Facts
            items={[
              ["Driver", `${run.driver.code} · ${run.driver.full_name}`],
              ["Track layout", `${run.track_layout.name} (${humanize(run.track_layout.activity_type)}, ${formatDistance(run.track_layout.verified_length_m)} verified)`],
              ["Setup", run.setup_snapshot_id ? <Link to={`/setups/${run.setup_snapshot_id}`} className="text-accent-700 underline">Snapshot {run.setup_snapshot_id}</Link> : "Not recorded"],
              ["Started", formatTimestamp(run.started_at)],
              ["Deviation reason", run.deviation_reason],
              ["Notes", run.notes],
            ]}
          />
        </Section>
        <Section title="Conditions">
          <Resource state={conditions}>
            {(c) =>
              c === null ? (
                <Empty>No conditions recorded for this run.</Empty>
              ) : (
                <Facts
                  items={[
                    ["Ambient", withUnit(c.ambient_temperature_c, "°C")],
                    ["Asphalt", withUnit(c.asphalt_temperature_c, "°C")],
                    ["Source", c.conditions_source && humanize(c.conditions_source)],
                    ["Weather", c.weather && humanize(c.weather)],
                    ["Track state", c.track_state && humanize(c.track_state)],
                    ["Notes", c.notes],
                  ]}
                />
              )
            }
          </Resource>
        </Section>
        <Section title="Fastest lap and mileage">
          <div className="grid grid-cols-2 gap-4">
            <Resource state={fastest}>
              {(f) => (
                <div>
                  <p className="text-xs uppercase tracking-wide text-slate-500">Fastest eligible lap</p>
                  <p className="font-mono text-2xl">{f.lap ? formatLapTime(f.lap.effective_time_ms) : "—"}</p>
                  <p className="text-xs text-slate-600">
                    {f.lap ? `lap ${f.lap.lap_number} · ` : "no eligible lap · "}
                    {f.eligible_lap_count} of {f.recorded_lap_count} laps eligible
                  </p>
                </div>
              )}
            </Resource>
            <Resource state={mileage}>
              {(m) => (
                <div>
                  <p className="text-xs uppercase tracking-wide text-slate-500">Distance</p>
                  <p className="font-mono text-2xl">{formatDistance(m.distance_m)}</p>
                  <p className="text-xs text-slate-600">{m.counted_lap_count} physically completed laps</p>
                </div>
              )}
            </Resource>
          </div>
        </Section>
        <Section title="Plan comparison">
          <Resource state={comparison}>
            {(cmp) => (
              <ul className="space-y-1 text-sm">
                {cmp.items.map((item) => (
                  <li key={item.aspect} className="flex flex-wrap items-baseline gap-2">
                    <Badge tone={statusTone(item.status)}>{humanize(item.status)}</Badge>
                    <span className="font-medium">{humanize(item.aspect.replace(/_(id|ms|kwh)$/, ""))}</span>
                    <span className="text-slate-600">
                      expected {item.expected ?? "—"} · actual {item.actual ?? "—"}
                    </span>
                    {item.note && <span className="text-xs text-slate-500">{item.note}</span>}
                  </li>
                ))}
              </ul>
            )}
          </Resource>
        </Section>
      </div>

      <div className="mt-4 space-y-4">
        <Section title="Laps" aside="Effective time = raw time + penalty. Only timed, timing-valid, completed flying laps are eligible.">
          <Resource state={laps}>
            {(page) => (
              <>
                <LapTable laps={page.items} fastestId={fastest.status === "success" ? fastest.data.lap?.id : undefined} />
                {page.total > page.items.length && (
                  <p className="mt-2 text-xs text-slate-500">Showing the first {page.items.length} of {page.total} laps.</p>
                )}
              </>
            )}
          </Resource>
        </Section>

        <Section title="Tyres" aside="Observed fitment and measurements for this run">
          <Resource state={tyres}>
            {([assignments, sets, measurements]) => {
              if (assignments.length === 0) return <Empty>No tyre fitment recorded for this run.</Empty>;
              const setCodes = new Map(sets.items.map((s) => [s.id, s.set_code]));
              const byCorner = new Map(assignments.map((a) => [a.corner, a]));
              return (
                <div className="overflow-x-auto">
                  <table className={tableClass}>
                    <caption className="sr-only">Tyres by corner with pre- and post-run measurements</caption>
                    <thead className="bg-slate-50">
                      <tr>
                        {["Corner", "Tyre", "Compound", "Set", "Pre-run", "Post-run"].map((h) => (
                          <th key={h} scope="col" className={thClass}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {CORNERS.map((corner) => {
                        const fitted = byCorner.get(corner);
                        return (
                          <tr key={corner} data-testid={`tyre-${corner}`}>
                            <th scope="row" className={`${tdClass} font-mono font-semibold`}>{corner}</th>
                            <td className={`${tdClass} font-mono`}>{fitted?.tire.serial_number ?? "not recorded"}</td>
                            <td className={tdClass}>{fitted ? `${fitted.tire.compound.manufacturer} ${fitted.tire.compound.name}` : "—"}</td>
                            <td className={tdClass}>{fitted?.tire.tire_set_id ? (setCodes.get(fitted.tire.tire_set_id) ?? `#${fitted.tire.tire_set_id}`) : "single tyre"}</td>
                            <td className={tdClass}><Measurement rows={measurements} corner={corner} phase="PRE_RUN" /></td>
                            <td className={tdClass}><Measurement rows={measurements} corner={corner} phase="POST_RUN" /></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              );
            }}
          </Resource>
        </Section>

        <Section title="Alignment — observed measurement" aside="Measured around this run; the intended setup is on the setup snapshot page.">
          <Resource state={alignment}>
            {(rows) =>
              rows.length === 0 ? (
                <Empty>No alignment measured for this run.</Empty>
              ) : (
                <div className="overflow-x-auto">
                  <table className={tableClass}>
                    <caption className="sr-only">Observed camber and toe</caption>
                    <thead className="bg-slate-50">
                      <tr>{["Phase", "Corner", "Camber", "Toe"].map((h) => <th key={h} scope="col" className={thClass}>{h}</th>)}</tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {rows.map((row) => (
                        <tr key={row.id}>
                          <td className={tdClass}>{humanize(row.phase)}</td>
                          <td className={`${tdClass} font-mono`}>{row.corner}</td>
                          <td className={`${tdClass} font-mono`}>{withUnit(row.camber_deg, "°")}</td>
                          <td className={`${tdClass} font-mono`}>{withUnit(row.toe_deg, "°")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            }
          </Resource>
        </Section>

        <div className="grid gap-4 lg:grid-cols-2">
          <Section title="Objectives">
            <Resource state={objectives}>
              {(items) =>
                items.length === 0 ? <Empty>No objectives linked to this run.</Empty> : (
                  <ul className="space-y-1 text-sm">{items.map((o) => <li key={o.id}>{o.description} <Badge>{humanize(o.priority)}</Badge></li>)}</ul>
                )
              }
            </Resource>
          </Section>
          <Section title="Indexed files" aside="Metadata only; files live in external storage">
            <Resource state={files}>
              {(page) =>
                page.items.length === 0 ? <Empty>No files indexed for this run.</Empty> : (
                  <ul className="space-y-2 text-sm">
                    {page.items.map((f) => (
                      <li key={f.id}>
                        <span className="font-medium">{f.original_filename}</span> <Badge>{humanize(f.file_type)}</Badge>
                        <div className="break-all font-mono text-xs text-slate-500">{f.storage_uri}</div>
                      </li>
                    ))}
                  </ul>
                )
              }
            </Resource>
          </Section>
        </div>
      </div>
    </>
  );
}

function Measurement({ rows, corner, phase }: { rows: TireMeasurement[]; corner: string; phase: MeasurementPhase }) {
  const m = rows.find((row) => row.corner === corner && row.phase === phase);
  if (!m) return <span className="text-slate-500">—</span>;
  return (
    <span className="font-mono text-xs">
      {withUnit(m.pressure_kpa, "kPa")}
      <br />
      I/C/O {m.temperature_inner_c ?? "—"} / {m.temperature_center_c ?? "—"} / {m.temperature_outer_c ?? "—"} °C
    </span>
  );
}

export function LapTable({ laps, fastestId }: { laps: Lap[]; fastestId?: number }) {
  if (laps.length === 0) return <Empty>No laps recorded for this run.</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className={tableClass}>
        <caption className="sr-only">Laps in order</caption>
        <thead className="bg-slate-50">
          <tr>
            {["Lap", "Type", "Raw", "Penalty", "Effective", "Timing", "Completed", "Note"].map((h) => (
              <th key={h} scope="col" className={thClass}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {laps.map((lap) => {
            const fastest = lap.id === fastestId;
            return (
              <tr key={lap.id} data-testid={`lap-${lap.lap_number}`} className={fastest ? "bg-emerald-50" : lap.timing_valid ? "" : "bg-slate-50 text-slate-600"}>
                <td className={`${tdClass} font-mono`}>{lap.lap_number}</td>
                <td className={tdClass}>
                  <span className="flex flex-wrap gap-1">
                    {lap.lap_classification !== "FLYING" && <Badge tone={lap.lap_classification === "ABORTED" ? "bad" : "neutral"}>{humanize(lap.lap_classification)}</Badge>}
                    {lap.lap_classification === "FLYING" && <span>Flying</span>}
                    {fastest && <Badge tone="good">Fastest</Badge>}
                  </span>
                </td>
                <td className={`${tdClass} font-mono`}>{lap.raw_time_ms === null ? <Badge>Untimed</Badge> : formatLapTime(lap.raw_time_ms)}</td>
                <td className={`${tdClass} font-mono`}>{formatPenalty(lap.penalty_duration_ms)}</td>
                <td className={`${tdClass} font-mono`} title={lap.effective_time_ms !== null ? `${lap.effective_time_ms} ms` : undefined}>
                  {formatLapTime(lap.effective_time_ms)}
                </td>
                <td className={tdClass}>{lap.timing_valid ? "Valid" : <Badge tone="bad">Invalid</Badge>}</td>
                <td className={tdClass}>{lap.physically_completed ? "Yes" : <Badge tone="warn">No</Badge>}</td>
                <td className={`${tdClass} text-slate-600`}>{lap.invalidation_reason ?? ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
