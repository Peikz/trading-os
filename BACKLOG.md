# BACKLOG — Trading OS

Work top to bottom. Tick items when done (code + tests + manual run + commit).

## Phase 1 — Core scans

### Setup
- [x] Emil: create public repo `trading-os` (add SPEC.md, CLAUDE.md, BACKLOG.md, `.github/workflows/claude-backlog.yml`) and private repo `trading-os-data` — done 18 Oct via gh; backlog worker disabled until START-HERE Step 6
- [x] Emil: fine-grained PAT with contents read/write on `trading-os-data` only → secret `DATA_REPO_TOKEN` in `trading-os` — added 19 Oct (needed repository access plus Contents read/write)
- [x] Data-repo client: checkout, write, commit, push from workflows; log only counts/status (SPEC §2 two-repo rules) — built in `eod.yml`, `premarket.yml` and `weekly.yml`; the scan side already ran green on GitHub (`Pipeline check`, 19 Oct: TradingView reachable from Actions, public log counts only); the commit/push side waits for `DATA_REPO_TOKEN` — first forced EOD on GitHub (19 Oct) committed to the data repo as trading-os-bot
- [x] Project skeleton: `pyproject.toml`, `ruff`, `pytest`, package layout per CLAUDE.md
- [x] `config/scans.yaml` with every threshold from SPEC.md §4 and §6 (Phase 1 scans)
- [x] Market calendar + New York time guard (premarket / eod windows, holidays)

### Data
- [x] TradingView client wrapper: verify field names (SPEC §11.1), print samples, document in `docs/fields.md`
- [x] Universe builder: exclusions + logged/alert tiers (SPEC §4)
- [x] Metrics module with unit tests (SPEC §5) — Phase 1 uses TradingView fields where they exist; every §5 metric now has a hand-computed test (`metrics.py`, `history_metrics.py`), and the exact values replace the proxies per row once history exists
- [x] Parquet writer (append-only, partitioned per SPEC §7) + xlsx export

### Scans — EOD
- [x] EP-Day — built and run locally on 16 Oct; ticks after the first Actions run — ran on GitHub 19 Oct (forced EOD into the data repo)
- [x] EP9M — built and run locally on 16 Oct (5 hits); ticks after the first Actions run — ran on GitHub 19 Oct (forced EOD into the data repo)
- [x] Momentum Burst up / down — built and run locally on 16 Oct (24 up, 308 down); ticks after the first Actions run — ran on GitHub 19 Oct (forced EOD into the data repo)
- [ ] Parabolic Short / Long — built on full-history metrics (`hist_*` columns); finds nothing until ~11 sessions of bars exist (Massive backfill, or our own EOD snapshots; default 1 in Questions)
- [ ] Breadth line + Market Light count — built: breadth row daily (`data/breadth/`), two push lines, light from the owner's table; Sunday scan count (`data/market_light_count/`). Light shows once QQQ's 5-session SMA20 slope and 10 days of counts exist; defaults 1, 4, 5 in Questions
- [x] EP-AH (built, toggle OFF) — built and tested; ticks after the first Actions run — ran on GitHub 19 Oct (forced EOD into the data repo)

### Scans — pre-market
- [ ] EP-PM — built, `premarket.py` + `premarket.yml`; smoke-tested locally; ticks after the first Actions run
- [ ] EP9M early warning — built (default 3 in Questions); ticks after the first Actions run
- [ ] Watchlist gappers (empty watchlist OK until Phase 2) — built on the watchlists below (defaults 3, 6); ticks after the first Actions run

### Scans — weekly
- [ ] Qullamaggie 1/3/6M gainers — built, `weekly.py` + `weekly.yml`; run locally on the week to 16 Oct (73 hits); ticks after the first Actions run
- [ ] Growth Bucket 1 and 2 (record quarters checked) — built; previous quarter comes from `total_revenue_fq_h` / EPS history (SPEC §11.2: available); run locally (202 / 150 hits); ticks after the first Actions run

### Delivery
- [x] ntfy notifications (one message per job + failure message) — test EOD message and failure message both sent from GitHub on 19 Oct and received
- [ ] GitHub Actions: `premarket.yml`, `eod.yml`, `weekly.yml` with dual cron + guard + `workflow_dispatch` + commit of `data/` — all three done (weekly: Sunday 16:00 and 17:00 UTC, guard on the New York weekday); `eod.yml` wrote to the data repo 19 Oct; pre-market's first scheduled run is 20 Oct, weekly's 25 Oct; `intraday.yml` added 19 Oct
- [x] Secret set: `NTFY_TOPIC` (Massive key not needed until Phase 2) — added 19 Oct; a test push from GitHub (`Pipeline check` with push) was accepted by ntfy

### Validation
- [ ] `docs/validation.md` **in the private data repo**: first 2 weeks, EP-Day and gainers vs Emil's manual TradingView screens — started with 16 Oct; `scripts/compare_screen.py` diffs a run against a TradingView CSV export and appends the table (with the reason for each difference) to `docs/validation.md`
- [ ] 10 consecutive trading days without manual intervention → Phase 1 done

## Phase 2 — Breakouts and history
- [x] Emil: create free Massive account, add `MASSIVE_API_KEY` as GitHub Secret (agent: if missing, log under Blocked and continue with other items) — added 19 Oct; `Massive check` workflow OK: 12,630 tickers on the latest session, history back to 2024-10-28 (older days answer 403, so the window is capped at 720 days)
- [ ] Massive 2-year grouped-daily backfill (rate limited, resumable) — built: `massive.py`, `backfill.py`, `backfill.yml` (dispatch with max_calls=504 ≈ 100 min); tested with mocked API; full run dispatched 19 Oct
- [ ] Daily Massive update in `eod` job — built as the scheduled catch-up in `backfill.yml` (09:30 UTC Tue-Sat, newest missing sessions first); exits cleanly without a key
- [ ] Metrics on full history (ADR, returns, MA slopes, consecutive days) — built and wired: `prefer_history` swaps in exact RVOL / ADR / returns / 20-day averages per row (whole groups, proxy kept as `*_proxy`, basis columns updated); end-to-end tested on 55 stored sessions; activates with the backfill
- [ ] Base detection B2 (configurable heuristic, store intermediates) — built: `breakouts.py` (pivot = base's highest high, zigzag contractions, depths/lows/volume ratios stored); unspecified parameters marked (proposed) in `config/scans.yaml` `breakout:`; waits for history and the 20-hit hand audit
- [ ] B1, B3, B4 (pivot, order stop, risk_adr), B5 trigger — built: `breakout_watch` (B1-B4 all pass) and `breakout_trigger` (B5 at the close vs yesterday's base, B1-B4 stored for grading) in the EOD job; candidates carry pivot, order_stop, risk_adr, base_len, contraction_depths, b1..b5
- [ ] Watchlists: EP-Watch → BO-Watch flow — built: append-only event log (`data/watchlists/`), add/refresh/move/trigger/expire (default 6 in Questions)
- [ ] Tight bases scan, CATS score — tight bases built (weekly, action `watchlist`, SPEC thresholds, needs ~50 sessions of bars); CATS built as a column on gainers and tight bases with proposed weights (default 14)
- [ ] Hand audit of 20 random breakout hits — `scripts/audit_breakouts.py` replays B1-B5 over the Massive history and writes `docs/breakout_audit_<date>.md` (charts + checklist) in the data repo; runs right after the backfill

## Phase 3 — Outcomes and journal
- [ ] Outcomes job (5/10/20/60 days) — built: `outcomes.py`, `outcomes.yml` (22:00 UTC weekdays); hand-computed tests; runs on EOD snapshots until Massive history exists
- [ ] Before-shot chart PNGs per alert candidate — built: `charts.py`, drawn by the EOD and pre-market jobs for every pushed candidate into `data/charts/` (120 sessions, MA10/20/50, volume, pivot/stop when present); sparse until history exists
- [ ] Write Breakout Log rows to EPStudyDatabase (Google service account) — built (`epstudy.py`, EOD job, deduplicated by signal_id), off until you set `epstudy.enabled`, `sheet_id` and the secret `GOOGLE_SERVICE_ACCOUNT_JSON`; columns are config (proposed)

- [x] Monthly live check (Emil, 21 Oct 2026) — `live_tracking.py`, `scripts/live_check.py`, `live-check.yml` (1st of the month): live A+ / A signals by their study plan against the study per grade, your trades against the plan; report in the data repo, one push, dashboard *Live results → Grades live vs study*

- [x] Market heat in the push (Emil, 21 Oct 2026) — `heat.py`, `scripts/heat_stats.py` → `data/grading/heat_stats.json`: the pre-market, EOD and weekly market lines end with the heat band of the Sunday count, the A setups at that heat and the C setups that held there in both periods; Market page table per heat

## Phase 4 — Trade tracking
- [ ] Saxo fills import (OpenAPI or CSV) → journal with R-multiples — built for CSV (`scripts/import_fills.py` and the dashboard's Journal page): map your export's headers in `journal.csv_columns` after the first Saxo export; trades flat to flat, linked to signals, R from the signal's order stop or a stops CSV
- [ ] Power BI model over DuckDB/Parquet — groundwork: `scripts/build_duckdb.py` builds a views-only DuckDB file over the data repo (universe, candidates, outcomes, bars, signals_with_outcomes) for the DuckDB ODBC driver; the model itself waits for real trades

## Phase 5 — Dashboard
- [ ] Private dashboard — built (System health, Entries & exits, Journal tabs added 20 Oct): Streamlit app (`app/streamlit_app.py`, localhost by default): today, screens, watchlists, journal with grades/notes/screenshots, graded signals, market, stats, validation. Plus a Markdown report per run in the data repo. Phone access: Tailscale (Emil, 19 Oct) via `scripts/start_dashboard.ps1` (`tailscale serve`); waiting for Tailscale to be installed on the PC

---

## Questions for Emil

You asked me to keep going without you, so each open choice below runs on a default. Each one
is a single line in `config/scans.yaml` (marked "proposed") or a small code note. Say the
word and I flip it.

| # | Choice | Default now running | Where |
|---|---|---|---|
| 1 | History for Parabolic, breadth ratios, Market Light | Our own EOD snapshots, plus Massive bars once you add `MASSIVE_API_KEY` (both feed the same loader) | `history.py` |
| 2 | EP9M push tier | Alert tier only (a quiet stock that suddenly trades 9M is saved, not pushed) | `ep9m.push_tier` |
| 3 | Pre-market "gap" (EP9M early, watchlist gappers) | `premarket_change` = current pre-market price vs prior close | `pm_gap_basis` |
| 4 | Market Light scan count: average-volume window | 30-day TradingView average | `market_light.scan_count.avg_volume_field` |
| 5 | Breadth up count | Stockbee style: up >= 4 % on volume above the prior day (no close-location rule) | `breadth.up_count_rule` |
| 6 | Watchlist rules | EP-Watch from EP-Day and EP-PM alert hits, expires after 63 sessions; BO-Watch expires after 10 sessions without B1-B4 | `watchlists:` |
| 7 | Breakout parameters SPEC leaves open | Swing >= 1 ADR $, >= 2 contractions, quiet volume = base avg below 50-day avg, right side = 5 sessions < 1.5 x ADR $ | `breakout:` |
| 8 | Breakout trigger | Full block only when B1-B4 also pass (Emil, 19 Oct, SPEC §11.12); the top 5 B5-only triggers follow as one line each with their B-flags | `breakout_trigger.push_if_all`, `partial_top_n` |
| 9 | Breakout and EP push tier | Alert tier, same as EP-Day (SPEC §11.7) | `push_tier` |
| 10 | EP-PM price floor | Prior close | `scans/ep.py` |
| 11 | QM gainers | Top 2 % over the whole logged-tier universe, then the floors; TradingView Perf.1M/3M/6M and ADR(14)/close | `proxies:` |
| 12 | Growth buckets | 30-day average volume; annual revenue = trailing 12 months | `growth_bucket_*` |
| 13 | EP-Day ranking and `[earnings]` flag | Largest gap first; earnings on the signal session or the one before | `scans/ep.py` |
| 14 | CATS weights | +1 growth bucket, +1 MB up/EP in the last 10 sessions, +1 if 30-day avg volume > 90-day, −0.5 per ADR beyond 3 ADR above MA10 | `cats:` |
| 15 | Position size in the push (Emil: 500k DKK, 0.5 % risk, in USD) | EP: entry at the close, stop at the day low but 0.25-1 ADR below entry; pre-market: 1 ADR below the pre-market price until the open; breakouts: SPEC order stop; max 25 % of the account in one name (Emil, 19 Oct) | `sizing:` (method) + data repo `settings/account.yaml` (private numbers) |
| 16 | Facts under pushed EPs and breakouts (Emil asked for context, fundamentals, EPS) | Top 5 per scan get one line of facts, no verdict (SPEC §10: no AI, no grading). EP: earnings on the session and when, EPS and revenue YoY for the last two quarters with the surprise vs estimates, float and how much of it traded, 6-month move before the gap, distance from the 52w high, above/below the 200d, industry, plus the latest headline from Massive (max 8 lookups a run; published within 48 h or since the previous session day, whichever reaches further back). Breakouts: prior move, 3/6M return, 52w high, ADR, MA stack, growth. One extra TradingView request for the pushed names; if it fails, alerts go out without facts. Headlines are dropped first when a message nears ntfy's 4 KB limit | `context:` |
| 17 | EP9M pace during the session (Emil chose this, 19 Oct) | 10:15 and 12:00 New York; change ≥ +4% and volume so far or pace ≥ 9M; pace = TradingView relative volume at time (5-minute) × the RVOL base (60-day average, today excluded); alert tier as EP9M (no signal-day dollar-volume guard, which only applies at the close); a name pushes once a session; entry at the last price, stop at the day's low within the EP ADR bounds | `scans.ep9m_pace`, `schedule.windows_et.am/mid` |
| 18 | Market Monitor extension (Emil, 19 Oct) | Month = 22 sessions (our 1-month window), 13 % move over 34 sessions from daily history only; the 34-day count shows n/a until at least half the breadth universe has history | `breadth.month_move_pct`, `month_big_move_pct`, `mid_move_pct` |
| 19 | Industry rank (Emil, 19 Oct) | TradingView industry; median 1M and 3M return of logged-tier members, mean of the two; groups under 5 members unranked; QM-gainer count shown, not scored | `context.industry_*` |
| 20 | RS, earnings soon, all-time high (Emil, 19 Oct) | RS = mean percentile of 1/3/6-month returns in the logged-tier universe, 1-99; earnings within 10 sessions; all-time high within 1 % | `metrics.rs_percentile`, `context.earnings_soon_sessions` |
| 21 | BO pivot intraday (Emil, 19 Oct) | Active BO-Watch names at most 1 % under the pivot or over it, levels from the latest EOD BO-Watch row (up to 11 EOD runs back), ranked by relative volume at time; once a session | `scans.pivot_watch.near_pivot_pct` |
| 22 | EP history: "months sideways" (Emil, 19 Oct) | Months (21 sessions) before the gap with every close within ±25 % of the pre-gap close | `ep_history.neglect_band_pct` |
| 23 | EP history: earnings EP and growth at the time | A gap within 10 days of the quarterly reporting rhythm (latest TradingView report date minus whole quarters) is an earnings EP; growth = the quarter reported by then; C3 = EPS or sales growth ≥ 50 % | `ep_history.match_days`, `c3_growth_min_pct` |
| 24 | EP history: entry, stop, C5 | Entry at the gap-day close and stop at the day low within the live EP ADR bounds (as the alerts); C5 uses the raw low-of-day distance ≤ 1.5 ADR | `sizing:`, `ep_history.c5_stop_adr_max` |
| 25 | Minute-bar study supersets and stops (Emil, 19 Oct) | Fetch every gap >= 3 %, +4 % day with 1.5M+ shares, prior-pivot day, Luk touch, VCP trigger and next session after an EOD hit; fixed-distance stop 1 ADR; EP9M pace = volume so far / 0.22 at 10:15 and / 0.42 at 12:00 (the live scan uses TradingView's relative volume at time, which the bars don't have) | `intraday_study:` |
| 26 | Martin Luk's setups (Emil, 19 Oct) | Leader: up >= 30 % over 1/3/6 months, ADR >= 5 %; lead = EMA 9 > 21 > 50; touch within 0.25 ADR of yesterday's EMA/AVWAP; flush >= 0.5 ADR under the prior close; AVWAP from the 250-session high, base >= 40 sessions; stop at the day's low | `luk:` |
| 27 | Minervini's VCP (Emil, 19 Oct) | Trend Template as in his books, RS = our 1-99 RS; base 3-26 weeks; swing highs hold 5 sessions each side, contractions >= 0.5 ADR, 2-6 of them, each shallower, first <= 35 %, last <= 10 %; last 10 days' volume <= 0.8 x the 50-day; stop at the last contraction low, at most 8 % | `minervini:` |
| 28 | Minute study: no stop closer than 1 % of the entry | With only the 0.25 ADR floor, quiet stocks (merger targets) got stops of cents and R in the hundreds; 1 % is about the closest stop that survives spreads | `intraday_study.min_stop_pct` |
| 29 | Trade plans expire after 5 sessions | A plan with no matching entry fill within 5 sessions of its day shows as expired | `journal.plan_valid_sessions` |

Still open (no default possible):
- **Data repo size:** each trading day adds ~3 MB of Parquet (pre-market + EOD universe snapshots, zstd), about 0.75 GB a year in git. Fine for the first years; later options are a slimmer pre-market snapshot or moving old Parquet to release assets / object storage. No action needed now.
- ~~Your manual EP-Day screen~~ — answered 19 Oct by Emil: it filters on neither TradingView's 10-day "Relative Volume" nor "Primary listing". Same as the pipeline (no primary-listing filter; RVOL from the 60-day proxy, exact 50-day once history exists), so neither explains a validation difference.

## Blocked
- Nothing blocked. All secrets are set (19 Oct); the 2-year backfill is running.

## Session log
- 2026-10-18: Repos created; skeleton, config, clock guard, TradingView client (fields verified, see `docs/fields.md`), universe tiers, Phase 1 metrics subset, EP-Day, store, ntfy, `eod.py`, `eod.yml`. Local forced run on 16 Oct data OK. Next: secrets, then the first Actions run of `eod.yml`.
- 2026-10-19: EP9M, Momentum Burst up/down, EP-AH (off), EP-PM + `premarket.yml`; shared job runner. Local runs on 16 Oct data written to `docs/validation.md` in the data repo. Probed TradingView history depth (2 bars only). Next: secrets → first Actions runs; then answers on the Questions above.
- 2026-10-19 (later): QM gainers, Growth Bucket 1 and 2, weekly job + `weekly.yml`; ADR %, returns and previous-quarter growth metrics; reported revenue history verified (100 % match). Local weekly run written to `docs/validation.md`. Next: secrets → first Actions runs; answers on the Questions.
- 2026-10-19 (later): Hardening for the 10-day goal: one retry on TradingView/ntfy errors, data saved even if the push fails. READMEs for both repos (data repo: layout + DuckDB query). All unblocked Phase 1 items done; the rest waits on the secrets and the Questions above.
- 2026-10-19 (later): Phase 2/3 groundwork on Emil's go-ahead: bars store + loader, Massive client and resumable backfill (+ daily catch-up), SPEC §5 metrics on full history, outcomes job. All tested offline; none needs a decision. Waiting on: secrets, Massive key, Questions.
- 2026-10-19 (later): History metrics wired into EOD and weekly jobs as `hist_*` columns; Parabolic Short/Long and tight bases built on them (0 hits until history accumulates). Live forced EOD run OK in ~10 s.
- 2026-10-19 (later): Before-shot charts (Phase 3) wired into the EOD and pre-market jobs; a chart failure is logged and never fails the run.
- 2026-10-19 (later): Breakout B1-B5 detector (Phase 2) with BO-Watch and trigger scans, breakout fields stored in candidates, breakout lines in the push. 10k tickers in ~3 s. Proposed parameters listed under Questions.
- 2026-10-19 (later): Validation helper (TradingView CSV vs run, with reasons) and DuckDB views builder.
- 2026-10-19 (later): On Emil's 'continue without me': EP9M early warning, breadth line + Market Light, watchlists + watchlist gappers, all on documented defaults (Questions table). Every Phase 1 scan is now built; waiting on secrets for the first Actions runs.
- 2026-10-19 (later): Markdown report per run (`reports/` in the data repo, charts inline, readable in the GitHub app); CATS column; weekly outcome statistics (`reports/stats/`). Forced runs now keep charts in their manual folder.
- 2026-10-19 (later): Phase 3 EPStudyDatabase writer (off until configured); Phase 4 journal (fills import, trades, R, signal links), DuckDB journal view and Power BI notes; Phase 5 private Streamlit dashboard, checked page by page on demo data.
- 2026-10-19 (later): Breadth also runs pre-market (Emil): today's Market Light, last close's breadth, pre-market movers and QQQ pre-market at the top of the pre-market push (SPEC §6.1, §11.9). Dashboard shows them; smoke test covers every page. Tailscale chosen for phone access; start script added.
- 2026-10-19 (later): Massive key verified live; backfill window capped by date with 403 skip; breakout audit replay ready for after the backfill.
- 2026-10-19 (later): Exact history metrics replace the TradingView proxies row by row as soon as history exists (SPEC §11.6 note); Phase 1 metrics item ticked.
- 2026-10-19 (later): `Pipeline check` workflow ran EOD, pre-market and weekly on GitHub's runners (forced, no push): TradingView answers from Actions (4,517 rows), charts and reports work on Linux, public log has no tickers. Only the data-repo commit and the ntfy push are untested, both waiting for the secrets.
- 2026-10-19 (later): Position sizing in every pushed alert (Emil): entry, stop, shares, position and risk in USD from the private account file (500k DKK, 0.5 %), live USD/DKK from TradingView; stored in candidates; journal R falls back to the planned stop for EP trades. Failure push tested from GitHub.
- 2026-10-19 (later): Facts under the top pushed EPs and breakouts (Emil): earnings timing, EPS/revenue growth and surprise, float traded, prior 6-month move, 52w high, 200d, industry, latest Massive headline for EPs. Stored in candidates (`ctx_*`), shown in the report and on the dashboard's Today page. Facts only; the grade stays yours.
- 2026-10-19 (later): DATA_REPO_TOKEN works (needed repo access plus Contents read/write). First forced EOD on GitHub wrote to the data repo (bot commit), pushed with sizing and facts; public log counts only. Fact display tidied after reading the real report: growth beyond ±999 % shown as capped, no `-0%`, float traded as % below 1x; headline window reaches back to the previous session day. 2-year backfill started.
- 2026-10-19 (later): EP9M pace (Emil): new `intraday` job at 10:15 and 12:00 New York finds EP9M names before the close from TradingView's relative volume at time. First live run is the check: compare the 10:15 pace with the day's final volume in a few EOD runs before trusting it.
- 2026-10-19 (later): Emil: defaults table ok as running; intraday checks keep pushing "no alerts" so a quiet day still shows they ran; Emil will do the breakout hand audit and the 2-week validation; Tailscale install approved.
- 2026-10-19 (later): From breakoutshappen.com and the reference repos (Emil chose all four): Stockbee Market Monitor month/34-day counts and SPY/VIX in the header; weekly industry ranking with the rank in every fact line; RS, earnings-soon and all-time-high facts; intraday BO pivot alert at 10:15/12:00.
- 2026-10-19 (later): Push messages laid out for a phone (Emil: "very hard to read"): counts in the title, short market lines with ▲/▼, one block per stock, repeats collapsed, facts trimmed from the bottom up under ntfy's 4 KB limit (before, one long message dropped every fact line), tap opens the report. Breakout audit sheet (10 BO-Watch, 10 triggers) in the data repo; trigger push rule waits on Emil.
- 2026-10-19 (later): Emil: breakout triggers push only with B1-B4 (SPEC §11.12). Push colours: 🟩/🟥 B-flags, 🟢/🔴 market counts and moves, section icons, 🛑 stop, 📢 earnings, ✅/❌ for the 200d and MA stack; the "no earnings" filler line is gone and the industry rank reads #3/112.
- 2026-10-19 (later): Emil wants the B5-only triggers visible too: top 5 as one line each under the full setups (`B5 only · top 5 of 13`).
- 2026-10-19 (later): EP history study (Emil): 29,637 EP-Day/EP9M rule hits over 494 sessions of Massive bars (7,162 EP-Day, 3,573 in the alert tier) with point-in-time features, the market that day, outcomes after 1d/1w/1m/1q/6m/1y and MA10/MA20 trailing exits; fundamentals inferred for 1,922 still-listed stocks. Data repo `data/ep_history/` + EP Log-ordered xlsx; dashboard EP history page with filters, grouped stats and before/after charts. Rebuild after more bars: `scripts/ep_history.py`.
- 2026-10-19 (later): Massive free plan probed: minute bars incl. pre/post-market, ticker list incl. delisted, ticker details as of a date, short interest and historical news all OK; financials 410 (switched off). Emil: "take everything" -> `ep-enrich.yml` fetches them for the EP-Day events at night (22:35-04:20, 04:30-09:20 UTC, weekends 09:45-15:30), resumable, ~12,700 calls (~4-5 nights). SEC EDGAR (exact earnings dates and EPS/revenue as filed) waits for the contact email the SEC requires in the User-Agent.
- 2026-10-19 (later): SEC EDGAR works with Emil's Gmail as contact (secret SEC_USER_AGENT; the GitHub no-reply address is refused): 2,307 filers, 11,012 earnings releases with times, quarterly EPS/revenue; the EP study now has exact earnings (earnings EPs win 47% vs 32% after a month). Strategy history for every scan (172,708 alert-tier hits, `data/strategy_history/<date>/`, dashboard page). Entry-timing study on minute bars ready, runs when the bars land; the fetch now saves hourly. Alpaca client + check ready, waiting for ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY.
- 2026-10-19 (later): 10 years of Alpaca daily bars (2016-2024, delisted names included) in the data repo's `bars-alpaca` release, ready for longer histories.
- 2026-10-19 (later): Minute-bar entry/exit study for every strategy (Emil): candidates from daily supersets, each stock-day fetched once from Alpaca into the `intraday-minutes` release; entries chosen with only the bars known at the entry minute; vectorised exits for every trade. Dashboard page "Entries & exits".
- 2026-10-19 (later): Martin Luk (pullback, AVWAP flush, inside day) and Minervini (Trend Template, VCP) added to the strategy history and the minute study, study only; Luk's EMA 9/21 exit measured for every strategy.
- 2026-10-20: GitHub started scheduled runs 3-6 h late on 19 Oct: pre-market and both intraday checks skipped, EOD never landed in its window. EOD window widened to 23:59 New York (Emil) with a third, later cron; tonight's EOD run by hand. System health page shows this from now on.
- 2026-10-20: Journal (Emil): log fills by hand with setup and stop (a later broker fill replaces its twin), open positions with open R and risk to stops, trade plans sized from the account risk and matched to fills (slippage), MAE/MFE and exit efficiency, trade charts with fills, real R per setup next to the studies. Saxo export still needed for the broker import mapping.
- 2026-10-20: Dashboard on the phone: Tailscale on PC and iPhone; `tailscale serve --http=80` publishes it to the tailnet only (HTTPS certificates are off in the tailnet, not needed).
- 2026-10-20: Real (unadjusted) daily prices for every stock-day of the 10-year Alpaca bars (Emil: real-price $1 floor): the `bars-alpaca-raw` release holds `raw_<year>.parquet` 2016-2026 (raw OHLCV and `factor` = raw close / adjusted close; 20.8M stock-days, row for row the `bars-alpaca` files), built by `alpaca-raw.yml`. Per year 135-618 stocks show a split-sized factor jump, and 10k-72k stock-days closed under $1 for real but at $1 or more adjusted. The studies' price floors and per-share costs should read `raw_close`.
- 2026-10-20: Grading research (Emil's 20 answers): grading study (stocks only, 9.8M minute-study trades with point-in-time features, Saxo costs), walk-forward scorecards, portfolio simulation; SEC point-in-time fundamentals and raw prices as new releases; MA-surf, high tight flag and pocket pivot detectors. Report in the data repo (docs/research/). Study grades: `grader.py` + config `grading:` (proposed, off); SPEC §1.4/§11.17 changed on Emil's OK. Next: Emil confirms the rules, then grades and plans in the pushes and on the dashboard.
- 2026-10-21: EP moved off the close (Emil): the after-hours look-ahead in the study was fixed (every after-close / pre-market earnings day fetched) and measured small; in the 2022-26 portfolio runs the close was the weakest EP entry. EP is now graded by its quality count (`quality_enabled: [ep]`) with two live entries: EP 10:30 at the 10:17 check and EP-AH at a new 16:50 after-hours check (earnings releases only, bought before Saxo's 17:00 cutoff). The 15:45 close check is no longer scheduled. Needs `scripts/timer_setup.py` re-run to sync cron-job.org.
- 2026-10-21 (later): Monthly live check (Emil): every live A+ / A signal is played out by its study plan on daily bars and compared per strategy, entry time and grade with the history the grade carried (verdict only after 20 closed trades, and 'below' only when mean R and win rate both fall clearly short); journal trades are set against the plan of the signal they came from. `live-check.yml` writes `docs/live-tracking/<date>.md` in the data repo on the 1st and pushes one summary; dashboard section *Grades live vs study*. Next: first real report on 1 Nov.
- 2026-10-21 (later): Market heat in the push (Emil: "which strategies work in this market"): every setup's study plan scored per heat band (Sunday scan count) on 2016-21 and 2022-26 separately; the market lines name today's band, the A setups' results there and the C setups that held in both periods. Results stay in the data repo. Market page shows every band. Rebuild with `scripts/heat_stats.py` after the grading study changes.
- 2026-10-21 (later): Timer sync automatic (Emil: "do I need to do it every time?"): `timer-sync.yml` runs `scripts/timer_setup.py --no-prompt` with the secrets CRONJOB_API_KEY and TIMER_GITHUB_TOKEN whenever `trading_os/timer.py` changes on main, or by hand. Needs the two secrets set once.
- 2026-10-21 (later): MA-surf live (Emil: "I will use this strategy more"): the study's Qullamaggie MA-surf rules run at EOD on the alert tier (`surf_live.py`, scan `ma_surf`); grade C but pushed in full (`push_ungraded`) with the study plan: from 10:00 over the pivot buy, else a buy-stop at it, order stop, out on a close under the 20-day MA.
- 2026-10-21: Notes per stock on the Chart page (Emil): write a note on any day, edit or delete it; append-only log in the data repo (`data/journal/stock_notes/`), so every note stays findable years later; pushed with "Save & push".
- 2026-10-21 (later): Next-morning watch (Emil): BO-Watch, MA-surf and both parabolics are still found at the close but pushed in the next pre-market push (`push_slot: pm`) with the pre-market price, the move against the pivot and a warning past 1 ADR; the parabolics are pushed for the first time. The evening push says what is held back.
- 2026-10-21 (later): Push titles, report headers and the dashboard run list show New York and Copenhagen time (Emil); the run list now also shows the after-hours (16:50) and close (15:45) runs, which it had missed.
- 2026-10-21 (later): EP-Day saved only (Emil): no longer in the evening push; it still runs, feeds EP-Watch and the EP history.
- 2026-10-21 (later): Evening push trimmed (Emil): EOD EP9M and Breakout trigger saved only; Luk flush pushed at EOD and again pre-market with its move (`push_slot: [eod, pm]`). Evening push = market lines, Luk flush, the note of what comes pre-market.
- 2026-10-22: Dashboard on a cloud server (Emil): `docs/SERVER.md` + `scripts/server/install.sh` (Ubuntu 24.04: Tailscale-only access, GitHub CLI login with a fine-grained token, slim data clone, systemd service) and `update.sh` (10-minute timer: pull both repos, restart after a code change). Waiting for Emil to create the server.
