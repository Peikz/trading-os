# Trading OS — Specification

Personal scanning, data-collection and trade-tracking system for momentum trading of US equities
(Kullamägi / Qullamaggie setups + Stockbee scans). Owner: Emil.

---

## 1. Principles (non-negotiable)

1. **No AI at runtime.** Scans are deterministic Python run by GitHub Actions. Same input → same output.
2. **Collect broadly, trade narrowly.** Every scan is logged. Only EP and Breakout produce trade alerts.
3. **Point-in-time data.** Every row is stored as it was known at run time. Never recompute or overwrite historical rows with later data. Outcomes go in a separate table.
4. **Screens find, the human decides.** Code may show a *study grade* (A+/A/B/C): how setups like
   this one did in the history of the owner's own rules (§11.17), labelled as such. Code never makes
   the trade decision, and the journal grade stays the human's.
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
| `intraday` (Emil, 19 Oct 2026) | 16:15 and 18:00 CET | 10:15 and 12:00 ET | EP9M pace, EP 10:30 at the 10:15 check (§6.1b); candidates only, no universe snapshot |
| `intraday` close check (Emil, 20 Oct 2026; off since 21 Oct) | 21:45 CET | 15:45 ET | EP close (§6.1b). Not scheduled since 21 Oct 2026; runs by hand only |
| `eod` | 22:20 CET | 16:20 ET | All end-of-day scans, universe snapshot, breadth |
| `intraday` after-hours check (Emil, 21 Oct 2026) | 22:50 CET | 16:50 ET | EP-AH (§6.1b): earnings movers after the close, graded (§11.17), bought before Saxo's extended hours end at 17:00 ET |
| `weekly` | Sunday 18:00 CET | — | Qullamaggie 1/3/6M gainers, growth buckets, tight bases, official Market Light count |
| `outcomes` | daily after `eod` | — | Fill outcome horizons for past signals (Phase 3) |
| `alerts` (Emil, 22 Oct 2026; GitHub Actions, timer at 09:25 and 12:45 ET) | every minute, 15:30–22:00 CET | 09:30–16:00 ET | Price alerts: last close's BO-Watch and MA-surf pivots, open positions' stops, alerts added on the dashboard; Alpaca IEX real-time prices; one ntfy push per event (`alerts.py`, `scripts/alert_watch.py`). Never places orders |
| `live-check` (Emil, 21 Oct 2026) | 1st of the month, 15:00 CET | — | Live A+ / A signals played out by their study plan against the history each grade carried, and Emil's trades against the plan (`docs/live-tracking/` in the data repo, one push) |

Implementation: schedule each workflow with two UTC crons (one per DST state) plus a guard in the
script that exits unless New York time is inside the target window (premarket 07:15–07:55 ET,
eod 16:15–23:59 ET, widened by Emil 20 Oct 2026 after GitHub ran crons 5 h late; a third, later
EOD cron is the fallback). GitHub cron can start minutes to hours late; schedule early, let the guard
decide.
All workflows also get `workflow_dispatch` for manual runs.

Timer (Emil, 20 Oct 2026): GitHub started the scheduled runs 2½–6½ h late on 19–20 Oct, so
pre-market and intraday never ran in their windows. A cron-job.org account now starts each
timed workflow through `workflow_dispatch` (input `timer`) at its New York time, with a second
start for each scan in case the first run failed (`trading_os/timer.py`,
`scripts/timer_setup.py`). Timer runs count as scheduled (`run_kind`). GitHub's crons stay as
the backup; the guards make duplicate starts harmless.

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
| EP close (Emil, 20 Oct 2026; off since 21 Oct) | EP-Day's rule (§6.2) on the live data at 15:45 New York (TradingView sees about 15:30). Switched off on 21 Oct 2026: in the 2022–26 portfolio runs the close was the weakest EP entry, so the EP buy moved to 10:30 and after hours | 1 | Off |
| EP 10:30 (Emil, 21 Oct 2026) | At the 10:15 check (TradingView sees about 10:00): opening gap ≥ 10%, price ≥ $1, mcap ≥ $50M, alert tier. The grading study's 10:30 entry needs only the opening gap. Graded by the EP quality count (§11.17); bought around 10:30 | 1 | Push |
| EP-AH (yours; live since 21 Oct 2026) | At 16:50 New York (TradingView sees about 16:35): post-market change ≥ 8%, post-market volume ≥ 50K, price ≥ $1, mcap ≥ $50M, and an earnings release that day (TradingView's last or next earnings date). Graded by the EP quality count (§11.17); entry at the post-market price before 17:00 ET, when Saxo's extended hours end. The study measured this entry at 16:45 on after-close earnings releases only. TradingView may not have the new quarter's revenue and EPS yet at 16:50, so those two points can still be the previous quarter's | 1 | Push, and again in the next pre-market push with its pre-market move against the after-hours price (Emil, 23 Oct 2026) |
| BO pivot (Emil, 19 Oct 2026; rule proposed) | Active BO-Watch names at or above their pivot, or at most 1% below it, during the session. Pivot and order stop from the name's latest EOD BO-Watch row (§6.4). Over the pivot: entry at the last price; under it: buy-stop at the pivot | 2 | Push |

### 6.2 End of day (22:20 CET)

| Scan | Filters | Phase | Action |
|---|---|---|---|
| EP-Day (yours) | Gap ≥ 10%, RVOL ≥ 3, volume ≥ 300K, price ≥ $1, mcap ≥ $50M | 1 | Log since 21 Oct 2026 (Emil): its buys are EP 10:30 and EP-AH; still feeds EP-Watch and the EP history |
| EP-AH | Moved to the 16:50 after-hours check on 21 Oct 2026 (§6.1b) | 1 | — |
| EP9M (Stockbee) | Volume ≥ 9M shares, change ≥ +4%. No MA filter (MA position stored as columns) | 1 | Log since 21 Oct 2026 (Emil): its buys are the 10:15 / 12:00 EP9M pace checks |
| Momentum Burst up (Stockbee) | Change ≥ +4%, volume > prior day, volume ≥ 100K, close location ≥ 0.70 | 1 | Push next pre-market (Emil, 22 Oct 2026) |
| Momentum Burst down (Stockbee) | Change ≤ −4%, volume > prior day, volume ≥ 100K | 1 | Log |
| Parabolic Short (Kullamägi) | ≥ 50% gain in ≤ 10 days (mcap ≥ $1B) or ≥ 200% (mcap < $1B); ≥ 3 consecutive up days; distance from MA10 in ADR stored | 1 | Push next pre-market (Emil, 21 Oct 2026) |
| Parabolic Long (Kullamägi) | ≥ 30% drop in ≤ 10 days; ≥ 3 consecutive down days; distance below MA10 in ADR stored | 1 | Push next pre-market (Emil, 21 Oct 2026) |
| Luk AVWAP flush (Emil, 20 Oct 2026) | Martin Luk's AVWAP flush (§11.16, rules in config `luk:`), alert tier, from 300 sessions of daily bars. Graded (§11.17); the plan buys the next session around 10:30 | 2 | Push at EOD and again in the next pre-market push with its pre-market move (Emil, 21 Oct 2026) |
| Luk pullback (Emil, 22 Oct 2026) | Martin Luk's pullback (config `luk:`, proposed, the study's rules): a leader dips to its EMA 9 or 21 and closes back over it. Grade C, pushed in the next pre-market push with the study plan (bought at that close, 1-ADR stop, 21 sessions) | 2 | Push next pre-market |
| VCP (Minervini; Emil, 22 Oct 2026) | A Trend Template stock with a VCP base at the close (2-6 shrinking contractions, the last tight, volume drying up; config `minervini:`, proposed) still under its pivot: the next session's buy-stop at the pivot, stop 1 ADR under (at least 1 %), hold 21. Grade C, pushed pre-market | 2 | Push next pre-market |
| Trend Template (Minervini; Emil, 22 Oct 2026) | Every alert-tier stock passing Minervini's Trend Template at the close, ranked by RS (within the alert tier) | 2 | Log |
| MA-surf (Emil, 21 Oct 2026) | Qullamaggie's breakout from a base surfing the rising 10- or 20-day MA (rules in config `qm_surf:`, all proposed, unchanged from the study), alert tier, from 160 sessions of daily bars. Grade C (no edge of its own in the 2016-26 study), pushed anyway (`push_ungraded`) because Emil trades it: the study plan for the next session (from 10:00 ET over the pivot buy, under it a buy-stop at the pivot; the order stop under the base's right side; out on a close under the 20-day MA), sized at the account's risk like the breakouts | 2 | Push |
| Breadth (Stockbee Market Monitor style) | MB up count, MB down count, 5- and 10-day up/down ratios, stocks up ≥ 25% in a quarter vs down ≥ 25% in a quarter, % above MA20 / MA50 / MA40. Universe: price ≥ $5, volume ≥ 100K. Extended 19 Oct 2026 (Emil) with the rest of Stockbee's Market Monitor: up/down ≥ 25% and ≥ 50% in a month (22 sessions), up/down ≥ 13% in 34 sessions (needs daily history); plus SPY and VIX next to QQQ; 20 Oct 2026 (Emil): QQQ shown like SPY (change, MA position), and the QQQ trend's SMA20 from 5 sessions ago taken from the daily bars until EOD runs have stored it | 1 | Push (top lines) |
| Market Light (yours) | See §6.5. Computed daily; the scan count input only changes on Sundays | 1 | Push (one line) |
| Universe snapshot | Every stock in the logged tier with all metrics | 1 | Log |
| Breakout B1–B4 (yours) | See 6.4 | 2 | Push (BO-Watch) |
| Breakout B5 trigger (yours) | See 6.4 | 2 | Log since 21 Oct 2026 (Emil; grade C) |

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
Code computes B1–B5 as booleans; the human's A/B/C (A = all 5, B = 4, C ≤ 3) stays the human's call.
The study grade (§11.17) is separate and labelled as such.
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

- Your edits (Emil, 22 Oct 2026): every scan may carry an optional `label` (its name in the push) and
  `note` (a line under its section), set with the rest of its settings on the dashboard's Scans page
  (`scan_editor.py`: in-place edits validated by `parse_config`, then commit and push). The Sunday
  lists are shown in full: they are lists to study, not graded setups.

- One message per job, not per ticker.
- Study grades (§11.17, Emil 20 Oct 2026): A+/A get a full block (grade, when to buy, exit and expected hold,
  the history behind the grade, size from the account risk x the grade's multiple), B one line under the
  plan they share, C is saved and counted in one closing line ("Study C, saved: ...").
- Format: title `Trading OS · EOD 2026-10-19`, body = breadth line, then each pushing scan with up to
  10 tickers: `TICKER  +14.2%  RVOL 5.1  $82M  [earnings]`.
  Phone layout (Emil, 19 Oct 2026): the title carries the counts (`🟡 EOD Fri 16 Oct · EP 2 · BO 3`),
  the market lines come first, then one section per scan with a short block per stock (alert line,
  entry/stop, size, facts wrapped to ~40 characters). A stock shown above gets one line; scans
  without alerts share one closing line; tapping opens the run's report in the data repo.
- Market heat (Emil, 21 Oct 2026): the market lines of the pre-market, EOD and weekly pushes end with the
  heat band of the latest Sunday scan count (cool < 18, mild 18-44, warm 45-80, hot > 80), how the graded
  A setups did at that heat, and the C setups that held there in both 2016-21 and 2022-26 (net R a trade
  after costs; held = up per trade and per signal day in both, 30+ trades each). Built from the grading
  study by `scripts/heat_stats.py` into `data/grading/heat_stats.json`; read by `heat.py`. Facts, not grades.
- Next-morning watch (Emil, 21 Oct 2026): BO-Watch, MA-surf and the parabolics are found at the close
  but pushed in the next pre-market push (`push_slot: pm`), each with its pre-market price and move,
  the move against the pivot, and a warning when it is up more than 1 ADR pre-market; the study plan
  sits once under each section (all grade C, `push_ungraded`). The EOD push names what is held back
  ("In the pre-market push: ..."). Only the push moves: the hits are saved with the EOD run.
- Heat tag (Emil, 22 Oct 2026): every hit of a scan with a study setup carries how that setup did at the
  latest scan count's heat on 2016-21 / 2022-26 (`heat.tag`: held / mixed / lost / few trades, net R a
  trade, trades) in the push and the report. It is a fact, not a grade: A/B grades stay with the
  setups that passed the blind and account tests.
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
- No trade decisions by code. Study grades only as in §11.17, labelled as history, never as advice.
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
11. ~~More facts per alert~~ — decided 19 Oct 2026 by Emil (ideas from breakoutshappen.com and the reference
   repos): each fact line also shows relative strength (1-99, mean percentile of the 1/3/6-month returns),
   "earnings in N days" when the next report is within 10 sessions, "at all-time high", and the stock's
   industry rank (industries ranked by the median 1- and 3-month return of their members, at least 5
   members; the weekly push lists the leaders). Facts only: none of them filters, scores or grades.
12. ~~Which breakout triggers push~~ — decided 19 Oct 2026 by Emil, after the history replay showed
   B5 alone firing ~42 times a day (1 of 2,503 with B1–B4): a trigger pushes only when B1–B4 also pass.
   B5-only triggers are still saved with their B-flags (for the audit and the stats); the push counts
   how many were held back. Later the same day Emil asked to see them too: the top 5 B5-only triggers
   follow as one line each with their B-flags, no size or facts (`partial_top_n`).
13. ~~EP history~~ — decided 19 Oct 2026 by Emil: every EP-Day and EP9M rule hit in the 2-year Massive
   bars becomes a study row for the EPStudyDatabase ("Found Forward? = No"): point-in-time features (gap,
   RVOL, ADR, months sideways, move before, 6-month/52-week high, 200d, the market that day) and outcomes
   after 1 day, 1 week, 1 month, a quarter, half a year and a year (return, best/worst point, stop hit, R)
   plus trailing exits under the 10/20-day MA. Entry and stop as the live EP alert. EPS/sales growth and
   earnings timing are inferred from TradingView's quarterly history (no past report dates exist there).
   The five sheet criteria are yes/no facts; the grade stays the human's. Stored in the data repo
   (`data/ep_history/`, an EP Log-ordered xlsx in `data/exports/`) and on the dashboard's EP history page.
14. ~~Strategy history~~ — decided 19 Oct 2026 by Emil: the same 2-year replay for every scan (EP9M, Momentum
   Burst up/down, Parabolic long/short, breakout watch and trigger, QM gainers, tight bases), running the live
   scan functions on rebuilt metrics, alert tier only, each measured on its side (shorts profit when it falls)
   with its natural stop. Facts for grading and for tuning the proposed defaults; never a filter by itself.
   The EP entry-timing study runs on Massive minute bars; Alpaca (free, back to 2016) for longer history
   once its delisted coverage is checked. SEC EDGAR gives exact earnings release times (8-K item 2.02).
15. ~~Entries and exits on minute bars~~ — decided 19 Oct 2026 by Emil ("minute bars for all strategies ... best
   entry and exit"): `intraday_study.py`. Each strategy's rule is applied at the entry minute with only the
   bars known by then (an entry picked with the day's close would skip every gap that faded). Stock-days are
   fetched from a daily superset (gaps >= 3 %, +4 % days with 1.5M+ shares, days reaching a prior-day pivot,
   Luk touches, VCP triggers, the session after every end-of-day hit), from Alpaca, each once, into the data
   repo's `intraday-minutes` release. Entries per strategy in `intraday_entries.py`; stops: low so far,
   1 ADR, the setup's own; exits in `intraday_exits.py` (holds of 1/5/21 sessions, MA 10/20 and EMA 9/21
   trails, the managed exits). Study only: it changes no live rule.
16. ~~Martin Luk and Minervini~~ — decided 19 Oct 2026 by Emil ("test the scanning Martin Luk does",
   "add Minervini and VCP"): study-only strategies in the histories, not live scans. Luk (`luk.py`,
   config `luk:`): pullback to EMA 9/21 in a leader, AVWAP flush, inside day; rules from public write-ups of
   his interviews (no rule sheet of his exists), all (proposed). Minervini (`minervini.py`, config
   `minervini:`): the Trend Template from his books and a mechanical VCP (swing highs, shrinking
   contractions, volume dry-up, pivot = the last contraction's high, stop <= 8 %); the VCP reading is
   (proposed). Luk's EMA 9/21 exit is measured for every strategy. A live scan for any of them needs Emil's
   OK on the rules and a SPEC entry first.
17. ~~Late GitHub crons~~ — decided 20 Oct 2026 by Emil: a cron-job.org timer starts the timed jobs on
   the minute through GitHub's workflow_dispatch API, with a fine-grained token limited to Actions on this
   repo; GitHub's cron is the backup (§3). System health checks each job's start against the timer.

17. ~~Study grades~~ — decided 20 Oct 2026 by Emil (grading research; answers to the 20 questions):
   code shows a study grade A+/A/B/C per setup from the 10-year grading study (`grading_study.py`,
   `grading_analysis.py`, walk-forward by year, net of Saxo costs, stocks only), with the trade plan
   (entry and when, stop, exit, expected hold, size from the account risk x the grade's multiple) and
   the history behind it (trades, win rate, mean/median R, years positive, from the data repo's
   `data/grading/grade_stats.json`). Rules in config `grading:`, confirmed by Emil on 20 Oct 2026 together with the
   15:45 EP close check (§6.1b) and the live Luk AVWAP flush (§6.2); `grader.py` applies them, deterministic. Scans without a validated scorecard
   grade C ("no edge after costs"). New study-only setups for the research: Qullamaggie's MA-surf
   breakout (`qm_setups.py`), high tight flag and pocket pivot (`patterns.py`); live only with a SPEC
   entry and Emil's OK. Report: data repo `docs/research/2026-10-20-grading-research.md`.
   EP quality count (Emil, 21 Oct 2026): EP is graded by its six yes/no points (`grading.quality.ep`:
   an earnings release, 1–2 months sideways, a market that isn't hot, revenue growth accelerating,
   EPS up year on year, within 20% of the 52-week high; 5–6 = A+, fewer = C: 4 points made +0.12R a
   trade and about 0R per signal day, so Emil made it C on 21 Oct 2026) in place of its close
   scorecard, with two entries: EP 10:30 (bought ~10:30 on the gap day) and EP-AH (bought at
   16:45–17:00 ET the evening of an after-close earnings release). The 15:45 EP close check is off.
   Quality grades for every graded setup (Emil, 21 Oct 2026: "switch to quality grades";
   `quality_enabled: true`): EP9M by the same six points with "earnings in the last 10 sessions"
   (5–6 = A+, fewer = C: as B, 4 points doubled the trades and halved the 2022–26 account result
   in the portfolio report's shuffled runs, so Emil made it C on 21 Oct 2026; bought after the
   10:15 check; names first found at 12:00 take the 12:00 plan),
   the Luk flush A when the market isn't hot and the
   5-day range is tight (bought the next session ~10:30). An EP 10:30 gap that the 16:50 check pushed
   the evening before shows "flagged last evening" instead of a second buy (one position per stock).
   Each grade shows its own entry's 2016–26 history (`grade_stats.json`, `quality`). Caveats, stated
   with the grades: the points were partly chosen with 2022–26 in view; rules picked blind on 2016–21
   score lower; in the 2022–26 portfolio runs (100 shuffled same-minute orders, 1 % / 0.75 % risk) the
   quality package made a median 8–15 % a year depending on the EP entry, and the blind version −7 to
   +6 % (data repo `docs/research/2026-10-21-portfolio-research.md` §11–12).

## 12. References

- Qullamaggie: https://qullamaggie.com — 1/3/6M gainer scans, Breakout, EP, Parabolic
- Stockbee: https://stockbee.blogspot.com — Momentum Burst, EP9M, Market Monitor
- Mark Minervini: Trade Like a Stock Market Wizard (2013), Think & Trade Like a Champion (2017) — Trend
  Template, VCP
- Martin Luk: interview write-ups (no rule sheet of his own), e.g. tradingresourcehub.substack.com,
  financialwisdomtv.com, ideas.finetiqsystems.com — EMA 9/21 pullbacks, AVWAP, inside days
- `shner-elmo/TradingView-Screener`, `dcimring/stockbee-dashboard`, `phuazz/vcp-screener`,
  `js8m226wkn-dotcom/qullamaggie-scanner`, `VladPetrariu/Qullamaggie-breakout-scanner`
