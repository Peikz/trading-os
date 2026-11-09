# Backlog: Backtest module, daily bars (Luk setups vs. current breakout rules)

**Status:** ready for Claude Code
**Repo:** `trading-os` (code), `trading-os-data` (Parquet output)
**Read first:** the repo's `CLAUDE.md` and existing data loaders. Reuse what exists, and adapt the paths below to the current layout.

---

## 1. Goal

Answer two questions with daily-bar history from 2016 to today:

1. **Do Martin Luk's setups, approximated on daily bars, beat the current breakout rule (TRADING-OS.md) on the same universe and dates?**
2. **The three parked Phase 2 questions**, tested on the current breakout rule:
   - Partial size: 1/3 on day 3–5, vs 15% at +3R, vs no partial
   - Stop handling: keep the original order stop, vs raise it to the entry-day low after the close check
   - Sizing: max 3 positions, vs a total open-risk budget of 2%

Results are **relative** (variant A vs. B on identical data). They are not expected returns. This module never places orders or changes live rules.

### Non-goals

- Intraday entries (1m/5m opening-range breaks, AVWAP intraday reclaims). There's no reliable free intraday history.
- Margin, options or CFDs. Gross exposure is capped at 100%.
- Catalyst or news classification for EPs. The volume and gap filters stand in for it.

---

## 2. Data

- **Bars:** daily OHLCV, split- and dividend-adjusted, 2015-06-01 to today. Six months of warm-up are needed for the 126-day lookbacks.
- **Source:** the existing loader if `trading-os` has one. Otherwise use `yfinance`, run from GitHub Actions, and cache to `trading-os-data/bars/daily/` as Parquet partitioned by year.
- **Universe list:** US common stocks (exclude ETFs, ADRs, warrants, preferreds and SPACs where identifiable). Also load **QQQ** for the regime tag.
- **Survivorship:** if delisted tickers can't be included, say so on the first line of every report. Momentum results are biased upward without them. That's acceptable for A-vs-B comparisons, not for absolute returns.
- **Point-in-time filters (all configurable):**
  - price ≥ $5 (alternative: $1, matching the Oct 2026 scan floor)
  - 20-day average volume ≥ 500K shares
  - market cap ≥ $300M if available point-in-time, else skip the filter and log that it was skipped

---

## 3. Shared definitions

All values on day *t* use only data up to and including *t*.

| Name | Definition |
|---|---|
| `ADR%` | mean over 20 days of (high / low − 1) |
| `ADR$` | `ADR%` × close |
| `EMA9`, `EMA21`, `EMA50` | exponential MAs of close |
| `SMA10`, `SMA20`, `SMA50` | simple MAs of close |
| `vol50` | 50-day average volume |
| `perf_n` | close / close *n* days ago − 1, for n = 21, 63, 126 |
| **Leader** | in the top 2% of the universe on `perf_21`, `perf_63` **or** `perf_126` on day *t*, **and** close > `SMA50` |
| **Rising MA** | MA today > MA 5 days ago |
| **AVWAP** | anchored VWAP using typical price (H+L+C)/3 × volume, anchored at the highest-volume up day in the last 63 sessions (catalyst proxy) |
| **Regime tag** | QQQ **up** = close > SMA20 and SMA10 > SMA20; **down** = close < SMA50 and SMA20 < SMA20 five days ago; else **sideways** |
| **Breadth tag** | from the universe: count of stocks with `perf_63` ≥ +25% vs ≤ −25%; **strong** if up/down ≥ 1.5, **weak** if < 1.0, else **neutral** |

---

## 4. Execution model (shared)

- **Decision and fill at the close of day *t*** (matches the 21:35 close check). Config option: fill at the next open instead, to measure close-fill optimism.
- **Breakout baseline only:** buy-stop at pivot × 1.001. Fill = max(open, trigger) if high ≥ trigger, with limit = trigger × 1.01 (no fill if the open is above the limit). If the close check fails the same day, exit at that close (`fail_sold`).
- **Stops:** checked on every following day. If open ≤ stop, exit at **open** (gap-through). Else if low ≤ stop, exit at **stop**. Mirror the logic for shorts.
- **Costs:** slippage 0.10% per side (configurable); commission max($1, 0.08% × notional) (configurable, Saxo-like).
- **Skip rule:** skip any signal whose stop distance is greater than the setup's max stop (given per setup, in ADR).
- **Earnings filter:** off by default (no point-in-time dates). If a dated source exists, add it as an option.

---

## 5. Setups

Each setup is a pure function: `signals(bars_t) -> rows(ticker, date, side, entry, stop)`.

### B0: Breakout (baseline, current TRADING-OS rule)

- **Prior move:** ≥ 30% gain from a low to a high within 21–63 sessions, ending before the base starts.
- **Base:** 10–40 sessions; depth (base high / base low − 1) ≤ 25%; low of the base's second half ≥ low of its first half (higher lows).
- **Trend:** close > `SMA10` > `SMA20`, both rising.
- **Tight right side:** the last 5 sessions' high-low range ≤ 1.5 × `ADR$`; average volume of the last 5 sessions < `vol50`.
- **Pivot:** the base high.
- **Close check on the trigger day:** close > pivot; close in the upper half of the day's range; volume > `vol50`.
- **Stop:** max(lowest low of the last 10 sessions before the trigger, pivot − 1 × `ADR$`).
- **Max stop:** 1 ADR (enforced by the stop rule).

### L1: Pullback to rising 9/21 EMA and AVWAP

- Leader; `EMA9` > `EMA21` > `EMA50`; `EMA21` rising.
- Prior move: ≥ 30% within the last 63 sessions, with the high made 3–7 sessions ago.
- Pullback: during those 3–7 sessions, the low comes within 0.5 × `ADR$` of `EMA9`, `EMA21` or AVWAP. No close below `EMA50`.
- **Trigger:** close > `EMA9` **and** close > the prior day's high.
- **Stop:** lowest low of the pullback. **Max stop:** 1 ADR.

### L2: Undercut and reclaim

- Leader; close > `SMA50`.
- **Undercut:** low on *t* < lowest low of the prior 10 sessions (call it `level`).
- **Reclaim:** close > `level`; close in the upper half of the day's range; close > open.
- **Stop:** low of *t*. **Max stop:** 1 ADR.

### L3: Catalyst gap-up (EP)

- Gap: open ≥ prior close × 1.10.
- Volume ≥ 3 × `vol50` and ≥ 300K shares.
- **Neglect:** `perf_126` of the prior day < +30% (configurable).
- Close > open; close in the upper half of the day's range.
- **Stop:** low of *t*. **Max stop:** 1.5 × the **pre-gap** ADR.
- No leader requirement.

### S1: Weak bounce into declining 9/21 EMA (short, information only)

- Former leader: was a Leader on any day in the last 63 sessions.
- **Breakdown:** within the last 10 sessions, a close below `EMA21` on volume ≥ 1.5 × `vol50`.
- **Bounce:** 2–4 sessions up from the post-breakdown low, with average bounce volume < `vol50`; the high comes within 0.5 × `ADR$` of `EMA9` or `EMA21`; `EMA21` falling.
- **Trigger:** close < the prior day's low.
- **Stop:** highest high of the bounce. **Max stop:** 1 ADR.
- Assume borrow is always available, and flag that assumption in the report.

### S2: Parabolic short (information only, weakest proxy)

- Close ≥ `EMA9` + 3 × `ADR$`; ≥ 5 up closes in the last 7 sessions; `perf_21` ≥ +50% (configurable; +30% for market cap > $10B if available).
- **Trigger:** close < open **and** close < prior close (first failure day).
- **Stop:** high of *t*. **Max stop:** 1.5 ADR.

---

## 6. Exit variants

Longs shown; shorts mirror them (MA crosses invert).

| ID | Partial | After the partial | Trail (on the daily close) |
|---|---|---|---|
| **E0** (current rule) | sell 1/3 on day 3–5 if close > entry | stop to breakeven | exit when close < `SMA10` |
| **E1** (Luk) | sell 15% at the first close ≥ +3R | stop to breakeven | exit when close < `EMA9` |
| **E2** (no partial) | none | none | exit when close < `SMA10` |
| **E3** (Luk, slow trend) | as E1 | as E1 | exit when close < `EMA21` |

Stop variants (crossed with every exit):

- **K0 keep:** the initial stop stays until the partial moves it to breakeven.
- **K1 raise:** after the entry day, raise the stop to the entry-day low if that's higher (current rule).

For every closed trade, also store **`r_no_partial`**: the R the trade would have made with no partial and the same trail. This answers Phase 2 item 3 directly.

---

## 7. Portfolio simulation

Run per setup, and also for B0 + L1 + L2 + L3 combined (longs). Shorts run separately and are never mixed into the long equity curve.

- Starting equity: 100,000.
- Risk per trade: **0.25%** of current equity (configurable: 0.5%, 1%).
- Shares = risk $ / (entry − stop); cap the position at **25% of equity**; gross exposure ≤ 100% (no margin).
- **Sizing variants:**
  - **P0:** max 3 open positions
  - **P1:** total open risk ≤ 2% of equity, where a position at breakeven counts as 0 risk; max 8 positions
- **When signals exceed free slots:** rank by `perf_63` descending (configurable).
- **Circuit breaker (optional flag, default on):** after 5 losses in a row, halve risk until a win of ≥ +2R.

---

## 8. Metrics

### Trade level, per setup × exit × stop variant

- n trades, win rate, average win R, average loss R, **expectancy R**, profit factor
- median holding days for winners and for losers
- % of trades stopped out on day 1
- max consecutive losses
- **share of net R from the top 10 trades**
- **shakeout rate:** % of stop-outs where a close above entry occurred within the next 3 sessions (Phase 2 item 2)
- mean `r_no_partial` − mean actual R (Phase 2 item 3)

### Portfolio level, per sizing variant

- CAGR, max drawdown, worst month, % positive months, average gross exposure

### Breakdowns

- by year
- by regime tag (QQQ up / sideways / down)
- by breadth tag

### Market-signal check (from S1)

- weekly count of S1 signals vs. the regime and breadth tags. Does a spike in weak-bounce shorts line up with down or weak periods?

---

## 9. Output

- `trading-os-data/backtests/<run_id>/trades.parquet`: one row per trade, with all variant keys, entry/exit dates and prices, R, `r_no_partial`, hold days, `exit_reason` (`stop`, `gap_stop`, `fail_sold`, `trail`, `breakeven`), regime, breadth
- `.../equity.parquet`: daily equity and gross exposure per portfolio variant
- `.../summary.parquet`: the section 8 metrics, one row per variant combination
- `.../report.md`: survivorship line first, then a summary table, then:
  - B0 vs L1 vs L2 vs L3 on expectancy and top-10 share
  - Phase 2 answers (E0 vs E1 vs E2; K0 vs K1; P0 vs P1)
  - the S1 market-signal check
- `.../spot_check.csv`: 20 random trades (ticker, date, entry, stop, exit) for manual TradingView Bar Replay review
- `config.yaml` copied into the run folder, so every result is reproducible

Example query to support: `duckdb -c "select setup, exit_variant, stop_variant, expectancy_r from 'summary.parquet' order by expectancy_r desc"`

---

## 10. Build order (one PR each)

1. **Data:** daily bars cached in Parquet, universe filter, QQQ. *Done when* row counts per year are logged and a 3-ticker sample matches Yahoo closes.
2. **Indicators:** section 3, with unit tests on a hand-computed fixture. *Done when* the tests pass, including a **no-lookahead test**: shifting future bars doesn't change any value on day *t*.
3. **Setups:** B0 first, then L1, L2, L3, S1, S2, each with a fixture test on one known example. *Done when* every setup emits signals on its fixture.
4. **Trade engine:** execution, stops and exits (sections 4 and 6). *Done when* tests cover gap-through stops, `fail_sold`, partial plus breakeven, and `r_no_partial`.
5. **Portfolio simulation:** section 7.
6. **Metrics and report:** sections 8 and 9.
7. **GitHub Actions:** a manual `workflow_dispatch` that runs a config and commits the output to `trading-os-data`.

---

## 11. Guardrails

- Config-driven: every threshold in this spec lives in `config.yaml`, not in code.
- Don't tune parameters to maximise results. Run the spec values first, then at most one sensitivity sweep (±20% on gap %, prior move % and max stop) to check robustness.
- The report states the limits plainly: daily proxies of intraday setups, survivorship, no news filter, assumed borrow.
- Results go to the Phase 2 review. Nothing here changes live trading rules automatically.

---

## 12. Adaptations to this repo (step 1, 9 Nov 2026)

- **Source:** the existing `bars-alpaca` release in the data repo (Alpaca daily bars, split- and
  dividend-adjusted, one file per year, delisted stocks included), read through
  `remote_data.fetch` or a local folder. No yfinance and no second copy under `bars/daily/`: the
  release already is the year-partitioned Parquet cache, and 350 MB doesn't belong in git.
- **Survivorship:** delisted tickers are included, so the report's first line says so.
- **Start:** the release begins 2016-01-04, not 2015-06-01. The first 126 sessions are warm-up,
  so signals start in July 2016 unless a 2015 file is added (Questions for Emil).
- **Security types:** the Massive ticker table (`data/ep_enrich/tickers.parquet`) drops ETFs,
  ETNs, funds, indexes, ADRs, warrants, units, rights and preferreds; `audit.ordinary_ticker`
  drops warrant/unit/right symbols it doesn't list. SPACs: names matching the config patterns
  ("Acquisition Corp" etc.). The table is today's snapshot, so a reused ticker gets its current type.
- **Market cap:** no point-in-time history in the bars, so the filter is skipped and logged.
- **Config:** `config/backtest.yaml`, checked key by key like `scans.yaml`.
