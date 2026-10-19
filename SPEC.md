# Trading OS — Specification

Personal scanning, data-collection and trade-tracking system for momentum trading of US equities
(Kullamägi / Qullamaggie setups + Stockbee scans). Owner: Emil.

---

## 1. Principles (non-negotiable)

1. **No AI at runtime.** Scans are deterministic Python run by GitHub Actions. Same input → same output.
2. **Collect broadly, trade narrowly.** Every scan is logged. Only EP and Breakout produce trade alerts.
3. **Point-in-time data.** Every row is stored as it was known at run time. Never recompute or overwrite historical rows with later data. Outcomes go in a separate table.
4. **Screens find, the human grades.** Code never assigns a trade grade.
5. **One config file.** All thresholds live in `config/scans.yaml`. No magic numbers in code.
6. **Validate before trusting.** Phase 1 runs side by side with manual TradingView screens for 2 weeks.

---

## 2. Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Screener data | `tradingview-screener` (shner-elmo, MIT) — no login, 15-min delayed |
| Price history | Massive (formerly Polygon.io) free tier — grouped daily bars, `adjusted=true` |
| Storage | Parquet files in the repo under `data/` |
| Query | DuckDB |
| Scheduler/runner | GitHub Actions (private repo) |
| Notifications | ntfy.sh (topic name stored as a GitHub Secret) |
| Exports | Daily `.xlsx` of candidates for human viewing |
| Market calendar | `exchange_calendars` or `pandas_market_calendars` (skip US holidays) |

Secrets (GitHub Secrets): `MASSIVE_API_KEY`, `NTFY_TOPIC`, `DATA_REPO_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`. No TradingView credentials, ever.

### Two-repo setup

| Repo | Visibility | Contains |
|---|---|---|
| `trading-os` | **Public** (unlimited Actions minutes) | Code, `config/`, tests, workflows, docs, SPEC/CLAUDE/BACKLOG |
| `trading-os-data` | **Private** | `data/` (Parquet, exports, watchlists, outcomes, journal), `docs/validation.md` |

- Workflows run in `trading-os`, check out `trading-os-data` with `DATA_REPO_TOKEN` (fine-grained PAT, contents read/write on the data repo only), write results there, commit and push.
- **Actions logs in the public repo are public.** Jobs must never print tickers, scan results, prices, P&L or journal content to stdout/stderr. Log only counts and status (e.g. `EP-Day: 7 hits, saved`).
- Notifications go to ntfy directly from the job (topic is a secret), never via logs.
- Validation notes that list tickers live in the data repo, not the public one.

---

## 3. Schedules

All times are local Copenhagen time. Scripts must check the actual New York time and skip
non-trading days, because EU and US daylight-saving changes happen on different dates.

| Job | Target time | New York time | Contents |
|---|---|---|---|
| `premarket` | 13:30 CET | 07:30 ET | EP-PM, EP9M early warning, watchlist gappers |
| `intraday` (Emil, 19 Oct 2026) | 16:15 and 18:00 CET | 10:15 and 12:00 ET | EP9M pace (§6.1b); candidates only, no universe snapshot |
| `eod` | 22:20 CET | 16:20 ET | All end-of-day scans, universe snapshot, breadth |
| `weekly` | Sunday 18:00 CET | — | Qullamaggie 1/3/6M gainers, growth buckets, tight bases, official Market Light count |
| `outcomes` | daily after `eod` | — | Fill outcome horizons for past signals (Phase 3) |

Implementation: schedule each workflow with two UTC crons (one per DST state) plus a guard in the
script that exits unless New York time is inside the target window (premarket 07:15–07:55 ET,
eod 16:15–17:30 ET). GitHub cron can start 5–15 min late; schedule early, let the guard decide.
All workflows also get `workflow_dispatch` for manual runs.

---

## 4. Universe tiers

Excluded always: OTC, ETFs/ETNs, warrants, rights, units, preferred shares.

| | Logged tier (model data) | Alert tier (trade candidates) |
|---|---|---|
| Price | ≥ $0.50 | ≥ $1.00 |
| Market cap | ≥ $50M | ≥ $50M |
| 20-day avg volume (shares) | — | ≥ 500K |
| 20-day avg dollar volume | ≥ $500K | — |
| Signal-day dollar volume (EOD signals) | — | ≥ $5M (SWVL guard) |

---

## 5. Metric definitions

| Metric | Definition |
|---|---|
| ADR(20) % | mean over 20 days of (high / low − 1) × 100 |
| ADR $ | ADR% × close / 100 |
| RVOL | today's volume / 50-day average volume (excluding today) |
| Gap % | open / prior close − 1 |
| Change % | close / prior close − 1 |
| Dollar volume | close × volume |
| Close location | (close − low) / (high − low) |
| Returns | 22 / 63 / 126 trading-day close-to-close |
| MA rising | MA today > MA 5 trading days ago |
| Distance from MA10 (ADR) | (close − MA10) / ADR $ |
| Consecutive up/down days | count of consecutive closes above/below prior close |

---

## 6. Scans

Status: **(yours)** = from the owner's TRADING-OS rules. **(proposed)** = default, confirm in validation.
Action: **Push** = saved + phone notification. **Log** = saved only. All scans are always saved.

### 6.1 Pre-market (13:30 CET)

| Scan | Filters | Phase | Action |
|---|---|---|---|
| EP-PM (yours) | Pre-market change ≥ 10%, price ≥ $1, pre-market volume ≥ 50K, market cap ≥ $50M; earnings/news flag as column | 1 | Push |
| EP9M early warning (proposed) | Pre-market volume ≥ 500K, gap ≥ 4% | 1 | Push |
| Watchlist gappers (proposed) | BO-Watch / EP-Watch names with pre-market gap ≥ 2% | 1 | Push |
| Breadth + Market Light (Emil, 19 Oct 2026) | Market Light set at the last close (it governs today's orders), that close's breadth line, pre-market movers (pre-market change ≥ +4% / ≤ −4% in the breadth universe) and QQQ's pre-market change | 1 | Push (top of message) |

### 6.1b During the session (16:15 and 18:00 CET)

| Scan | Filters | Phase | Action |
|---|---|---|---|
| EP9M pace (Emil, 19 Oct 2026; rule proposed) | EP9M's rule (§6.2) on the day's projected volume: change ≥ +4% and volume so far or pace ≥ 9M shares. Pace = TradingView's relative volume at this time of day (5-minute bars) × normal daily volume (today excluded), never below the volume so far. A name pushes once per session: the 12:00 check skips names sent at 10:15 | 1 | Push |

### 6.2 End of day (22:20 CET)

| Scan | Filters | Phase | Action |
|---|---|---|---|
| EP-Day (yours) | Gap ≥ 10%, RVOL ≥ 3, volume ≥ 300K, price ≥ $1, mcap ≥ $50M | 1 | Push |
| EP-AH (yours, toggle, default OFF) | Post-market change ≥ 8%, price ≥ $1, mcap ≥ $50M, post-market volume ≥ 50K | 1 | Push |
| EP9M (Stockbee) | Volume ≥ 9M shares, change ≥ +4%. No MA filter (MA position stored as columns) | 1 | Push |
| Momentum Burst up (Stockbee) | Change ≥ +4%, volume > prior day, volume ≥ 100K, close location ≥ 0.70 | 1 | Log |
| Momentum Burst down (Stockbee) | Change ≤ −4%, volume > prior day, volume ≥ 100K | 1 | Log |
| Parabolic Short (Kullamägi) | ≥ 50% gain in ≤ 10 days (mcap ≥ $1B) or ≥ 200% (mcap < $1B); ≥ 3 consecutive up days; distance from MA10 in ADR stored | 1 | Log |
| Parabolic Long (Kullamägi) | ≥ 30% drop in ≤ 10 days; ≥ 3 consecutive down days; distance below MA10 in ADR stored | 1 | Log |
| Breadth (Stockbee Market Monitor style) | MB up count, MB down count, 5- and 10-day up/down ratios, stocks up ≥ 25% in a quarter vs down ≥ 25% in a quarter, % above MA20 / MA50 / MA40. Universe: price ≥ $5, volume ≥ 100K | 1 | Push (one line) |
| Market Light (yours) | See §6.5. Computed daily; the scan count input only changes on Sundays | 1 | Push (one line) |
| Universe snapshot | Every stock in the logged tier with all metrics | 1 | Log |
| Breakout B1–B4 (yours) | See 6.4 | 2 | Push (BO-Watch) |
| Breakout B5 trigger (yours) | See 6.4 | 2 | Push |

### 6.3 Weekly (Sunday)

| Scan | Filters | Phase | Action |
|---|---|---|---|
| Qullamaggie gainers | Top 2% by 22-, 63- and 126-day return; ADR ≥ 4%; 20-day avg dollar volume ≥ $10M; price > $5. One merged list tagged with which list(s) each hit | 1 | Push |
| Growth Bucket 1 | Price > $10, avg volume > 100K, quarterly sales growth YoY ≥ 40% (last 2 quarters if available), annual revenue > $25M | 1 | Push (list) |
| Growth Bucket 2 | Price > $10, avg volume > 200K, EPS growth YoY ≥ 40% and sales growth ≥ 20% (last 2 quarters if available) | 1 | Push (list) |
| Tight bases (HTB + Ants merged) | Within 15% of 52-week high, ADR ≥ 4%, above MA50, 10-day range < 1.5 × ADR $, 10-day avg volume < 50-day avg volume | 2 | Watchlist |
| CATS score | Ranking column, not a filter: growth bucket hit + recent MB/EP + RVOL trend − extension penalty | 2 | Column |

If "previous quarter" growth is not available from TradingView fields, Phase 1 uses latest quarter
only and records that in the row (`growth_quarters_checked`).

### 6.4 Breakout criteria (B1–B5, from TRADING-OS.md rules card)

| | Criterion | Rule |
|---|---|---|
| B1 | Prior move | Up ≥ 30% within the last 1–3 months (22–63 trading days), fast (days to weeks) |
| B2 | Base | 2–8 weeks (10–40 trading days); higher lows; contracting swings (each pullback depth ≤ 0.85 × the previous); quiet volume |
| B3 | Trend | Close riding a rising MA10 and MA20, ideally MA10 > MA20 > MA50 |
| B4 | Tight right side | Last 5–10 days of the base narrow and quiet: range < ADR-based threshold, volume below 50-day average |
| B5 | Trigger | Close > pivot with range expansion (day range > ADR $) and volume (RVOL ≥ 1.5), checked at the close |

**Order stop is a rule, not a criterion:** `order_stop = max(last_contraction_low, pivot − 1 × ADR $)`,
so `risk_adr = (pivot − order_stop) / ADR $ ≤ 1`. Stored for every breakout candidate.

`pivot` = highest high within the base. B2 and B4 are heuristics: all parameters in config, all
intermediate values (base length, contraction depths, right-side range, pivot) stored so the human can audit.
Code computes B1–B5 as booleans; **code never assigns the A/B/C grade** (A = all 5, B = 4, C ≤ 3 is the human's call).
Reference implementation for contraction detection: `phuazz/vcp-screener` (check license before copying).

### 6.5 Market Light (from TRADING-OS.md — owner's rules, do not change)

**1. QQQ trend** (daily, 10/20/50 SMA), checked in this order:
- **up** = close > SMA20 AND SMA10 > SMA20
- **down** = close < SMA50 AND SMA20 lower than 5 sessions ago
- **sideways** = anything else

**2. Breadth** (Stockbee Market Monitor style, computed from the universe):
- **strong** = 10-day up/down ratio ≥ 1.5 AND more stocks up ≥ 25% in a quarter than down ≥ 25%
- **weak** = 10-day ratio < 1.0 AND more stocks down ≥ 25% in a quarter than up
- **neutral** = anything else. A 5-day ratio > 2 (breadth thrust) lifts weak to neutral.

**3. Scan count** (Sunday): Country USA, price > $5, average volume > 500K, quarter performance ≥ +50%,
price above SMA20. Only the count matters. **This screen must not change** — the thresholds were written for it.

**4. The light** — first matching row wins:

| Light | When | New entries |
|---|---|---|
| STOP | QQQ down AND breadth weak, OR scan count < 5 | None |
| RED | QQQ down OR breadth weak, OR scan count < 15 | A grades only, half risk |
| GREEN | QQQ up AND breadth not weak AND scan count ≥ 50 | Normal |
| YELLOW | anything else | A and B grades only |

The light read in the evening covers the next day's orders. Store `qqq_trend`, `breadth_state`,
`scan_count`, `light` daily in `breadth.parquet`. Our computed breadth is a reconstruction of Stockbee's
Market Monitor; log Stockbee's published numbers alongside when available so the two can be compared.

---

## 7. Data model (Parquet, append-only)

All paths below live in the private `trading-os-data` repo.

```
data/
├── universe/YYYY/YYYY-MM-DD_{slot}.parquet     # slot = pm | eod
├── candidates/YYYY/YYYY-MM-DD_{slot}.parquet
├── breadth/breadth.parquet                     # one row per day
├── watchlists/bo_watch.parquet, ep_watch.parquet
├── outcomes/YYYY/YYYY-MM-DD.parquet            # Phase 3
├── journal/journal.parquet                     # Phase 4
└── exports/YYYY-MM-DD_{slot}.xlsx
```

**universe** — one row per ticker per run: `run_ts, slot, ticker, exchange, sector, industry, open, high,
low, close, volume, dollar_volume, market_cap, float_shares, adr20_pct, adr20_usd, rvol50, gap_pct,
chg_pct, close_loc, ret_22, ret_63, ret_126, ma10, ma20, ma50, ma200, ma10_rising, ma20_rising,
dist_ma10_adr, consec_up, consec_down, high_52w, pct_from_52w_high, earnings_date, rev_growth_q,
eps_growth_q, pm_change_pct, pm_volume, ah_change_pct, ah_volume, tier, data_source`.

**candidates** — one row per scan hit: `signal_id, run_ts, slot, scan, ticker, rank, tier (log|alert),
pushed (bool), pivot, order_stop, risk_adr, base_len, contraction_depths, b1..b5 (bool), notes`.
`signal_id` = stable hash of (date, slot, scan, ticker).

**outcomes** (Phase 3) — `signal_id, horizon (5|10|20|60), max_gain_pct, max_drawdown_pct,
close_ret_pct, hit_order_stop (bool), r_hypothetical, computed_ts`. Never edits candidates.

**watchlists** — `ticker, list, added_date, source_signal_id, status (active|triggered|expired), status_date`.
EP gappers enter EP-Watch; when B1–B4 pass, they move to BO-Watch.

---

## 8. Notifications (ntfy.sh)

- One message per job, not per ticker.
- Format: title `Trading OS · EOD 2026-10-19`, body = breadth line, then each pushing scan with up to
  10 tickers: `TICKER  +14.2%  RVOL 5.1  $82M  [earnings]`.
- If a job fails, push a short failure message with a link to the Actions run.

---

## 9. Phases and acceptance criteria

| Phase | Scope | Done when |
|---|---|---|
| 1 | Repo, config, pre-market + EOD + weekly scans from the scan tables above (excluding Breakout B1–B5, tight bases, CATS), Parquet storage, xlsx export, ntfy, Actions with DST/holiday guards | 10 consecutive trading days run without manual intervention; EP-Day and gainers lists match manual TradingView screens (differences explained in `docs/validation.md`) |
| 2 | Massive history backfill (2 years), metrics module, Breakout B1–B5, watchlists, tight bases, CATS, breadth extensions | Breakout candidates audited by hand on 20 random hits; B4 stops correct |
| 3 | Outcomes job (5/10/20/60 days), before-shot chart PNGs, write Breakout Log rows to EPStudyDatabase (Google Sheet via service account) | Outcomes filled for all signals ≥ 5 days old |
| 4 | Saxo fills (OpenAPI or CSV import) → journal with R-multiples; Power BI model over Parquet/DuckDB | One month of real trades reconciled |
| 5 | Static dashboard (GitHub Pages or artifact) | After pipeline is stable ≥ 1 month |
| 6 | Statistics, then model | ≥ 6–12 months of data |

---

## 10. Non-goals

- No automated order placement.
- No AI/LLM calls in any scheduled job.
- No grading of setups by code.
- No new setups beyond this spec without the owner's explicit decision.

---

## 11. Open questions (resolve during Phase 1)

1. Exact TradingView field names for pre-/post-market change and volume, earnings date, revenue/EPS growth (verify against the package's field docs).
2. Whether previous-quarter growth is available.
3. ~~Market Light mapping~~ — resolved, see §6.5.
5. ~~Universe floor conflict~~ — resolved 18 Oct 2026 by Emil: alert tier = price ≥ $1 and 20-day average
   volume ≥ 500K shares (replaces both TRADING-OS.md's $5 floor and the earlier $1M dollar-volume rule).
   EP screens (EP-PM, EP-Day, EP-AH) also lowered to price ≥ $1 and market cap ≥ $50M.
   Exception: the Market Light count screen keeps price > $5 (its thresholds were calibrated on that exact screen).
4. Massive free-tier behaviour for the 2-year backfill (5 calls/min → ~2 hours, run once).
6. ~~Volume windows in Phase 1~~ — resolved 18 Oct 2026 by Emil: TradingView exposes 10/30/60/90-day
   average volume only. Until Massive history exists (Phase 2), RVOL = volume / 60-day average volume
   and every "20-day average" uses the 30-day field. TradingView's averages include today (verified
   18 Oct, see `docs/fields.md`), so RVOL removes it to keep §5's "excluding today":
   RVOL = volume / ((60 × avg60 − volume) / 59). Once a stock has enough daily history (Massive
   backfill, or enough stored EOD sessions), the exact §5 definitions replace these proxies row by
   row (RVOL, ADR, returns, 20-day averages); the basis columns record which was used. TradingView's own 10-day relative volume is stored
   as an extra column. Each row records the basis used (`rvol_basis`).
7. ~~Which EP hits push~~ — resolved 18 Oct 2026 by Emil: every hit is saved; only hits that also pass
   the alert tier (§4) are pushed. The others are saved with `tier=log`, `pushed=false`.
8. ~~ADRs~~ — resolved 18 Oct 2026 by Emil: ADRs stay in the universe, with the symbol type stored as a column.
9. ~~Breadth pre-market~~ — decided 19 Oct 2026 by Emil: breadth also runs pre-market (see §6.1). The
   light itself is still set at the close (§6.5); pre-market adds the movers count and QQQ's pre-market change.
10. ~~Early EP9M~~ — decided 19 Oct 2026 by Emil: EP9M names also during the session, at 10:15 and 12:00 New
   York (§6.1b), so they can be acted on before the close. TradingView's data is 15 minutes delayed, so a
   check sees the market about 15 minutes earlier. Intraday runs store candidates (with the pace inputs),
   not a universe snapshot, to keep the data repo's growth flat. Outcomes enter at the price the run saw.

## 12. References

- Qullamaggie: https://qullamaggie.com — 1/3/6M gainer scans, Breakout, EP, Parabolic
- Stockbee: https://stockbee.blogspot.com — Momentum Burst, EP9M, Market Monitor
- `shner-elmo/TradingView-Screener`, `dcimring/stockbee-dashboard`, `phuazz/vcp-screener`,
  `js8m226wkn-dotcom/qullamaggie-scanner`, `VladPetrariu/Qullamaggie-breakout-scanner`
