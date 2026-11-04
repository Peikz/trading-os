// Plain words in labels (design review 4 Nov 2026): "Daily range" instead of "ADR %", with the
// abbreviation kept in a tooltip. Covers the key-stat labels, the Screener's field labels and
// the API tables' column names; anything not listed is shown as it comes, underscores spaced.

/** label -> [plain words, the original term for the tooltip] */
const WORDS: Record<string, [string, string?]> = {
  // Key stats under the chart (trading_os.board_data.key_stats)
  "Mkt cap": ["Market cap"],
  ADR: ["Daily range", "ADR %: average daily range over 20 days"],
  "$ vol 20d": ["$ volume", "Average dollar volume over 20 days"],
  "From 52w high": ["From the high", "From the 52-week high"],
  RS: ["RS", "Relative strength percentile against all US stocks (1-99)"],
  // Screener fields (trading_os.screens.FIELDS)
  "ADR % (20d)": ["Daily range %", "ADR %: average daily range over 20 days"],
  "Avg $ volume 20d": ["$ volume (20-day avg)", "Average dollar volume over 20 days"],
  "Avg volume 20d": ["Volume (20-day avg)", "Average volume over 20 days"],
  "RS percentile (1-99)": ["RS", "Relative strength percentile against all US stocks (1-99)"],
  "Relative volume (50d)": ["Relative volume", "Volume against its 50-day average (RVOL)"],
  "Revenue TTM": ["Revenue, last 12 months", "Revenue TTM"],
  "Revenue growth q/q-y %": ["Revenue growth %", "Quarter against the same quarter a year ago"],
  "EPS growth q/q-y %": ["Earnings growth %", "EPS, quarter against the same quarter a year ago"],
  "10-day range in ADRs (tightness)": ["10-day range (tightness)", "10-day range in ADRs"],
  "Distance to MA10 (ADRs)": ["Distance to the 10-day line", "In ADRs"],
  // API table columns
  ticker: ["Ticker"],
  close: ["Price"],
  chg_pct: ["Change %"],
  rvol50: ["Relative volume", "RVOL against the 50-day average"],
  adr20_pct: ["Daily range %", "ADR %: average daily range over 20 days"],
  avg_dollar_volume_20d: ["$ volume", "Average dollar volume over 20 days"],
  market_cap: ["Market cap"],
  rs_pct: ["RS", "Relative strength percentile (1-99)"],
  pct_from_52w_high: ["From the high %", "From the 52-week high"],
  ret_22: ["1 month %"],
  ret_63: ["3 months %"],
  above_ma50: ["Over the 50-day line", "Above MA50"],
  above_ma200: ["Over the 200-day line", "Above MA200"],
  to_pivot_pct: ["To the pivot %"],
  earnings_in_sessions: ["Earnings in (sessions)"],
  in_scans: ["In scans"],
  industry: ["Industry"],
  note: ["Note"],
  direction: ["Side"],
  entry_date: ["Entry date"],
  entry_avg: ["Entry"],
  exit_date: ["Exit date"],
  exit_avg: ["Exit"],
  open_quantity: ["Shares"],
  quantity: ["Shares"],
  order_stop: ["Stop"],
  last_close: ["Last close"],
  last_date: ["Last date"],
  open_pnl: ["Open P&L"],
  open_r: ["Open R"],
  at_risk_usd: ["At risk $"],
  at_risk_pct: ["At risk %"],
  setup: ["Setup"],
  status: ["Status"],
  session_date: ["Session"],
  entry: ["Entry"],
  stop: ["Stop"],
  shares: ["Shares"],
  risk_usd: ["Risk $"],
  fill_date: ["Fill date"],
  fill_price: ["Fill price"],
  slippage_pct: ["Slippage %"],
  slippage_r: ["Slippage R"],
  plan_id: ["Plan id"],
  pnl: ["P&L"],
  r_multiple: ["R"],
  mfe_r: ["Best R", "MFE: the best open R while held"],
  mae_r: ["Worst R", "MAE: the worst open R while held"],
  exit_efficiency: ["Exit efficiency"],
  sessions_held: ["Sessions held"],
  signal_scan: ["Scan"],
  grade: ["Grade"],
  grade_score: ["Score"],
  tier: ["Tier"],
  added_date: ["Added"],
  status_date: ["Status since"],
  reason: ["Reason"],
  fired_ts: ["Fired"],
  kind: ["Kind"],
  level: ["Price"],
  price: ["Price"],
  rule: ["Rule"],
  held: ["Held"],
  hold: ["Hold"],
  r_now: ["R now"],
  earnings: ["Earnings"],
  action: ["Plan says"],
};

export function plain(label: string): { text: string; title?: string } {
  const hit = WORDS[label];
  if (hit) return { text: hit[0], title: hit[1] ?? (hit[0] !== label ? label : undefined) };
  if (/^[a-z0-9_]+$/.test(label) && label.includes("_")) {
    const spaced = label.replace(/_/g, " ");
    return { text: spaced[0].toUpperCase() + spaced.slice(1), title: label };
  }
  return { text: label };
}

/** Text without its leading pictographs (the package writes some lines with emoji). */
export function stripIcons(text: string): string {
  return text.replace(/^[\p{Extended_Pictographic}️‍\s]+/u, "").trim();
}
