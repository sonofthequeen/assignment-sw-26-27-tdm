import { Link, useParams } from "react-router";
import { api } from "../api/endpoints";
import { useResource } from "../api/useResource";
import { Badge, Empty, Facts, PageHeader, Resource, Section, tableClass, tdClass, thClass } from "../components/ui";
import { CORNERS, type SetupDiff } from "../types/api";
import { formatTimestamp, humanize, withUnit } from "../utils/format";

export function SetupSnapshotPage() {
  const id = Number(useParams().setupSnapshotId);
  const snapshot = useResource((s) => api.setupSnapshot(id, s), `setup-${id}`);
  const diff = useResource((s) => api.setupDiff(id, s), `setup-diff-${id}`);

  return (
    <Resource state={snapshot} label="Loading setup snapshot…">
      {(setup) => {
        const byCorner = new Map(setup.corners.map((c) => [c.corner, c]));
        return (
          <>
            <PageHeader
              title={setup.name ?? `Setup snapshot ${setup.id}`}
              subtitle={<>Intended setup for {setup.vehicle.code} · created {formatTimestamp(setup.created_at)}</>}
              actions={setup.is_derived ? <Badge tone="info">Derived</Badge> : <Badge>Root</Badge>}
            />
            <p className="mb-4 rounded-md border border-slate-200 bg-white p-3 text-sm text-slate-700">
              Snapshots are append-only: a change is recorded as a new snapshot derived from this one, so this view is read-only.
            </p>
            <div className="space-y-4">
              <Section title="Intended setup — vehicle">
                <Facts
                  items={[
                    ["Vehicle", `${setup.vehicle.code} · ${setup.vehicle.name}`],
                    ["Based on", setup.based_on ? <Link to={`/setups/${setup.based_on.id}`} className="text-accent-700 underline">{setup.based_on.name ?? `Snapshot ${setup.based_on.id}`}</Link> : "Root snapshot"],
                    ["Change reason", setup.change_reason],
                    ["Power limit", withUnit(setup.power_limit_kw, "kW")],
                    ["RPM limit", withUnit(setup.rpm_limit_rpm, "rpm")],
                    ["Torque vectoring", setup.torque_vectoring_mode],
                    ["Control map", setup.control_map],
                  ]}
                />
              </Section>
              <Section title="Intended setup — corners" aside={setup.missing_corners.length ? `No values recorded for ${setup.missing_corners.join(", ")}` : undefined}>
                <div className="overflow-x-auto">
                  <table className={tableClass}>
                    <caption className="sr-only">Static corner setup in FL, FR, RL, RR order</caption>
                    <thead className="bg-slate-50">
                      <tr>{["Corner", "Static camber", "Static toe", "Spring rate"].map((h) => <th key={h} scope="col" className={thClass}>{h}</th>)}</tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {CORNERS.map((corner) => {
                        const c = byCorner.get(corner);
                        return (
                          <tr key={corner}>
                            <th scope="row" className={`${tdClass} font-mono font-semibold`}>{corner}</th>
                            {c ? (
                              <>
                                <td className={`${tdClass} font-mono`}>{withUnit(c.static_camber_deg, "°")}</td>
                                <td className={`${tdClass} font-mono`}>{withUnit(c.static_toe_deg, "°")}</td>
                                <td className={`${tdClass} font-mono`}>{withUnit(c.spring_rate_n_per_mm, "N/mm")}</td>
                              </>
                            ) : (
                              <td colSpan={3} className={`${tdClass} text-slate-500`}>not recorded</td>
                            )}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Section>
              <Section title="Changes from the source snapshot">
                <Resource state={diff}>{(d) => <DiffView diff={d} />}</Resource>
              </Section>
            </div>
          </>
        );
      }}
    </Resource>
  );
}

function DiffView({ diff }: { diff: SetupDiff }) {
  if (diff.baseline === "NONE") return <Empty>This is a root snapshot; there is no source to compare with.</Empty>;
  if (!diff.has_changes) return <Empty>No engineering values differ from the source snapshot.</Empty>;
  const rows = [
    ...diff.vehicle_changes.map((c) => ({ key: c.field, where: "vehicle", ...c })),
    ...diff.corner_changes.map((c) => ({ key: `${c.corner}-${c.field}`, where: c.corner, ...c })),
  ];
  return (
    <>
      <table className={tableClass}>
        <caption className="sr-only">Changed values</caption>
        <thead className="bg-slate-50">
          <tr>{["Where", "Parameter", "Before", "After"].map((h) => <th key={h} scope="col" className={thClass}>{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row) => (
            <tr key={row.key}>
              <td className={`${tdClass} font-mono`}>{row.where}</td>
              <td className={tdClass}>{humanize(row.field)}</td>
              <td className={`${tdClass} font-mono`}>{row.previous ?? "—"}</td>
              <td className={`${tdClass} font-mono`}>{row.current ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {(diff.corners_added.length > 0 || diff.corners_removed.length > 0) && (
        <p className="mt-2 text-sm">
          {diff.corners_added.length > 0 && <>Corners added: {diff.corners_added.join(", ")}. </>}
          {diff.corners_removed.length > 0 && <>Corners removed: {diff.corners_removed.join(", ")}.</>}
        </p>
      )}
    </>
  );
}
