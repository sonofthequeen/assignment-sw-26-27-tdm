// Display formatting only: values stay in their stored units (ms, m, °C, kPa, deg);
// decimals are formatted from their string form, never via binary floats.

/** 62450 -> "1:02.450"; 5390 -> "0:05.390"; null -> "—". */
export function formatLapTime(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.floor((ms % 60_000) / 1000);
  const millis = ms % 1000;
  return `${minutes}:${String(seconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
}

/** Penalty display: 2000 -> "+2.000 s"; 0 -> "—". */
export function formatPenalty(ms: number): string {
  if (!ms) return "—";
  return `+${Math.floor(ms / 1000)}.${String(ms % 1000).padStart(3, "0")} s`;
}

/** "6900.000" -> "6 900.000 m" (thousands grouped from the string, exact). */
export function formatDistance(metres: string): string {
  const [whole = "0", fraction] = metres.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  return `${grouped}${fraction !== undefined ? `.${fraction}` : ""} m`;
}

export function withUnit(value: string | number | null | undefined, unit: string): string {
  return value === null || value === undefined || value === "" ? "—" : `${value} ${unit}`;
}

/** "IN_LAP" -> "In lap". */
export function humanize(value: string): string {
  const text = value.replaceAll("_", " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  return iso.replace("T", " ").replace(/\.\d+/, "").replace("Z", " UTC");
}
