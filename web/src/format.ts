// Display formats for the Screener table (the same kinds as trading_os/screens.py FIELDS).
import type { FieldKind, Value } from "./api";

export const GRADE_COLOURS: Record<string, string> = {
  "A+++": "#063d19",
  "A++": "#0b5a26",
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

/** A table cell for the Journal / Watchlists tables: money columns as $, the rest plain. */
const MONEY = /(pnl|_usd|risk_to_stop)$/;
const STAMP = /^\d{4}-\d\d-\d\dT/;
export function cell(column: string, v: Value | undefined): string {
  if (v === null || v === undefined || v === "") return "–";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "string") return STAMP.test(v) ? v.slice(0, 16).replace("T", " ") : v;
  if (MONEY.test(column)) return usd(v);
  if (Number.isInteger(v)) return v.toLocaleString("en-US");
  return v.toFixed(2);
}

export function signed(x: number | null | undefined, digits = 2, unit = ""): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "n/a";
  return `${x >= 0 ? "+" : ""}${x.toFixed(digits)}${unit}`;
}

export function usd(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "n/a";
  const whole = Math.abs(x).toLocaleString("en-US", { maximumFractionDigits: 0 });
  return `${x < 0 ? "-" : ""}$${whole}`;
}

/** A text file to save (the TradingView list): a download link clicked once. */
export function download(name: string, text: string): void {
  if (typeof URL.createObjectURL !== "function") return; // jsdom
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export function copy(text: string): Promise<void> {
  return navigator.clipboard?.writeText(text) ?? Promise.resolve();
}

/** A picked file's text (FileReader: in every browser, and in the tests' jsdom). */
export function readText(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.readAsText(file);
  });
}
