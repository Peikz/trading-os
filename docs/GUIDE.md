# Trading OS — guide

How the system works, what every scan and study does, and what each dashboard page shows.
The exact numbers live in `config/scans.yaml` (one place for every threshold); this guide
quotes the current values. Facts, not advice: the system finds and measures; you grade and
decide.

**Contents**
1. [What it is](#1-what-it-is)
2. [The day: jobs and schedule](#2-the-day-jobs-and-schedule)
3. [Data: where it comes from and where it lives](#3-data-where-it-comes-from-and-where-it-lives)
4. [Universe and tiers](#4-universe-and-tiers)
5. [The scans](#5-the-scans)
6. [Market breadth and the Market Light](#6-market-breadth-and-the-market-light)
7. [Push messages](#7-push-messages)
8. [Position size, facts and watchlists](#8-position-size-facts-and-watchlists)
9. [The studies](#9-the-studies)
10. [Journal: trades, plans, review](#10-journal-trades-plans-review)
11. [The dashboard, page by page](#11-the-dashboard-page-by-page)
12. [Phone access](#12-phone-access)
13. [Glossary](#13-glossary)
14. [Changing things](#14-changing-things)

---

## 1. What it is

A personal momentum scanner for US stocks in the style of Qullamaggie and Stockbee. Every
weekday it screens the whole US market, saves every hit, pushes the best ones to your phone,
and keeps the history so every rule can be measured.

Ground rules:

- **No AI at runtime.** Scans are plain Python on GitHub Actions: same input, same output.
- **Collect broadly, alert narrowly.** Every hit of every scan is saved; only EP and breakout
  hits that pass the alert tier are pushed.
- **Point in time.** A row is stored as it was known when the scan ran, never rewritten.
- **The human grades.** Code never gives a trade grade or a buy/sell verdict.
- **Private data stays private.** The code repo is public; all data (scans, journal, account)
  lives in the private data repo. Public job logs print counts only.

## 2. The day: jobs and schedule

All times New York (ET). Each job has two cron times (US summer and winter time) and a guard
that runs it only inside its window; a run that already saved its output exits.

| Job | Window | What it does |
|---|---|---|
| Pre-market | 07:15–07:55 | EP-PM, early EP9M, watchlist gappers; today's Market Light from the last close |
| Intraday checks | 10:10–11:30 and 11:55–13:30 (runs 10:15, 12:00) | EP9M on pace for the day's volume; BO-Watch names at their pivot |
| EOD | 16:15–23:59 | All end-of-day scans, breadth, Market Light, charts, report, push |
| Weekly | Sunday 18:00 Copenhagen | QM gainers, growth buckets, tight bases, the Sunday scan count |
| Outcomes | 22:00 UTC weekdays | Fills in what happened 5/10/20/60 sessions after each signal |
| Backfill | 09:30 UTC Tue–Sat | Adds the previous session's daily bars (Massive) |
| Keepalive | monthly | Keeps GitHub from switching off the scheduled jobs |

GitHub sometimes starts scheduled runs late (on 19 Oct 2026 by up to six hours). A run that
starts after its window does nothing, which is why the EOD window runs to midnight and has a
third, later cron. The **System health** page shows every miss. A run started by hand
(`force`) skips the guard and saves under `data/manual/`, shown as "(manual HHMMSS)" with the
start time in UTC.

## 3. Data: where it comes from and where it lives

| Source | Used for |
|---|---|
| TradingView screener | The live universe at every run: price, change, gaps, volumes, fundamentals, pre-/after-market |
| Massive (free plan) | Daily bars for the last 2 years (exact history metrics), news headlines, ticker list incl. delisted and their types |
| Alpaca (free plan) | Daily bars since 2016 and minute bars for the studies (full SIP feed) |
| SEC EDGAR | Exact earnings release times (8-K item 2.02) and quarterly EPS/revenue as filed |

The private data repo (`trading-os-data`) holds the runs (`data/universe`, `data/candidates`,
`data/manual`), breadth, charts, reports, watchlists, the journal and your settings. Large
study data lives only in its releases on GitHub, not in git and not on your PC:
`bars-2y` (the last two years of daily bars as small per-letter files, refreshed each morning
at 10:15 UTC), `bars-alpaca` (daily bars per year since 2016, adjusted for splits and
dividends), `bars-alpaca-raw` (the same stock-days at the prices they really traded at, with
the factor between the two: a price floor or a per-share cost needs these, not the adjusted
bars), `intraday-minutes` (minute bars and their index), `intraday-2y`, `intraday-10y`,
`history-10y`, `regime-10y`.

Your PC keeps a slim copy of the data repo: only the latest version of each file (no
history) and without the per-session bar files, which only the GitHub jobs read. Recreate it
with `git clone --depth 1 --filter=blob:none --sparse` and the sparse patterns `/*`,
`!/data/bars/`, `!/data/ep_enrich/`, `/data/ep_enrich/tickers.parquet`. The dashboard fetches just what a
page needs into a cache (`%LOCALAPPDATA%	rading-os-cache`, at most 1.5 GB, least used files
dropped first); **System health → Empty the cache** clears it.

## 4. Universe and tiers

The universe is US-listed common stock and ADRs (no OTC, preferreds, units, warrants, rights,
ETFs or ETNs). Two tiers:

- **Logged tier** (everything saved): price ≥ $0.50, market cap ≥ $50M, 20-day average dollar
  volume ≥ $500K.
- **Alert tier** (can be pushed): price ≥ $1, market cap ≥ $50M, 20-day average volume ≥ 500K
  shares, and for end-of-day signals at least $5M traded that day.

## 5. The scans

### Pre-market (07:15–07:55)

| Scan | Rule |
|---|---|
| EP-PM | Up ≥ 10 % pre-market, ≥ 50K pre-market shares, price ≥ $1, market cap ≥ $50M |
| EP9M early | ≥ 500K pre-market shares and up ≥ 4 % pre-market: a possible EP9M |
| Watchlist gappers | Names on BO-Watch or EP-Watch up ≥ 2 % pre-market |

### End of day

| Scan | Rule | Pushed |
|---|---|---|
| **EP-Day** (episodic pivot) | Opening gap ≥ 10 %, RVOL ≥ 3, volume ≥ 300K, price ≥ $1, market cap ≥ $50M | yes |
| EP-AH | After-hours move ≥ 8 % (switched off) | — |
| **EP9M** | Volume ≥ 9M shares and up ≥ 4 % | yes |
| Momentum Burst up | Up ≥ 4 % on more volume than the day before, ≥ 100K shares, close in the top 30 % of the range | logged |
| Momentum Burst down | Down ≥ 4 % on more volume than the day before, ≥ 100K shares | logged |
| Parabolic short | Up ≥ 50 % (≥ $1B market cap) or ≥ 200 % (smaller) within 10 days, 3+ up days in a row | logged |
| Parabolic long | Down ≥ 30 % within 10 days, 3+ down days in a row | logged |
| **BO-Watch** | A base that passes B1–B4 (below) | yes |
| **BO trigger** | B5 at the close over the pivot of the base that ended the day before | full setups yes |

### Intraday (10:15 and 12:00)

- **EP9M pace**: up ≥ 4 % and 9M shares traded or on pace for it (TradingView's relative
  volume at that time of day × the stock's normal daily volume).
- **BO pivot**: BO-Watch names within 1 % of their pivot or over it. A name pushes once a
  session.

### Weekly (Sunday)

- **QM gainers**: the top 2 % by 1-, 3- and 6-month return, ADR ≥ 4 %, 20-day dollar volume
  ≥ $10M, price > $5 (Qullamaggie's screens).
- **Growth buckets**: revenue growth ≥ 40 % for two quarters (bucket 1); EPS growth ≥ 40 % and
  revenue growth ≥ 20 % for two quarters (bucket 2).
- **Tight bases**: within 15 % of the 52-week high, ADR ≥ 4 %, above the 50-day MA, the last
  10 days' range under 1.5 ADR on drying volume.
- **CATS** ranks QM gainers and tight bases: a point each for a growth bucket, a recent MB/EP
  signal and rising volume, minus points for being stretched far above the 10-day MA.

### The breakout criteria (B1–B5)

The base runs from the highest high of the last 40 sessions (the **pivot**) to today.

| | Means | Rule |
|---|---|---|
| B1 | prior move | up ≥ 30 % within 1–3 months before the base |
| B2 | base | 10–40 sessions, ≥ 2 pullbacks each ≤ 0.85× the one before, higher lows, quiet volume |
| B3 | trend | close above the 10- and 20-day MAs, both rising |
| B4 | tight right side | the last 5 sessions' range < 1.5 ADR, volume below average |
| B5 | trigger | close over the pivot, day range > 1 ADR, RVOL ≥ 1.5 |

Order stop = the higher of the last pullback low and pivot − 1 ADR. BO-Watch = B1–B4 all pass;
the trigger push gives full blocks only to triggers with B1–B4 and lists the top five B5-only
triggers as one line each.

## 6. Market breadth and the Market Light

**Breadth** (Stockbee Market Monitor), stocks over $5 with ≥ 100K shares: stocks up/down
≥ 4 % on rising volume today, their 5- and 10-day ratios, stocks up/down ≥ 25 % in a quarter
and in a month, ≥ 50 % in a month, ≥ 13 % in 34 sessions, and the share above the 20/40/50-day
MAs.

**The Market Light** (your rules, SPEC §6.5), from three inputs:

- **QQQ trend**: *up* when the close is over the 20-day MA and the 10-day is over the 20-day;
  *down* when the close is under the 50-day MA and the 20-day is lower than 5 sessions ago;
  else *sideways*.
- **Breadth state**: *strong* when the 10-day ratio ≥ 1.5 and more stocks are up 25 % in a
  quarter than down; *weak* when the 10-day ratio < 1.0 and more are down (unless a 5-day
  ratio over 2.0 makes it *neutral*); else *neutral*.
- **Scan count**: the Sunday screen (price > $5, 30-day average volume > 500K, up ≥ 50 % in a
  quarter, above the 20-day MA).

First match wins: **STOP** (QQQ down and breadth weak, or count < 5), **RED** (QQQ down, or
breadth weak, or count < 15), **GREEN** (QQQ up, breadth not weak, count ≥ 50), else
**YELLOW**. The market panel also shows SPY and QQQ (change and MA position) and VIX.

## 7. Push messages

Sent through ntfy to your phone after each run that has something (the intraday checks also
send "no alerts" so you know they ran). Layout, top to bottom: the title with counts, the
market panel, then one block per scan with the stocks, each with its facts line and the
entry/stop/size line. Colours: 🟢/🔴 counts and moves, 🟩/🟥 B-flags (legend line under each
breakout block), 🛑 stop, 📢 earnings. The grey lines at the end say what was left out and why
("N without B1-B4", "N sent earlier", "N below alert tier"). Up to 10 stocks per scan; if the
message gets near ntfy's 4 KB, news goes first, then facts, then the last stocks ("… N more in
the report"). Tap the message to open the full report.

## 8. Position size, facts and watchlists

**Size**: every pushed EP and breakout gets entry, stop, shares, position and risk in USD,
from your account settings (private, `settings/account.yaml`) at the live USD rate. EP: entry
at the close, stop at the day's low, at least 0.25 and at most 1 ADR below. Pre-market: 1 ADR
below. Breakouts: the order stop.

**Facts** (top 5 per scan, never a verdict): earnings timing and growth, float traded, the move
before, distance to the 52-week and all-time high, the 200-day, RS, industry rank, earnings
coming up, and for EPs the latest headline.

**Scan watchlists**: EP-Watch holds alert-tier EP-Day and EP-PM hits for about 3 months (63
sessions); BO-Watch holds bases passing B1–B4, refreshed each day they qualify, marked when
they trigger, and dropped after 10 sessions without qualifying.
**Your own watchlists** live next to them (section 11).

## 9. The studies

All studies replay the same rules on history. **R** = profit in units of the starting risk
(entry minus stop); a stopped trade is about −1R. Means are capped at 20R per trade so one
runner can't carry a group; medians show the typical trade. No commissions or slippage.

- **EP history** (2 years): every EP-Day and EP9M hit with its features (gap, RVOL, months
  sideways, earnings, growth, the five EPStudyDatabase criteria C1–C5) and the outcome after 1
  day to 1 year.
- **Strategy history** (2 years, Massive; 10 years, Alpaca): every hit of every scan, entered
  at the signal close with the strategy's own stop, measured after 1/5/21/63 sessions, with
  trailing exits (close under the 10/20-day MA or EMA 9/21) and managed exits (Qullamaggie: a
  third after 3–5 days, then a trail; Stockbee: out after 3–5 days or at +8 %).
- **Study-only setups** (not live scans):
  - **Martin Luk**: pullback to EMA 9/21 in a leader, AVWAP flush, inside day (rules from
    interviews, marked proposed).
  - **Minervini**: the Trend Template and a mechanical VCP (shrinking contractions, drying
    volume, stop at most 8 %).
- **Minute study** (entries and exits): each strategy bought at different times on minute
  bars — after hours, pre-market, the open, opening-range breakouts, set times, the close, the
  next day — and each entry chosen **only with what was known at that minute** (picking EPs by
  the day's close and buying them at 09:31 would skip every gap that faded). Stops: the low so
  far, 1 ADR, or the setup's own; every trade run with every exit. 2 years with all trades, 10
  years as summaries.
- **Market regime** (10 years): every trade matched to the regime known before it was entered
  (Market Light, QQQ trend, breadth state, SPY/QQQ against their MAs) to see whether skipping
  bad markets helps.

## 10. Journal: trades, plans, review

- **Fills are the record.** Import your broker's CSV export, or log a fill by hand (date,
  ticker, buy/sell, shares, price, fees, setup, initial stop). A later broker fill replaces
  the matching hand-logged one.
- **Trades** are built from the fills, flat to flat per ticker (long or short), with P&L after
  fees and R from your logged stop, else the linked scan signal's stop.
- **Plans** are made before a trade: entry, stop and a share count suggested from your risk per
  trade. A plan turns *filled* when a matching entry fill arrives within 5 sessions (showing
  slippage in % and R), else *expired*; you can cancel it.
- **Review**: the best and worst price during each trade (MFE/MAE, in R), how much of the best
  move you kept, a chart with your fills, a grade, notes and screenshots, and your real R per
  setup next to what the studies got.

## 11. The dashboard, page by page

The sidebar has the page list, the data folder, "Show manual test runs", **Pull latest**
(fetch the newest runs from GitHub) and **Save & push** (send your grades, notes, journal and
watchlists to the private repo).

| Page | What it shows |
|---|---|
| **Today** | The market panel (Market Light, breadth, SPY/QQQ/VIX) and the newest run's pushed scans with facts, charts and TradingView links |
| **Screens** | Any run, any scan, both tiers: the full table, an interactive chart, Open in TradingView, and the grading form (grade, notes, screenshots) |
| **Chart** | Any stock, interactive (drag to pan, scroll or pinch to zoom): daily or weekly candles with volume, 2 or 10 years, MA 10/20/50/200 and EMA 9/21, the scans' past hits (amber triangles, hover for the scan), your buys and sells, today's pivot and stops; anchored VWAPs (from the highest high, the lowest low, the year start, the latest scan hit, or any day you save); trend lines, saved per stock in the data repo as you draw them on the daily bars (the line tool, top right; drag a line or its ends to move it, click it and use the eraser to delete it; a line drawn past the last bar keeps extending each day; or type one in through two points); and an intraday view of any day with minute bars (1/5/15-minute candles, VWAP from the open, pre-/post-market shaded) |
| **Watchlists** | Your own lists (add by typing or a TradingView export; each ticker with close, change, RVOL, ADR, RS, distance to the high and pivot, earnings, today's scans) and the scans' EP-Watch and BO-Watch |
| **Journal** | Tabs: *Open positions* (open P&L, open R, money at risk to the stops), *Log a trade*, *Plans*, *Closed trades* (stats, R curve, MFE/MAE, review chart, grading), *Real vs study* |
| **Graded signals** | The signals you graded, with what happened after |
| **Market** | Breadth history: the 5- and 10-day ratios over time |
| **Stats** | Outcome statistics of the live signals per scan |
| **History** | Every strategy's history (2 or 10 years): win rate and median move after 1/5/21/63 sessions, R, the exits compared, splits by year/market/price (EP-Day adds its own filters), the events and their charts |
| **Entries & exits** | The minute study: the best entry, stop and exit per strategy; every combination with any exit; splits; the trades (2 years) or the summaries and a by-year table (10 years) |
| **Market regime** | How often each light occurred per year, and for any strategy every filter's effect on trades kept, mean R and win rate, overall and per year |
| **System health** | Which scheduled job ran for which session, data freshness, failure logs, and how late GitHub started each run |
| **Validation** | Compare a run with a TradingView screener export and record it in `docs/validation.md` |
| **Guide** | This page |

## 12. Phone access

The dashboard runs on your PC (`scripts\start_dashboard.ps1`, or http://localhost:8501).
With Tailscale on the PC and the phone (same account), it is shared only with your own devices
at `http://<pc-name>.<tailnet>.ts.net`. Open the Tailscale app, switch it on, then open that
address in Safari (Share → Add to Home Screen for one tap). The PC has to be on.

## 13. Glossary

| Term | Meaning |
|---|---|
| ADR | Average daily range (20 days), in % or $: how far a stock usually moves in a day |
| RVOL | Today's volume against the usual (50-day average, today excluded) |
| EP | Episodic pivot: a big gap on news and heavy volume |
| EP9M | Stockbee's 9-million-share day: up ≥ 4 % on ≥ 9M shares |
| MB | Momentum Burst: a ≥ 4 % day on rising volume |
| Pivot | The high a breakout has to clear |
| ORH / ORB | Opening-range high / breakout: the high of the first N minutes, and buying its break |
| LOD | Low of day (here: the low so far at the entry) |
| R | Profit or loss in units of the starting risk |
| MFE / MAE | Best / worst price reached during a trade |
| EMA / MA | Exponential / simple moving average |
| VWAP | Volume-weighted average price: intraday from the 09:30 open |
| AVWAP | VWAP anchored at a chosen day (a gap, a base high or low), from each day's VWAP and volume |
| VCP | Volatility contraction pattern (Minervini) |
| SIP / IEX | Alpaca's full-market feed / one exchange's feed (a small slice of the volume) |

## 14. Changing things

- **Thresholds and rules**: `config/scans.yaml` (values marked *proposed* are defaults waiting
  for your confirmation). A scan that isn't in SPEC.md isn't added without a SPEC entry.
- **Your account and risk**: `settings/account.yaml` in the private data repo.
- **The spec and decisions**: `SPEC.md`; open items and history: `BACKLOG.md`.
