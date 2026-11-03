// The API's shapes (api/main.py) and a small fetch helper. Every number is computed by the
// Python package; the browser only shows it.

export type Value = string | number | boolean | null;

export interface Tile {
  label: string;
  value: string;
  delta: string | null;
}

export interface Market {
  tiles: Tile[];
  details: string[];
  session?: string | null;
}

export interface Stat {
  label: string;
  value: string;
}

export interface BoardRow {
  ticker: string;
  scan: string;
  scan_label: string;
  grade: string;
  run_label: string;
  run_slot: string;
  exchange?: string | null;
  chg_pct?: number | null;
  avwap_anchor?: string | null;
  run_session?: string | null;
  facts: string[];
  stats: Stat[];
  levels: Record<string, number>;
  [key: string]: unknown;
}

export type Scope = "graded" | "pushed" | "all";

export interface Today {
  scope: Scope;
  rows: BoardRow[];
  hidden_c: number;
  total: number;
}

export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Line {
  name: string;
  colour: string;
  scale: "right" | "rs";
  pts: { time: string; value: number }[];
}

export interface Bars {
  ticker: string;
  tf: "1D" | "1W";
  candles: Candle[];
  lines: Line[];
}

export interface RunInfo {
  id: string;
  label: string;
  session: string;
  slot: string;
  kind: string;
  has_universe: boolean;
  has_breadth: boolean;
}

export interface RunScans {
  run: string;
  label: string;
  scans: Record<string, { label: string; pushed: boolean; count: number; hits: unknown[] }>;
}

export type FieldKind = "num" | "pct" | "money" | "bool" | "text";

export interface Filter {
  field: string;
  op: string;
  value: Value | Value[];
}

export interface ScreenSpec {
  filters: Filter[];
  sort: string | null;
  descending: boolean;
}

export interface ScreenerMeta {
  fields: Record<string, { label: string; kind: FieldKind; group: string }>;
  ops: Record<FieldKind, string[]>;
  shown: string[];
  examples: Record<string, ScreenSpec>;
  saved: Record<string, ScreenSpec>;
  labels: Record<string, string>;
}

export interface ScreenRequest extends ScreenSpec {
  source: "all" | "hits";
  data: "close" | "live";
  run?: string | null;
  scan?: string | null;
  tiers?: string[];
}

export interface ScreenResult {
  count: number;
  when: string;
  summary: string;
  columns: string[];
  rows: Record<string, Value>[];
}

export const INDICATORS = [
  "MA 10",
  "MA 20",
  "MA 50",
  "MA 200",
  "EMA 9",
  "EMA 21",
  "AVWAP (signal day)",
  "RS vs QQQ",
] as const;
export const DEFAULT_INDICATORS = ["MA 10", "MA 20", "MA 50"];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(String(detail));
  }
  return (await res.json()) as T;
}

export const api = {
  today: (scope: Scope, tickers?: string[]) => {
    const q = new URLSearchParams({ scope });
    if (tickers?.length) q.set("t", tickers.join(","));
    return request<Today>(`/api/today?${q}`);
  },
  market: () => request<Market>("/api/market"),
  bars: (ticker: string, tf: "1D" | "1W", indicators: string[], anchor?: string | null) => {
    const q = new URLSearchParams({ tf, indicators: indicators.join(",") });
    if (anchor) q.set("anchor", anchor);
    return request<Bars>(`/api/bars/${encodeURIComponent(ticker)}?${q}`);
  },
  runs: () => request<RunInfo[]>("/api/runs"),
  runScans: (id: string) => request<RunScans>(`/api/runs/${encodeURIComponent(id)}/scans`),
  screenerMeta: () => request<ScreenerMeta>("/api/screener/meta"),
  options: (field: string) =>
    request<string[]>(`/api/screener/options/${encodeURIComponent(field)}`),
  runScreen: (body: ScreenRequest) =>
    request<ScreenResult>("/api/screener/run", { method: "POST", body: JSON.stringify(body) }),
  saveScreen: (name: string, spec: ScreenSpec) =>
    request<Record<string, ScreenSpec>>(`/api/screens/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify(spec),
    }),
  deleteScreen: (name: string) =>
    request<Record<string, ScreenSpec>>(`/api/screens/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
};
