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

export type Scope = "graded" | "pushed" | "all" | "watchlists";

export interface Today {
  scope: Scope | "screen";
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
  tickers: string[];
  tv_list: string;
  signal_ids: Record<string, string>;
}

export type Row = Record<string, Value>;

export interface TicketLine {
  label: string;
  value: string;
}

export interface TicketView {
  kinds: Record<string, string>;
  default: string;
  kind: string;
  price_label: string;
  plan_price: number | null;
  note: string | null;
  error: string | null;
  ticket: {
    order_type: string;
    shares: number;
    est_entry: number;
    stop: number;
    risk_usd: number;
    position_usd: number;
    capped: boolean;
    when: string;
    lines: TicketLine[];
    caption: string;
  } | null;
}

export interface StockNote {
  note_id: string;
  note_date: string;
  text: string;
}

export interface Alert {
  alert_id: string;
  ticker: string;
  level: number;
  direction: string;
  note: string;
}

export interface Alerts {
  directions: string[];
  alerts: Alert[];
  fired: Row[];
  message?: string;
}

export interface GradeNote {
  kind: "signal" | "trade";
  ref_id: string;
  grades: string[];
  grade: string;
  notes: string;
  tags: string;
  attachments: string[];
  message?: string;
}

export interface Totals {
  positions: number;
  open_pnl: number;
  at_risk_usd: number;
  at_risk_pct: number | null;
}

export interface PositionCard {
  ticker: string;
  setup: string;
  direction: string;
  shares: number;
  entry_date: string;
  entry: number;
  price: number | null;
  move_pct: number | null;
  open_r: number | null;
  pnl: number | null;
  to_stop_pct: number | null;
  stop: number | null;
  facts: string[];
}

export interface Positions {
  source: string | null;
  totals: Totals;
  cards: PositionCard[];
  caption?: string;
}

export interface JournalOpen {
  totals: Totals;
  rows: Row[];
  plan: Row[];
  plan_day: string | null;
  plan_caption?: string;
}

export interface PlanHit {
  ticker: string;
  scan: string;
  plan_entry: number;
  plan_stop: number;
  label: string;
}

export interface JournalPlans {
  today: string;
  plans: Row[];
  hits: PlanHit[];
  setups: string[];
  message?: string;
}

export interface Suggestion {
  suggestion: { shares: number; position_usd: number; risk_usd: number; capped: boolean } | null;
  text: string | null;
}

export interface ClosedStats {
  trades: number;
  win_rate: number | null;
  avg_r: number | null;
  pnl: number;
}

export interface JournalClosed {
  stats: ClosedStats;
  curve: { time: string; value: number }[];
  trades: Row[];
  caption: string;
}

export interface Table {
  columns: string[];
  rows: Row[];
  caption?: string;
}

export interface WatchList {
  name: string;
  label: string | null;
  columns: string[];
  rows: Row[];
  tv_list: string;
}

export interface WatchAdded {
  kind: "success" | "warning" | "error";
  added: string[];
  already: string[];
  unknown: string[];
  lines: string[];
}

export type ScanWatchlists = Record<string, { label: string; rows: Row[] }>;

export interface TrendLine {
  id: string;
  label: string;
  colour: string;
  x0: string;
  y0: number;
  x1: string;
  y1: number;
  extend: boolean;
  pts: { time: string; value: number }[];
}

export interface Level {
  name: string;
  price: number;
  colour: string;
}

export interface ChartMarker {
  time: string;
  position: "aboveBar" | "belowBar";
  shape: "arrowUp" | "arrowDown";
  color: string;
  text: string;
}

export interface ChartData {
  ticker: string;
  period: string;
  timeframe: string;
  candles: Candle[];
  lines: Line[];
  avwaps: { name: string; colour: string; pts: { time: string; value: number }[] }[];
  trend: TrendLine[];
  markers: ChartMarker[];
  levels: Level[];
  visible: { from: string; to: string } | null;
  quick_anchors: Record<string, string>;
  marks: Row[];
  dates: string[];
  tradingview: string;
  note: string;
}

export interface ChartNotes {
  notes: { note_id: string; note_date: string; text: string; written: string | null; edited: string | null }[];
  daily: { note_date: string; text: string; also: string[] }[];
}

export interface IntradayDays {
  study_days: string[];
  live: boolean;
  live_sessions: string[];
  no_keys: string;
}

export interface Intraday {
  candles: { time: number; open: number; high: number; low: number; close: number; volume: number; extended: boolean }[];
  vwap: { time: number; value: number }[];
  levels: Level[];
}

export interface ChartQuery {
  period: string;
  timeframe: string;
  span: string;
  lines: string[];
  hits: boolean;
  fills: boolean;
  levels: boolean;
  anchors: string[];
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

const post = <T>(path: string, body: unknown, method = "POST") =>
  request<T>(path, { method, body: JSON.stringify(body) });
const enc = encodeURIComponent;

export const api = {
  today: (scope: Scope, tickers?: string[], screen?: string | null) => {
    const q = new URLSearchParams({ scope });
    if (tickers?.length) q.set("t", tickers.join(","));
    if (screen) q.set("screen", screen);
    return request<Today>(`/api/today?${q}`);
  },
  ticket: (row: BoardRow, kind?: string | null, price?: number | null) =>
    post<TicketView>("/api/ticket", { row, kind, price }),
  placeTicket: (row: BoardRow, kind?: string | null, price?: number | null) =>
    post<{ plan_id: string; message: string }>("/api/ticket/place", { row, kind, price }),
  flag: (ticker: string, name: string) => post<{ message: string }>("/api/flags", { ticker, name }),
  stockNotes: (ticker: string) => request<StockNote[]>(`/api/stock-notes/${enc(ticker)}`),
  addStockNote: (ticker: string, text: string) =>
    post<StockNote[]>(`/api/stock-notes/${enc(ticker)}`, { text }),
  alerts: () => request<Alerts>("/api/alerts"),
  addAlert: (ticker: string, level: number, direction: string, note = "") =>
    post<Alerts>("/api/alerts", { ticker, level, direction, note }),
  removeAlert: (id: string) => request<Alerts>(`/api/alerts/${enc(id)}`, { method: "DELETE" }),
  grade: (kind: "signal" | "trade", ref: string) =>
    request<GradeNote>(`/api/grades/${kind}/${enc(ref)}`),
  saveGrade: (
    kind: "signal" | "trade",
    ref: string,
    body: { grade: string; notes: string; tags: string; screenshots: { name: string; data: string }[] },
  ) => post<GradeNote>(`/api/grades/${kind}/${enc(ref)}`, body, "PUT"),
  positions: () => request<Positions>("/api/positions"),
  journalOpen: () => request<JournalOpen>("/api/journal/open"),
  journalSetups: () => request<string[]>("/api/journal/setups"),
  logFill: (body: Record<string, unknown>) => post<{ message: string }>("/api/journal/fills", body),
  journalPlans: () => request<JournalPlans>("/api/journal/plans"),
  suggest: (entry: number, stop: number) =>
    request<Suggestion>(`/api/journal/plans/suggest?entry=${entry}&stop=${stop}`),
  createPlan: (body: Record<string, unknown>) => post<JournalPlans>("/api/journal/plans", body),
  cancelPlan: (id: string) => post<JournalPlans>(`/api/journal/plans/${enc(id)}/cancel`, {}),
  journalClosed: () => request<JournalClosed>("/api/journal/closed"),
  realVsStudy: () => request<Table>("/api/journal/real-vs-study"),
  watchlists: () => request<{ lists: string[]; flags: string[] }>("/api/watchlists"),
  watchlist: (name: string) => request<WatchList>(`/api/watchlists/${enc(name)}`),
  addToWatchlist: (name: string, text: string, exportText: string, note: string) =>
    post<WatchAdded>(`/api/watchlists/${enc(name)}/add`, {
      text,
      export_text: exportText,
      note,
    }),
  removeFromWatchlist: (name: string, tickers: string[]) =>
    post<WatchList>(`/api/watchlists/${enc(name)}/remove`, { tickers }),
  chartPicks: () => request<{ ticker: string; where: string }[]>("/api/chart/picks"),
  chart: (ticker: string, q: ChartQuery) => {
    const p = new URLSearchParams({
      period: q.period,
      timeframe: q.timeframe,
      span: q.span,
      lines: q.lines.join(","),
      hits: String(q.hits),
      fills: String(q.fills),
      levels: String(q.levels),
      anchors: q.anchors.join(","),
    });
    return request<ChartData>(`/api/chart/${enc(ticker)}?${p}`);
  },
  addLine: (ticker: string, body: { x0: string; y0: number; x1: string; y1: number; label?: string; extend: boolean }) =>
    post<{ mark_id: string }>(`/api/chart/${enc(ticker)}/lines`, body),
  moveLine: (ticker: string, id: string, body: { x0: string; y0: number; x1: string; y1: number; extend: boolean }) =>
    post<{ mark_id: string }>(`/api/chart/${enc(ticker)}/lines/${enc(id)}`, body, "PUT"),
  addAnchor: (ticker: string, day: string, label: string) =>
    post<{ mark_id: string }>(`/api/chart/${enc(ticker)}/anchors`, { day, label }),
  removeMark: (ticker: string, id: string) =>
    request<{ removed: string }>(`/api/chart/${enc(ticker)}/marks/${enc(id)}`, { method: "DELETE" }),
  chartNotes: (ticker: string) => request<ChartNotes>(`/api/chart/${enc(ticker)}/notes`),
  addChartNote: (ticker: string, text: string, day: string) =>
    post<ChartNotes>(`/api/chart/${enc(ticker)}/notes`, { text, day }),
  editChartNote: (ticker: string, id: string, text: string, day: string) =>
    post<ChartNotes>(`/api/chart/${enc(ticker)}/notes/${enc(id)}`, { text, day }, "PUT"),
  removeChartNote: (ticker: string, id: string) =>
    request<ChartNotes>(`/api/chart/${enc(ticker)}/notes/${enc(id)}`, { method: "DELETE" }),
  intradayDays: (ticker: string) => request<IntradayDays>(`/api/chart/${enc(ticker)}/intraday-days`),
  intraday: (ticker: string, day: string, every: number, source: "study" | "live") =>
    request<Intraday>(`/api/chart/${enc(ticker)}/intraday?day=${day}&every=${every}&source=${source}`),
  scanWatchlists: (all: boolean) =>
    request<ScanWatchlists>(`/api/scan-watchlists?include_ended=${all}`),
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
