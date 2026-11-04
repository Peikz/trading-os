// The API's shapes (api/main.py) and a small fetch helper. Every number is computed by the
// Python package; the browser only shows it.

export type Value = string | number | boolean | null;

export interface Tile {
  label: string;
  value: string;
  delta: string | null;
}

export type MoodLevel = "green" | "amber" | "red";

/** One word for the market (QQQ light + heat + IBD) with each reason (board_data.market_mood) */
export interface Mood {
  level: MoodLevel | null;
  word: string;
  reasons: { level: MoodLevel; text: string }[];
  quotes: Tile[];
}

export interface Market {
  tiles: Tile[];
  details: string[];
  session?: string | null;
  mood?: Mood;
}

/** The plan card's first line (board_data.decision) */
export interface Decision {
  text: string;
  local: string | null;
  session: string | null;
  day: string | null;
}

/** The "Why" card (board_data.why) */
export interface Why {
  summary: string | null;
  points: { ok: boolean; text: string }[];
  lines: string[];
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
  decision?: Decision | null;
  why?: Why;
  [key: string]: unknown;
}

export type Scope = "graded" | "pushed" | "all" | "watchlists";
export type Timeframe = "1D" | "1W" | "1M";

export interface NextScan {
  slot: string;
  name: string;
  when: string;
  at: string;
}

export interface Today {
  scope: Scope | "screen";
  rows: BoardRow[];
  hidden_c: number;
  total: number;
  next_scan?: NextScan | null;
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
  tf: Timeframe;
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
  source: "all" | "hits" | "list";
  watchlist?: string | null;
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
    summary?: string;
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
  /** The live chart's 10:30 (the EP entry time) */
  markers?: { time: number; position: "aboveBar" | "belowBar"; shape: "arrowDown" | "arrowUp"; color: string; text: string }[];
}

/** A table from the API: column names and JSON rows; `total` counts rows before any limit. */
export interface ApiTable {
  columns: string[];
  rows: Row[];
  total: number;
}

export interface StrategyRules {
  labels: string[];
  label: string;
  heading: string;
  rules: string;
  settings: Row[];
  heat: Row[];
  heat_note: string | null;
}

export interface HowTested {
  setups: { setup: string; grades: string; points: string[]; buy: string; stop: string; exit: string }[];
  caption: string;
  write_up: string | null;
}

export interface StudyGrades {
  period: string | null;
  source: string | null;
  sizes: Row[];
  ungraded: string;
  strategies: {
    title: string;
    entry: string;
    stop: string;
    exit: string;
    bands: string;
    base: string;
    history: Row[];
    features: Row[];
  }[];
  costs: string[];
  report: string | null;
}

export interface HistoryQuery {
  period: "2y" | "10y";
  strategies: string[] | null;
  years: number[] | null;
  states: string[];
  ep: { gap_min: number; rvol_min: number; months_min: number; earnings: string; must: string[] } | null;
  split: string;
  one: string | null;
}

export interface HistoryView {
  empty: boolean;
  graded: { summary: ApiTable; by_grade: ApiTable; caption: string };
  caption?: string;
  strategies?: string[];
  years?: number[];
  picked?: string[];
  chosen_years?: number[];
  ep_flags?: string[];
  splits?: string[];
  split?: string;
  count?: number;
  summary?: ApiTable;
  summary_caption?: string;
  compared?: ApiTable;
  one?: string;
  events?: ApiTable;
}

export interface Entries {
  published: boolean;
  caption?: string;
  best?: ApiTable | null;
  exits?: string[];
  exit?: string;
  strategies?: string[];
  strategy?: string;
  by_year?: ApiTable;
  splits?: string[];
  split?: string;
  picked?: string[];
  shown?: string[];
  table?: ApiTable;
}

export interface Regime {
  published: boolean;
  caption?: string;
  mix?: ApiTable;
  strategies?: string[];
  strategy?: string;
  exits?: string[];
  exit?: string;
  entries?: string[];
  entry?: string | null;
  stops?: string[];
  stop?: string | null;
  filters?: ApiTable;
  by_year?: ApiTable;
}

export interface LiveGrades {
  compare: ApiTable | null;
  gaps: ApiTable | null;
  signals: ApiTable | null;
  monthly: string | null;
  caption: string;
}

export interface Jobs {
  grid: ApiTable;
  freshness: ApiTable;
  failures: ApiTable;
  cache: { used_gb: number; limit_gb: number };
}

export interface Status {
  level: "ok" | "warn" | "error";
  text: string;
  details: string[];
}

export type Spark = { time: string; open: number; high: number; low: number; close: number }[];

export interface ScansPage {
  caption: string;
  rows: Row[];
  names: { key: string; label: string }[];
  writable: boolean;
  checkout: boolean;
  note: string | null;
}

export interface ScanForm {
  name: string;
  label: string;
  enabled: boolean;
  action: string;
  push: string | null;
  numbers: { key: string; value: number; kind: "int" | "float" }[];
  flags: { key: string; value: boolean }[];
  push_label: string;
  note: string;
  push_slots: string[];
}

export interface MarketPage {
  empty: boolean;
  tiles?: Tile[];
  ibd?: ApiTable;
  ibd_caption?: string;
  heat?: {
    bands: { band: string; label: string }[];
    now: string;
    count: number;
    band: string;
    table: ApiTable;
    caption: string;
  } | null;
  periods?: string[];
  period?: string;
  groups?: string[];
  picked?: string[];
  sectors?: ApiTable | null;
  sector_caption?: string;
  rotation?: { ticker: string; name: string | null; group: string; x: number; y: number }[];
  back?: string;
  industries?: { top: ApiTable; climbing: ApiTable; caption: string } | null;
  breadth?: ApiTable;
  ratios?: { time: string; ratio_5d: number | null; ratio_10d: number | null }[];
}

export interface DailyNote {
  note_id: string;
  note_date: string;
  text: string;
  tags: string[];
}

export interface DailyNotes {
  notes: DailyNote[];
  tags: string[];
  days: number[];
  caption: string;
  kept: string;
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

// Writes to the data repo, for the automatic Save & push (design review 4 Nov 2026). These POSTs
// only read or compute, or write outside the data repo, so they don't count.
const NOT_WRITES = [
  /^\/api\/ticket$/,
  /^\/api\/screener\/run/,
  /^\/api\/research\//,
  /^\/api\/system\/validation$/,
  /^\/api\/system\/cache/,
  /^\/api\/sync\//,
  /^\/api\/scans\//,
];
type WriteListener = (path: string) => void;
const writeListeners = new Set<WriteListener>();

/** Called after each successful write to the data repo; returns the unsubscribe. */
export function onWrite(listener: WriteListener): () => void {
  writeListeners.add(listener);
  return () => writeListeners.delete(listener);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
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
  const out = (await res.json()) as T;
  if (method !== "GET" && !NOT_WRITES.some((r) => r.test(path))) {
    writeListeners.forEach((l) => l(path));
  }
  return out;
}

const post = <T>(path: string, body: unknown, method = "POST") =>
  request<T>(path, { method, body: JSON.stringify(body) });
const enc = encodeURIComponent;

export const api = {
  today: (scope: Scope, tickers?: string[], screen?: string | null, wl?: string | null) => {
    const q = new URLSearchParams({ scope });
    if (wl) q.set("wl", wl);
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
  strategyRules: (label?: string) =>
    request<StrategyRules>(`/api/research/strategy-rules${label ? `?label=${enc(label)}` : ""}`),
  howTested: () => request<HowTested>("/api/research/how-tested"),
  studyGrades: () => request<StudyGrades>("/api/research/grades"),
  studyNotes: (name?: string) =>
    request<{ names: string[]; name: string | null; text: string | null }>(
      `/api/research/notes${name ? `?name=${enc(name)}` : ""}`,
    ),
  history: (q: HistoryQuery) => post<HistoryView>("/api/research/history", q),
  historyEvent: (p: Record<string, string>) =>
    request<ChartData>(`/api/research/history/event?${new URLSearchParams(p)}`),
  entries: (p: Record<string, string>) =>
    request<Entries>(`/api/research/entries?${new URLSearchParams(p)}`),
  entryTrades: (strategy: string) => request<ApiTable>(`/api/research/entries/trades/${enc(strategy)}`),
  regime: (p: Record<string, string>) => request<Regime>(`/api/research/regime?${new URLSearchParams(p)}`),
  liveGrades: () => request<LiveGrades>("/api/live/grades"),
  liveStats: (minimum?: number) =>
    request<{ minimum: number; total: number; table: ApiTable }>(
      `/api/live/stats${minimum ? `?minimum=${minimum}` : ""}`,
    ),
  liveGraded: () => request<ApiTable>("/api/live/graded"),
  jobs: () => request<Jobs>("/api/system/jobs"),
  clearCache: () => post<{ message: string }>("/api/system/cache/clear", {}),
  github: () => request<{ answered: boolean; timer?: ApiTable; runs?: ApiTable }>("/api/system/github"),
  validationRuns: () =>
    request<{ runs: { id: string; label: string }[]; scans: { id: string; label: string }[] }>(
      "/api/system/validation/runs",
    ),
  validate: (body: { run: string; scan: string; csv_text: string }) =>
    post<ApiTable>("/api/system/validation", body),
  appendValidation: (body: { run: string; scan: string; csv_text: string }) =>
    post<{ message: string }>("/api/system/validation/append", body),
  scans: () => request<ScansPage>("/api/scans"),
  scanForm: (name: string) => request<ScanForm>(`/api/scans/${enc(name)}/form`),
  saveScan: (name: string, values: Record<string, unknown>) =>
    post<{ saved: boolean; message: string; diff: string }>(`/api/scans/${enc(name)}`, { values }),
  commitScan: (name: string) => post<{ ok: boolean; message: string }>(`/api/scans/${enc(name)}/commit`, {}),
  pull: () => post<{ ok: boolean; message: string }>("/api/sync/pull", {}),
  push: () => post<{ ok: boolean; message: string }>("/api/sync/push", {}),
  marketPage: (p: Record<string, string>) =>
    request<MarketPage>(`/api/market/page?${new URLSearchParams(p)}`),
  guide: () => request<{ text: string | null }>("/api/guide"),
  importFills: (name: string, content: string) =>
    post<{ message: string }>("/api/journal/import", { name, content }),
  dailyNotes: (tag: string, days: number) =>
    request<DailyNotes>(`/api/journal/daily-notes?${new URLSearchParams({ ...(tag ? { tag } : {}), days: String(days) })}`),
  addDailyNote: (body: { text: string; day: string; tags: string }) =>
    post<{ note_id: string }>("/api/journal/daily-notes", body),
  editDailyNote: (id: string, body: { text: string; day: string; tags: string }) =>
    post<{ note_id: string }>(`/api/journal/daily-notes/${enc(id)}`, body, "PUT"),
  removeDailyNote: (id: string) =>
    request<{ removed: string }>(`/api/journal/daily-notes/${enc(id)}`, { method: "DELETE" }),
  scanWatchlists: (all: boolean) =>
    request<ScanWatchlists>(`/api/scan-watchlists?include_ended=${all}`),
  market: () => request<Market>("/api/market"),
  status: () => request<Status>("/api/system/status"),
  sparks: (tickers: string[], n = 60) =>
    request<Record<string, Spark>>(`/api/sparks?t=${tickers.map(enc).join(",")}&n=${n}`),
  bars: (ticker: string, tf: Timeframe, indicators: string[], anchor?: string | null) => {
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
