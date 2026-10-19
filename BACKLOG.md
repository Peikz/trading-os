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

## Phase 4 — Trade tracking
- [ ] Saxo fills import (OpenAPI or CSV) → journal with R-multiples — built for CSV (`scripts/import_fills.py` and the dashboard's Journal page): map your export's headers in `journal.csv_columns` after the first Saxo export; trades flat to flat, linked to signals, R from the signal's order stop or a stops CSV
- [ ] Power BI model over DuckDB/Parquet — groundwork: `scripts/build_duckdb.py` builds a views-only DuckDB file over the data repo (universe, candidates, outcomes, bars, signals_with_outcomes) for the DuckDB ODBC driver; the model itself waits for real trades

## Phase 5 — Dashboard
- [ ] Private dashboard — built: Streamlit app (`app/streamlit_app.py`, localhost by default): today, screens, watchlists, journal with grades/notes/screenshots, graded signals, market, stats, validation. Plus a Markdown report per run in the data repo. Phone access: Tailscale (Emil, 19 Oct) via `scripts/start_dashboard.ps1` (`tailscale serve`); waiting for Tailscale to be installed on the PC

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
| 8 | Breakout trigger | Fires on B5 alone, B1-B4 stored for your grade (C grades push too) | `history_scans.py` |
| 9 | Breakout and EP push tier | Alert tier, same as EP-Day (SPEC §11.7) | `push_tier` |
| 10 | EP-PM price floor | Prior close | `scans/ep.py` |
| 11 | QM gainers | Top 2 % over the whole logged-tier universe, then the floors; TradingView Perf.1M/3M/6M and ADR(14)/close | `proxies:` |
| 12 | Growth buckets | 30-day average volume; annual revenue = trailing 12 months | `growth_bucket_*` |
| 13 | EP-Day ranking and `[earnings]` flag | Largest gap first; earnings on the signal session or the one before | `scans/ep.py` |
| 14 | CATS weights | +1 growth bucket, +1 MB up/EP in the last 10 sessions, +1 if 30-day avg volume > 90-day, −0.5 per ADR beyond 3 ADR above MA10 | `cats:` |
| 15 | Position size in the push (Emil: 500k DKK, 0.5 % risk, in USD) | EP: entry at the close, stop at the day low but 0.25-1 ADR below entry; pre-market: 1 ADR below the pre-market price until the open; breakouts: SPEC order stop; max 25 % of the account in one name (Emil, 19 Oct) | `sizing:` (method) + data repo `settings/account.yaml` (private numbers) |
| 16 | Facts under pushed EPs and breakouts (Emil asked for context, fundamentals, EPS) | Top 5 per scan get one line of facts, no verdict (SPEC §10: no AI, no grading). EP: earnings on the session and when, EPS and revenue YoY for the last two quarters with the surprise vs estimates, float and how much of it traded, 6-month move before the gap, distance from the 52w high, above/below the 200d, industry, plus the latest headline from Massive (max 8 lookups a run; published within 48 h or since the previous session day, whichever reaches further back). Breakouts: prior move, 3/6M return, 52w high, ADR, MA stack, growth. One extra TradingView request for the pushed names; if it fails, alerts go out without facts. Headlines are dropped first when a message nears ntfy's 4 KB limit | `context:` |
| 17 | EP9M pace during the session (Emil chose this, 19 Oct) | 10:15 and 12:00 New York; change ≥ +4% and volume so far or pace ≥ 9M; pace = TradingView relative volume at time (5-minute) × the RVOL base (60-day average, today excluded); alert tier as EP9M (no signal-day dollar-volume guard, which only applies at the close); a name pushes once a session; entry at the last price, stop at the day's low within the EP ADR bounds | `scans.ep9m_pace`, `schedule.windows_et.am/mid` |

Still open (no default possible):
- **Data repo size:** each trading day adds ~3 MB of Parquet (pre-market + EOD universe snapshots, zstd), about 0.75 GB a year in git. Fine for the first years; later options are a slimmer pre-market snapshot or moving old Parquet to release assets / object storage. No action needed now.
- Your manual EP-Day screen: does it filter on TradingView's "Relative Volume" (10-day) and have "Primary listing" on? Both change which names appear; `docs/validation.md` shows both RVOL columns, and `scripts/compare_screen.py` explains each difference.

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
