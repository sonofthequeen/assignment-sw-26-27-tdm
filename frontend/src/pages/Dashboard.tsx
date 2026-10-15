import { Link } from "react-router";
import { api } from "../api/endpoints";
import { useResource } from "../api/useResource";
import { Badge, Empty, PageHeader, Resource, Section, statusTone } from "../components/ui";
import type { HistoricalRun, TestSummary } from "../types/api";
import { formatDistance, formatLapTime, humanize } from "../utils/format";

/** Overview built from bounded queries; every card states the exact scope it shows. */
export function Dashboard() {
  const tests = useResource((s) => api.tests({ limit: 5 }, s), "dashboard-tests");
  const runs = useResource((s) => api.searchRuns({ limit: 5 }, s), "dashboard-runs");

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Latest test activity. All values are computed by the backend." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Recent tests" aside="5 most recent test days">
          <Resource state={tests}>
            {(page) =>
              page.items.length === 0 ? (
                <Empty>No tests yet. <Link to="/tests/new" className="text-accent-700 underline">Create one</Link>.</Empty>
              ) : (
                <ul className="divide-y divide-slate-100 text-sm">
                  {page.items.map((t) => (
                    <li key={t.id} className="flex items-center justify-between gap-2 py-1.5">
                      <Link to={`/tests/${t.id}`} className="text-accent-700 underline-offset-2 hover:underline">
                        {t.test_date} · {t.title ?? `Test ${t.id}`}
                      </Link>
                      <Badge tone={statusTone(t.status)}>{humanize(t.status)}</Badge>
                    </li>
                  ))}
                </ul>
              )
            }
          </Resource>
        </Section>
        <Section title="Recent runs" aside="5 most recent runs by test date">
          <Resource state={runs}>
            {(page) =>
              page.items.length === 0 ? (
                <Empty>No runs recorded yet.</Empty>
              ) : (
                <ul className="divide-y divide-slate-100 text-sm">
                  {page.items.map((r) => (
                    <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                      <Link to={`/runs/${r.id}`} className="text-accent-700 underline-offset-2 hover:underline">
                        {r.test.test_date} · Run {r.run_number} · {r.driver.code}
                      </Link>
                      <span className="font-mono text-xs text-slate-600">
                        {r.fastest_lap ? formatLapTime(r.fastest_lap.effective_time_ms) : "no eligible lap"} · {formatDistance(r.distance_m)}
                      </span>
                    </li>
                  ))}
                </ul>
              )
            }
          </Resource>
        </Section>
        {tests.status === "success" && tests.data.items[0] && <LatestTestPlan test={tests.data.items[0]} />}
        {runs.status === "success" && runs.data.items[0] && <LayoutAndSeason run={runs.data.items[0]} />}
      </div>
    </>
  );
}

function LatestTestPlan({ test }: { test: TestSummary }) {
  const pva = useResource((s) => api.planVsActual(test.id, s), `dashboard-pva-${test.id}`);
  return (
    <Section title="Plan versus actual" aside={`Most recent test: ${test.test_date}`}>
      <Resource state={pva}>
        {({ counts }) => (
          <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            {([
              ["Planned", counts.planned_runs], ["Executed", counts.executed], ["Not executed", counts.not_executed],
              ["Cancelled", counts.cancelled], ["Replaced", counts.replaced], ["Repeated", counts.with_repeated_attempts],
              ["Actual runs", counts.actual_runs], ["Unexpected", counts.unexpected_runs],
            ] as const).map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-slate-500">{label}</dt>
                <dd className="font-mono text-lg">{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </Resource>
    </Section>
  );
}

function LayoutAndSeason({ run }: { run: HistoricalRun }) {
  const ranking = useResource(
    (s) => api.fastestLaps({ track_layout_id: run.track_layout.id, limit: 3 }, s),
    `dashboard-ranking-${run.track_layout.id}`,
  );
  const mileage = useResource((s) => api.mileage("seasons", run.season.id, s), `dashboard-mileage-${run.season.id}`);
  return (
    <Section title="Records" aside={`Layout ${run.track_layout.name} · season ${run.season.name}`}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500">Fastest eligible laps on {run.track_layout.name} (all history)</h3>
          <Resource state={ranking}>
            {(page) =>
              page.items.length === 0 ? <Empty>No eligible laps.</Empty> : (
                <ol className="mt-1 space-y-1 text-sm">
                  {page.items.map((lap) => (
                    <li key={lap.lap_id}>
                      <span className="font-mono">{formatLapTime(lap.effective_time_ms)}</span>{" "}
                      <Link to={`/runs/${lap.run_id}`} className="text-accent-700 underline">{lap.driver.code}, {lap.test.test_date}</Link>
                    </li>
                  ))}
                </ol>
              )
            }
          </Resource>
        </div>
        <div>
          <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500">Distance in season {run.season.name}</h3>
          <Resource state={mileage}>
            {(m) => (
              <p className="mt-1">
                <span className="font-mono text-2xl">{formatDistance(m.distance_m)}</span>
                <span className="block text-xs text-slate-600">{m.counted_lap_count} laps over {m.contributing_run_count} runs</span>
              </p>
            )}
          </Resource>
        </div>
      </div>
    </Section>
  );
}
