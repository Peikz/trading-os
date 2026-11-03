// Display formats for the Screener table (the same kinds as trading_os/screens.py FIELDS).
import type { FieldKind, Value } from "./api";

export const GRADE_COLOURS: Record<string, string> = {
  "A+": "#1a7f37",
  A: "#2da44e",
  B: "#bf8700",
  C: "#6e7781",
};

export function compact(x: number): string {
  const a = Math.abs(x);
  if (a >= 1e9) return `${(x / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `${(x / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${(x / 1e3).toFixed(1)}k`;
  return x.toFixed(0);
}

export function formatValue(v: Value | undefined, kind: FieldKind | undefined): string {
  if (v === null || v === undefined || v === "") return "–";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "string") return v;
  switch (kind) {
    case "pct":
      return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
    case "money":
      return Math.abs(v) >= 1e4 ? `$${compact(v)}` : `$${v.toFixed(2)}`;
    case "num":
      return Number.isInteger(v) ? compact(v) : Math.abs(v) >= 1e4 ? compact(v) : v.toFixed(2);
    default:
      return String(v);
  }
}

/** The move colour: green up, red down (VIX the other way round, as on the Streamlit tiles). */
export function deltaColour(label: string, delta: string | null): string | undefined {
  if (!delta || label === "IBD market") return undefined;
  const up = !delta.startsWith("-");
  return up !== (label === "VIX") ? "var(--up)" : "var(--down)";
}
