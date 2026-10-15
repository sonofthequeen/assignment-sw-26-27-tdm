import type { ReactNode } from "react";
import { ApiError, NetworkError } from "../api/client";
import type { ResourceState } from "../api/useResource";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-600">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}

export function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm" aria-labelledby={slug(title)}>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={slug(title)} className="text-base font-semibold">{title}</h2>
        {aside && <div className="text-xs text-slate-500">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

function slug(text: string): string {
  return `section-${text.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p role="status" className="animate-pulse py-4 text-sm text-slate-500">
      {label}
    </p>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-4 text-sm text-slate-500">{children}</p>;
}

export function describeError(error: Error): { title: string; message: string } {
  if (error instanceof NetworkError) {
    return { title: "Backend unreachable", message: `${error.message} Is the API running on port 8000?` };
  }
  if (error instanceof ApiError) {
    if (error.status === 404) return { title: "Not found", message: error.message };
    return { title: `Request rejected (${error.code})`, message: error.message };
  }
  return { title: "Unexpected error", message: "The page could not be displayed." };
}

export function ErrorPanel({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const { title, message } = describeError(error);
  const details = error instanceof ApiError ? error.details : [];
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-900">
      <p className="font-semibold">{title}</p>
      <p>{message}</p>
      {details.length > 0 && (
        <ul className="mt-2 list-disc pl-5">
          {details.map((detail, index) => (
            <li key={index}>
              {detail.field && <code className="font-mono">{detail.field}</code>}
              {detail.field && ": "}
              {detail.issue}
            </li>
          ))}
        </ul>
      )}
      {onRetry && (
        <button type="button" onClick={onRetry} className="mt-2 rounded border border-red-300 bg-white px-2 py-1 font-medium hover:bg-red-100">
          Retry
        </button>
      )}
    </div>
  );
}

/** Renders loading / error / content for one resource. */
export function Resource<T>({
  state,
  children,
  label,
}: {
  state: ResourceState<T> & { reload: () => void };
  children: (data: T) => ReactNode;
  label?: string;
}) {
  if (state.status === "loading") return <Loading label={label} />;
  if (state.status === "error") return <ErrorPanel error={state.error} onRetry={state.reload} />;
  return <>{children(state.data)}</>;
}

const TONES = {
  neutral: "border-slate-300 bg-slate-100 text-slate-800",
  good: "border-emerald-300 bg-emerald-50 text-emerald-900",
  warn: "border-amber-300 bg-amber-50 text-amber-900",
  bad: "border-red-300 bg-red-50 text-red-900",
  info: "border-accent-100 bg-accent-50 text-accent-700",
} as const;
export type Tone = keyof typeof TONES;

/** A text badge: status is always written out, colour only reinforces it. */
export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: Tone }) {
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function statusTone(status: string): Tone {
  if (["COMPLETED", "EXECUTED", "MATCH", "TARGET_MET", "ACHIEVED"].includes(status)) return "good";
  if (["CANCELLED", "DIFFERENT", "TARGET_MISSED", "DROPPED"].includes(status)) return "bad";
  if (["REPLACED", "MODIFIED", "NOT_EXECUTED", "IN_PROGRESS", "ACTUAL_NOT_RECORDED"].includes(status)) return "warn";
  if (["PLANNED", "OPEN"].includes(status)) return "info";
  return "neutral";
}

export function Pagination({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);
  return (
    <nav aria-label="Pagination" className="mt-3 flex items-center justify-between gap-2 text-sm">
      <p aria-live="polite">
        {first}–{last} of {total}
      </p>
      <div className="flex gap-2">
        <button type="button" className={buttonSecondary} disabled={offset === 0} onClick={() => onChange(Math.max(offset - limit, 0))}>
          Previous
        </button>
        <button type="button" className={buttonSecondary} disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
          Next
        </button>
      </div>
    </nav>
  );
}

export const buttonPrimary =
  "rounded-md bg-accent-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-700 disabled:cursor-not-allowed disabled:opacity-50";
export const buttonSecondary =
  "rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40";
export const inputClass =
  "mt-1 block w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm aria-[invalid=true]:border-red-500";
export const tableClass = "min-w-full divide-y divide-slate-200 text-sm";
export const thClass = "px-2 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-slate-600";
export const tdClass = "px-2 py-1.5 align-top";

/** Two-column definition list for detail pages. */
export function Facts({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
      {items.map(([term, value]) => (
        <div key={term}>
          <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{term}</dt>
          <dd className="mt-0.5">{value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}
