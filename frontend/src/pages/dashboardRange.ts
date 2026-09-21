import type { Scope } from "../api";

export type RangePreset = "month" | "3m" | "6m" | "12m" | "ytd" | "all" | "custom";
export type RangeState = {
  preset: RangePreset;
  date_from: string;
  date_to: string;
  scope: "" | Scope;
};

const key = "spendloom.dashboard.range";
const iso = (value: Date) => value.toISOString().slice(0, 10);

function monthStart(monthsBack = 0): string {
  const now = new Date();
  return iso(new Date(now.getFullYear(), now.getMonth() - monthsBack, 1));
}

function defaultRange(): RangeState {
  return { preset: "12m", date_from: monthStart(11), date_to: iso(new Date()), scope: "" };
}

export function readSavedRange(): RangeState {
  const fallback = defaultRange();
  try {
    const saved = { ...fallback, ...JSON.parse(localStorage.getItem(key) || "{}") } as RangeState;
    return rangeError(saved) ? fallback : saved;
  } catch {
    return fallback;
  }
}

export function saveRange(range: RangeState): void {
  localStorage.setItem(key, JSON.stringify(range));
}

export function rangeError(range: RangeState): string {
  if (!range.date_from || !range.date_to) return "Select both dates.";
  if (typeof range.date_from !== "string" || typeof range.date_to !== "string") return "Select valid dates.";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(range.date_from) || !/^\d{4}-\d{2}-\d{2}$/.test(range.date_to)) {
    return "Select valid dates.";
  }
  if (range.date_from > range.date_to) return "From must be on or before To.";
  return "";
}

export function presetRange(preset: RangePreset, current: RangeState): RangeState {
  const today = iso(new Date());
  if (preset === "month") return { ...current, preset, date_from: monthStart(), date_to: today };
  if (preset === "3m") return { ...current, preset, date_from: monthStart(2), date_to: today };
  if (preset === "6m") return { ...current, preset, date_from: monthStart(5), date_to: today };
  if (preset === "12m") return { ...current, preset, date_from: monthStart(11), date_to: today };
  if (preset === "ytd") return { ...current, preset, date_from: `${new Date().getFullYear()}-01-01`, date_to: today };
  if (preset === "all") return { ...current, preset, date_from: "1900-01-01", date_to: today };
  return { ...current, preset };
}
