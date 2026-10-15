import { type FormEvent, type ReactNode, useState } from "react";
import { useNavigate } from "react-router";
import { ApiError } from "../api/client";
import { api } from "../api/endpoints";
import { useResource } from "../api/useResource";
import { ErrorPanel, PageHeader, Resource, Section, buttonPrimary, inputClass } from "../components/ui";
import { TEST_STATUSES, type TestCreate } from "../types/api";
import { humanize } from "../utils/format";

interface FormState {
  season_id: string;
  vehicle_id: string;
  track_location_id: string;
  test_date: string;
  status: string;
  title: string;
  problems_encountered: string;
  engineering_conclusions: string;
  add_plan: boolean;
  expected_driver_id: string;
  expected_track_layout_id: string;
  expected_lap_count: string;
  target_lap_time_ms: string;
}

const EMPTY: FormState = {
  season_id: "", vehicle_id: "", track_location_id: "", test_date: "", status: "PLANNED", title: "",
  problems_encountered: "", engineering_conclusions: "", add_plan: false, expected_driver_id: "",
  expected_track_layout_id: "", expected_lap_count: "", target_lap_time_ms: "",
};

type Errors = Partial<Record<keyof FormState, string>>;
const POSITIVE_INT = /^[1-9]\d*$/;

export function validateTestForm(form: FormState): Errors {
  const errors: Errors = {};
  if (!form.season_id) errors.season_id = "Choose a season.";
  if (!form.vehicle_id) errors.vehicle_id = "Choose a vehicle.";
  if (!form.track_location_id) errors.track_location_id = "Choose a track location.";
  if (!form.test_date) errors.test_date = "Enter the test date.";
  if (form.add_plan) {
    if (form.expected_lap_count && !POSITIVE_INT.test(form.expected_lap_count)) errors.expected_lap_count = "Use a whole number above 0.";
    if (form.target_lap_time_ms && !POSITIVE_INT.test(form.target_lap_time_ms)) errors.target_lap_time_ms = "Use whole milliseconds above 0.";
  }
  return errors;
}

function toRequest(form: FormState): TestCreate {
  const text = (value: string) => value.trim() || null;
  const number = (value: string) => (value ? Number(value) : null);
  return {
    season_id: Number(form.season_id),
    vehicle_id: Number(form.vehicle_id),
    track_location_id: Number(form.track_location_id),
    test_date: form.test_date,
    status: form.status as TestCreate["status"],
    title: text(form.title),
    problems_encountered: text(form.problems_encountered),
    engineering_conclusions: text(form.engineering_conclusions),
    planned_runs: form.add_plan
      ? [{
          sequence_number: 1,
          expected_driver_id: number(form.expected_driver_id),
          expected_track_layout_id: number(form.expected_track_layout_id),
          expected_lap_count: number(form.expected_lap_count),
          target_lap_time_ms: number(form.target_lap_time_ms),
        }]
      : [],
  };
}

function loadOptions(signal: AbortSignal) {
  return Promise.all([api.seasons(signal), api.vehicles(signal), api.trackLocations(signal), api.drivers(signal), api.trackLayouts({}, signal)]);
}

export function CreateTestPage() {
  const navigate = useNavigate();
  const options = useResource(loadOptions, "create-test-options");
  const [form, setForm] = useState<FormState>(EMPTY);
  const [errors, setErrors] = useState<Errors>({});
  const [submitError, setSubmitError] = useState<Error | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const set = (key: keyof FormState) => (value: string | boolean) => setForm((f) => ({ ...f, [key]: value }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    const found = validateTestForm(form);
    setErrors(found);
    setSubmitError(null);
    if (Object.keys(found).length) return;
    setSubmitting(true);
    try {
      const created = await api.createTest(toRequest(form));
      navigate(`/tests/${created.id}`);
    } catch (error) {
      setSubmitError(error instanceof Error ? error : new Error(String(error)));
      if (error instanceof ApiError) setErrors(error.fieldErrors() as Errors);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <PageHeader title="New test" subtitle="Create a test day, optionally with its first planned run." />
      <Resource state={options} label="Loading form options…">
        {([seasons, vehicles, locations, drivers, layouts]) => {
          const layoutsHere = layouts.items.filter((l) => String(l.track_location_id) === form.track_location_id);
          return (
            <form onSubmit={submit} noValidate className="max-w-3xl space-y-4" aria-label="Create test">
              {submitError && <ErrorPanel error={submitError} />}
              <Section title="Test day">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <Choice id="season_id" label="Season *" value={form.season_id} onChange={set("season_id")} error={errors.season_id}
                    options={seasons.items.map((s) => [String(s.id), s.name])} />
                  <Choice id="vehicle_id" label="Vehicle *" value={form.vehicle_id} onChange={set("vehicle_id")} error={errors.vehicle_id}
                    options={vehicles.items.map((v) => [String(v.id), `${v.code} · ${v.name}`])} />
                  <Choice id="track_location_id" label="Track location *" value={form.track_location_id} error={errors.track_location_id}
                    onChange={(value) => setForm((f) => ({ ...f, track_location_id: value, expected_track_layout_id: "" }))}
                    options={locations.items.map((l) => [String(l.id), l.name])} />
                  <Text id="test_date" label="Test date *" type="date" value={form.test_date} onChange={set("test_date")} error={errors.test_date} />
                  <Choice id="status" label="Status" value={form.status} onChange={set("status")} error={errors.status} required
                    options={TEST_STATUSES.map((s) => [s, humanize(s)])} />
                  <Text id="title" label="Title" value={form.title} onChange={set("title")} error={errors.title} />
                </div>
                <div className="mt-3 grid grid-cols-1 gap-3">
                  <Area id="problems_encountered" label="Problems encountered" value={form.problems_encountered} onChange={set("problems_encountered")} error={errors.problems_encountered} />
                  <Area id="engineering_conclusions" label="Engineering conclusions" value={form.engineering_conclusions} onChange={set("engineering_conclusions")} error={errors.engineering_conclusions} />
                </div>
              </Section>
              <Section title="First planned run (optional)">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={form.add_plan} onChange={(e) => set("add_plan")(e.target.checked)} />
                  Add planned run 1
                </label>
                {form.add_plan && (
                  <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <Choice id="expected_driver_id" label="Expected driver" value={form.expected_driver_id} onChange={set("expected_driver_id")} error={errors.expected_driver_id}
                      options={drivers.items.map((d) => [String(d.id), `${d.code} · ${d.full_name}`])} />
                    <Choice id="expected_track_layout_id" label="Expected layout" value={form.expected_track_layout_id} onChange={set("expected_track_layout_id")} error={errors.expected_track_layout_id}
                      options={layoutsHere.map((l) => [String(l.id), l.name])}
                      hint={form.track_location_id ? undefined : "Choose a track location first."} />
                    <Text id="expected_lap_count" label="Expected laps" value={form.expected_lap_count} onChange={set("expected_lap_count")} error={errors.expected_lap_count} inputMode="numeric" />
                    <Text id="target_lap_time_ms" label="Target lap time (ms)" value={form.target_lap_time_ms} onChange={set("target_lap_time_ms")} error={errors.target_lap_time_ms} inputMode="numeric" />
                  </div>
                )}
              </Section>
              <button type="submit" className={buttonPrimary} disabled={submitting}>
                {submitting ? "Creating…" : "Create test"}
              </button>
            </form>
          );
        }}
      </Resource>
    </>
  );
}

function FieldShell({ id, label, error, hint, children }: { id: string; label: string; error?: string; hint?: string; children: ReactNode }) {
  return (
    <div className="text-sm">
      <label htmlFor={id} className="block font-medium text-slate-700">{label}</label>
      {children}
      {hint && !error && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
      {error && <p id={`${id}-error`} className="mt-1 text-xs text-red-700">{error}</p>}
    </div>
  );
}

const describedBy = (id: string, error?: string) => ({
  "aria-invalid": error ? true : undefined,
  "aria-describedby": error ? `${id}-error` : undefined,
});

function Choice({ id, label, value, onChange, options, error, hint, required }: {
  id: string; label: string; value: string; onChange: (v: string) => void; options: [string, string][]; error?: string; hint?: string; required?: boolean;
}) {
  return (
    <FieldShell id={id} label={label} error={error} hint={hint}>
      <select id={id} className={inputClass} value={value} onChange={(e) => onChange(e.target.value)} {...describedBy(id, error)}>
        {!required && <option value="">Select…</option>}
        {options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
      </select>
    </FieldShell>
  );
}

function Text({ id, label, value, onChange, error, type = "text", inputMode }: {
  id: string; label: string; value: string; onChange: (v: string) => void; error?: string; type?: string; inputMode?: "numeric";
}) {
  return (
    <FieldShell id={id} label={label} error={error}>
      <input id={id} type={type} inputMode={inputMode} className={inputClass} value={value} onChange={(e) => onChange(e.target.value)} {...describedBy(id, error)} />
    </FieldShell>
  );
}

function Area({ id, label, value, onChange, error }: { id: string; label: string; value: string; onChange: (v: string) => void; error?: string }) {
  return (
    <FieldShell id={id} label={label} error={error}>
      <textarea id={id} rows={3} className={inputClass} value={value} onChange={(e) => onChange(e.target.value)} {...describedBy(id, error)} />
    </FieldShell>
  );
}
