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
  tdTextClass,
  thClass,
} from "../components/ui";
import type { AttemptSummary, PlannedRun, TestPlanVsActual } from "../types/api";
import { formatLapTime, humanize } from "../utils/format";

export function TestDetailPage() {
  const rawId = useParams().testId ?? "";
  const testId = Number(rawId);
  const test = useResource((signal) => api.test(testId, signal), `test-${testId}`);
  const plan = useResource((signal) => api.planVsActual(testId, signal), `pva-${testId}`);
  const objectives = useResource((signal) => api.testObjectives(testId, signal), `objectives-${testId}`);

  if (test.status === "loading") return <Loading label="Loading test…" />;
  if (test.status === "error") {
    if (test.error instanceof ApiError && test.error.status === 404) {
      return (
        <div role="alert" className="space-y-2">
          <h1 className="text-xl font-semibold">Test not found</h1>
          <p className="text-sm text-slate-600">There is no test with id {rawId}.</p>
          <Link to="/runs" className="text-accent-700 underline">Back to run history</Link>
        </div>
      );
    }
    return <ErrorPanel error={test.error} onRetry={test.reload} />;
  }
  const data = test.data;
  const plansById = new Map(data.planned_runs.map((p) => [p.id, p]));

  return (
    <>
      <PageHeader
        title={data.title ?? `Test ${data.test_date}`}
        subtitle={<>{data.test_date} · {data.track_location.name} · {data.vehicle.code} · {data.season.name}</>}
        actions={<Badge tone={statusTone(data.status)}>{humanize(data.status)}</Badge>}
      />
      <div className="space-y-4">
        <Section title="Test context">
          <Facts
            items={[
              ["Season", data.season.name],
              ["Vehicle", `${data.vehicle.code} · ${data.vehicle.name}`],
              ["Track location", data.track_location.name],
              ["Problems encountered", data.problems_encountered],
              ["Engineering conclusions", data.engineering_conclusions],
            ]}
          />
        </Section>

        <Section title="Planned versus actual">
          <Resource state={plan} label="Loading plan comparison…">
            {(pva) => <PlanVsActual pva={pva} plans={plansById} />}
          </Resource>
        </Section>

        <Section title="Objectives addressed">
          <Resource state={objectives}>
            {(items) =>
              items.length === 0 ? (
                <Empty>No objectives are linked to this test.</Empty>
              ) : (
                <ul className="space-y-1 text-sm">
                  {items.map((o) => (
                    <li key={o.id} className="flex flex-wrap items-center gap-2">
                      <Badge tone={o.priority === "CRITICAL" ? "bad" : "neutral"}>{humanize(o.priority)}</Badge>
                      <span>{o.description}</span>
                      <Badge tone={statusTone(o.status)}>{humanize(o.status)}</Badge>
                    </li>
                  ))}
                </ul>
              )
            }
          </Resource>
        </Section>
      </div>
    </>
  );
}

function PlanVsActual({ pva, plans }: { pva: TestPlanVsActual; plans: Map<number, PlannedRun> }) {
  const c = pva.counts;
  return (
    <>
      <p className="mb-3 text-sm text-slate-700">
        {c.planned_runs} planned · {c.executed} executed · {c.not_executed} not executed · {c.cancelled} cancelled ·{" "}
        {c.replaced} replaced · {c.with_repeated_attempts} with repeated attempts · {c.actual_runs} actual runs ·{" "}
        {c.unexpected_runs} unexpected
      </p>
      {pva.planned_runs.length === 0 ? (
        <Empty>This test has no run plan.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className={tableClass}>
            <caption className="sr-only">Planned runs and their actual attempts</caption>
            <thead className="bg-slate-50">
              <tr>
                {["#", "Outcome", "Plan", "Attempts", "Notes"].map((h) => (
                  <th key={h} scope="col" className={thClass}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {pva.planned_runs.map((outcome) => {
                const plan = plans.get(outcome.planned_run_id);
                return (
                  <tr key={outcome.planned_run_id}>
                    <td className={`${tdClass} font-mono`}>{outcome.sequence_number}</td>
                    <td className={tdClass}>
                      <div className="flex flex-wrap gap-1">
                        <Badge tone={statusTone(outcome.category)}>{humanize(outcome.category)}</Badge>
                        {outcome.repeated && <Badge tone="warn">Repeated attempts</Badge>}
                      </div>
                    </td>
                    <td className={tdTextClass}>
                      {plan?.expected_lap_count != null && <div>{plan.expected_lap_count} laps expected</div>}
                      {plan?.target_lap_time_ms != null && <div>target {formatLapTime(plan.target_lap_time_ms)}</div>}
                      {plan?.notes && <div className="text-slate-500">{plan.notes}</div>}
                    </td>
                    <td className={tdTextClass}>
                      {outcome.attempts.length === 0 ? <span className="text-slate-500">none</span> : <Attempts attempts={outcome.attempts} />}
                    </td>
                    <td className={tdTextClass}>
                      {outcome.cancellation_reason && <div>Cancelled: {outcome.cancellation_reason}</div>}
                      {outcome.replacement_reason && (
                        <div>
                          Replaced{outcome.replaced_by_planned_run_id && ` by plan ${plans.get(outcome.replaced_by_planned_run_id)?.sequence_number ?? outcome.replaced_by_planned_run_id}`}:{" "}
                          {outcome.replacement_reason}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <h3 className="mb-1 mt-4 text-sm font-semibold">Unexpected runs</h3>
      {pva.unexpected_runs.length === 0 ? <Empty>No unexpected runs.</Empty> : <Attempts attempts={pva.unexpected_runs} />}
    </>
  );
}

function Attempts({ attempts }: { attempts: AttemptSummary[] }) {
  return (
    <ul className="space-y-1">
      {attempts.map((a) => (
        <li key={a.run_id} className="text-sm">
          <Link to={`/runs/${a.run_id}`} className="font-medium text-accent-700 underline-offset-2 hover:underline">Run {a.run_number}</Link>{" "}
          <span className="text-slate-600">
            {a.physically_completed_lap_count}/{a.recorded_lap_count} laps · fastest {formatLapTime(a.fastest_effective_time_ms)}
          </span>
          {a.deviation_reason && <span className="text-slate-600"> · {a.deviation_reason}</span>}
          {a.differing_aspects.length > 0 && (
            <span className="ml-1 inline-flex flex-wrap gap-1">
              {a.differing_aspects.map((aspect) => (
                <Badge key={aspect} tone="bad">differs: {humanize(aspect.replace(/_(id|ms|kwh)$/, ""))}</Badge>
              ))}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}
