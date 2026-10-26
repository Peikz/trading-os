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

All times New York (ET). A timer at cron-job.org starts each job on the minute (below); GitHub's
own schedule, two cron times per job for US summer and winter time, is the backup. Each job has
a guard that runs it only inside its window, and a run that already saved its output exits, so
the extra starts are harmless.

| Job | Window | What it does |
|---|---|---|
| Backfill | starts 05:30 Tue–Sat | Adds the previous session's daily bars (Massive) |
| Bars pack | starts 06:15 Tue–Sat | Packs the last 2 years of daily bars into the dashboard's compact files |
| Pre-market early (26 Oct 2026) | 11:00–12:30 **Copenhagen** (starts 11:30 Copenhagen) | The same pre-market push early ("Pre-market early"): last night's setups, the market head, and gappers that already have the volume. Saved under `data/manual/`, so the 07:17 run stays the full one |
| Pre-market | 07:15–07:55 (starts 07:17, again 07:35) | EP-PM, early EP9M, watchlist gappers; today's Market Light from the last close |
| Intraday checks | 10:10–11:30 and 11:55–13:30 (starts 10:17 and 12:03, again 10:40 and 12:30) | EP9M on pace for the day's volume; EP gaps to buy around 10:30 (10:17 check only); BO-Watch names at their pivot |
| EOD | 16:15–23:59 (starts 16:17, again 17:00) | All end-of-day scans, breadth, Market Light, charts, report, push |
| After-hours check | 16:40–17:10 (starts 16:50, again 16:56) | EP-AH: earnings movers after the close, to buy before 17:00 (Saxo's extended hours end) |
| Outcomes | starts 18:00 weekdays | Fills in what happened 5/10/20/60 sessions after each signal |
| Weekly | Sunday, starts 12:00 (18:00 Copenhagen) | QM gainers, growth buckets, tight bases, the Sunday scan count |
| Live check | the 1st of each month | The live A+ / A / B signals against the grading study, split by the IBD market state too, and your trades against their plan (section 11, Live results) |
| Jobs log (26 Oct 2026) | once a day | The open-job count of ~480 listed companies' job boards, saved to `data/jobs/`, to test hiring growth as an EP variable once there is history |
| Keepalive | monthly | Keeps GitHub from switching off the scheduled jobs |

**Price alerts** (since 22 Oct 2026): GitHub Actions (`alerts.yml`, started by the timer at 09:25 and 12:45 New York) checks every minute of the session (15:30–22:00 Copenhagen) and pushes once when a price is hit: 🎯 last close's BO-Watch and MA-surf names over their pivot (with the plan's stop), 🛑 an open position at its stop, 🔔 your own alerts from the Watchlists page (they end once fired). Prices come from Alpaca's free real-time IEX feed, so the alerts are on price only. It uses the repo's secrets, so nothing runs on your PC; what fired is saved to the data repo when each run ends. To run it on the PC instead: `scripts\set_local_secrets.ps1` once, then `scripts\start_alerts.ps1`. Nothing places orders.

GitHub starts its scheduled runs late, on 19–20 Oct 2026 by 2½ to 6½ hours, so pre-market and
the intraday checks never ran inside their windows. A run that starts after its window does
nothing. That is why the timer exists, and why the EOD window runs to midnight. The **System
health** page shows, per job, when the timer fired and when GitHub started it, and every miss. A run started by hand
(`force`) skips the guard and saves under `data/manual/`, shown as "(manual HHMMSS)" with the
start time in UTC.

### The timer (cron-job.org)

A free cron-job.org account calls GitHub's API at each start time above (New York time, so
summer and winter time take care of themselves), and emails you when a call fails. The start
times live in `trading_os/timer.py`; `scripts/timer_setup.py` creates the jobs there. Setup,
once:

1. Make a free account at cron-job.org. In its Console, **Settings → API**: create an API key.
2. On GitHub: **Settings → Developer settings → Fine-grained tokens → Generate new token**.
   Repository access: *Only select repositories* → `trading-os`. Permissions: *Actions: Read and
   write* (nothing else). Expiry: up to a year; note the date.
3. Store both keys as secrets of the code repo, in a terminal in the Trading-OS folder (paste
   each at the prompt; it isn't shown):
   `gh secret set CRONJOB_API_KEY -R Peikz/trading-os` and
   `gh secret set TIMER_GITHUB_TOKEN -R Peikz/trading-os`.
4. Start the **Timer sync** workflow once (Actions → Timer sync → Run workflow, or
   `gh workflow run timer-sync.yml -R Peikz/trading-os`). Its log lists the 14 jobs at
   cron-job.org. The next trading day, System health → *Load the latest runs from GitHub*
   should say ✅ on time.

From then on the sync is automatic (since 21 Oct 2026): whenever `trading_os/timer.py` changes on
main, the Timer sync workflow updates the jobs at cron-job.org by itself, and a failed sync sends
a push. Running `uv run python scripts/timer_setup.py` on the PC still works too (it asks for
the two keys).

The token can do nothing but start, cancel and re-run jobs in the public code repo; it can't
read the data repo or any secret. When it expires, every call fails: cron-job.org emails you,
System health shows every job ❌ missed, and GitHub's own (late) schedule carries on. Make a new
token, put it in the secret TIMER_GITHUB_TOKEN (step 3) and start Timer sync (step 4). If the
cron-job.org API key is limited to certain IP addresses, the sync from GitHub is refused: leave
the key unrestricted.

## 3. Data: where it comes from and where it lives

| Source | Used for |
|---|---|
| TradingView screener | The live universe at every run: price, change, gaps, volumes, fundamentals, pre-/after-market |
| Massive (free plan) | Daily bars for the last 2 years (exact history metrics), news headlines, ticker list incl. delisted and their types |
| Alpaca (free plan) | Daily bars since 2016 and minute bars for the studies (full SIP feed) |
| SEC EDGAR | Exact earnings release times (8-K item 2.02) and quarterly EPS/revenue as filed; the bulk files for 10 years of fundamentals |

The private data repo (`trading-os-data`) holds the runs (`data/universe`, `data/candidates`,
`data/manual`), breadth, charts, reports, watchlists, the journal and your settings. Large
study data lives only in its releases on GitHub, not in git and not on your PC:
`bars-2y` (the last two years of daily bars as small per-letter files, refreshed each morning
at 10:15 UTC), `bars-alpaca` (daily bars per year since 2016, adjusted for splits and
dividends), `bars-alpaca-raw` (the same stock-days at the prices they really traded at, with
the factor between the two: a price floor or a per-share cost needs these, not the adjusted
bars), `intraday-minutes` (minute bars and their index), `intraday-2y`, `intraday-10y`,
`history-10y`, `regime-10y`, `sec-10y` (SEC fundamentals since 2015, point in time:
earnings events with their reaction session, quarterly EPS/revenue/net income, shares
outstanding, companies with a sector from SIC, and the ticker-to-company map; joined to any
stock-day with `sec_bulk.pit_join`).

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
| **EP9M** | Volume ≥ 9M shares and up ≥ 4 % | yes |
| Momentum Burst up | Up ≥ 4 % on more volume than the day before, ≥ 100K shares, close in the top 30 % of the range | logged |
| Momentum Burst down | Down ≥ 4 % on more volume than the day before, ≥ 100K shares | logged |
| Parabolic short | Up ≥ 50 % (≥ $1B market cap) or ≥ 200 % (smaller) within 10 days, 3+ up days in a row | logged |
| Parabolic long | Down ≥ 30 % within 10 days, 3+ down days in a row | logged |
| **BO-Watch** | A base that passes B1–B4 (below) | yes |
| **BO trigger** | B5 at the close over the pivot of the base that ended the day before | full setups yes |
| **EP9M AVWAP** (26 Oct 2026, grade B) | A stock that was an EP9M A+ in the last 2–15 sessions comes back to the VWAP anchored at that day's open: the low touches it, the close holds over it (the first such day). Pushed at EOD and again pre-market; bought at the next open, stop under the signal day's low (at most 2 ADR), out after 21 sessions | yes |

### Intraday (10:15, 12:00 and 16:50)

- **EP9M pace**: up ≥ 4 % and 9M shares traded or on pace for it (TradingView's relative
  volume at that time of day × the stock's normal daily volume).
- **EP 10:30** (10:15 check): an opening gap ≥ 10 %, price ≥ $1, market cap ≥ $50M. Graded
  by the EP quality count; the plan buys around 10:30 New York (16:30 Copenhagen).
- **EP-AH** (16:50 New York, 22:50 Copenhagen): up ≥ 8 % after hours on ≥ 50K shares, on an
  earnings release that day. Graded by the EP quality count; the plan buys at the after-hours
  price before Saxo's extended hours end at 17:00 New York. The 15:45 EP close check is off
  since 21 Oct 2026: the close was the weakest EP entry in the study.
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

**The QQQ light** (Qullamaggie's rule; the push's first line since 25 Oct 2026): 🟢 GREEN when
QQQ's 10- and 20-day both rise and the 10 is over the 20, 🔴 RED when both fall and the 10 is
under the 20, 🟡 YELLOW otherwise. GREEN = a momentum market, the most breakout chances (2-3
breakouts a day went 10R+ in the study); RED = few breakout winners, momentum mostly off. It is
not a stop: EP, EP9M and Luk flush did as well or better on RED, and stopping on red cost money
in every test.

**The IBD market state** (O'Neil; since 26 Oct 2026, tracked, not a rule): a distribution day is
SPY down at least 0.2 % on more volume than the day before; 6 of them in 25 sessions start a
correction, and a follow-through day (day 4 or later of a rally off the low, SPY up 1.25 % on more
volume) starts an uptrend. Every signal carries the state (the report's IBD column and market
line, the dashboard's tiles and tables; the push leaves it out), and the monthly live check
splits the live trades by it. In the study MA-surf A and EP9M A+ did better in an uptrend, but
that was found with both periods in view and 2006–15 didn't confirm it, so grades don't use it.

**The Market Light** (your rules, SPEC §6.5; since 25 Oct 2026 in the report and on the dashboard only), from three inputs:

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

**Study grades** (since 20 Oct 2026): every pushed hit carries a grade from the 10-year grading
study of these rules (net of Saxo costs, walk-forward by year; report in the data repo's
`docs/research/`). Only EP gaps bought at the close (A/B), Luk's AVWAP flush (A/B) and EP9M at
the 12:00 check (B) showed an edge after costs; every other scan grades C. A+/A: a full block with
when to buy, the stop (1 ADR), the exit (the close after 21 sessions, the stop resting) and the
expected hold, the history behind the grade, and the size (your risk x 2 / 1.5 / 1 for A+ / A /
B). B: one line. C: saved and counted in the closing line. The Luk AVWAP flush is a live EOD scan
since the same day. Rules: config `grading:`; code: `grader.py`, `grade_live.py`.

**Quality grades** (since 21 Oct 2026, in place of the scorecards above): a grade is the number
of yes/no points a setup has. EP and EP9M: an earnings release (EP9M: in the last 10 sessions),
1–2 months sideways, a market that isn't hot (fewer than 45 stocks up 50 % in a quarter),
revenue growth accelerating, EPS up year on year, within 20 % of the 52-week high; 5–6 points =
A+; 4 points or fewer is C for both (saved, not pushed as a trade: an EP with 4 is about
break-even, and EP9M with 4 as a B trade halved the account's result in the study). Luk flush: a market that isn't hot and a tight 5-day range = A. MA-surf (since 23 Oct 2026): SPY closed over its 200-day average on the signal day = A at 0.75 % risk, else C. Since 25 Oct 2026, any A+ or A in a stock with 5 or more days to cover (FINRA's twice-monthly short interest) is shown as C, "heavily shorted", and every hit at 5+ days, C included, gets a ⚠️ heavily shorted line: in the study those trades lagged, and skipping them raised the account's return in both periods. The push says
"N of M quality points" and shows the history of that grade at that entry:

| Push | When to buy |
|---|---|
| 🌙 EP-AH (16:50 New York check, and again in the next pre-market push since 23 Oct 2026) | after hours now, before 17:00 New York (23:00 Copenhagen). The morning copy shows the pre-market price and move against last night's after-hours price; the buy time has passed, so it has no Saxo ticket |
| ⚡ EP 10:30 (10:17 check) | around 10:30 New York (16:30 Copenhagen); "flagged last evening" if the 16:50 check already sent it |
| ⏱️ EP9M pace (10:17 check) | after the 10:15 check (16:15 Copenhagen) |
| 🌊 Luk flush (EOD, and again in the next pre-market push with its pre-market move) | the next session around 10:30 New York (16:30 Copenhagen) |
| 💥 MB up, ↩️ Luk pullback, 🌀 VCP (found at the close, pushed the next pre-market since 22 Oct 2026, grade C) | each with its study plan under the section and a 🌡 heat line: how that setup did at today's market heat on both test periods (held, mixed, lost or few trades). Minervini's Trend Template is saved as a daily list (Screens), not pushed |
| 🎯 BO-Watch, 🏄 MA-surf, 🪂 Parabolic long, 🎢 Parabolic short (found at the close, pushed the next pre-market at 07:17 New York / 13:17 Copenhagen, grade C except MA-surf with SPY over its 200-day; since 21 Oct 2026) | each line shows the pre-market price and move, the move against the pivot, and ⚠️ when it is already up more than 1 ADR. The study plan sits under each section header. Parabolic long: buy at the open, stop 1 ADR under, out after 21 sessions. Parabolic short: short around 10:30, stop over the signal day's high, cover on a close over the 20-day MA |
| 🏄 MA-surf (found at EOD, pushed the next pre-market; A when SPY is over its 200-day, else C, since 23 Oct 2026) | the next session from 10:00 New York (16:00 Copenhagen): over the pivot buy, under it a buy-stop at the pivot; stop under the base's right side; sell on a close under the 20-day MA |

| ⚓ EP9M AVWAP (EOD, and again in the next pre-market push; grade B since 26 Oct 2026) | at the next open, 09:30 New York (15:30 Copenhagen); stop under the signal day's low (at most 2 ADR); out at the close after 21 sessions |

**What the grades mean** (Emil, 26 Oct 2026): **A+ / A** raised the account's return in both test
periods (full size: your risk × 2 / 1.5). **B** has an edge per trade but wasn't proven to add to
the account on top of the A+ trades (half the A+ size: your risk × 1; EP9M AVWAP is the one B
today). **C** had no edge after costs (saved and counted, not a buy). The monthly live check
covers A+, A and B and decides whether a B moves to A or C.

The points were partly chosen with 2022–26 in view, so they flatter those years; rules picked
blind on 2016–21 do worse (research report §9, portfolio report §11–12).

**Market heat** (since 21 Oct 2026): the market lines of the pre-market, EOD and Sunday pushes
end with today's heat band, from the latest Sunday scan count: cool under 18, mild 18–44, warm
45–80, hot over 80. Heat is the one market variable that held up when tested blind. Three lines:

- `🌡 Warm market (count 60, 45-80) · net R a trade 2016-21/2022-26:`
- `A:` the graded setups at this heat, net R a trade in each period and the number of trades.
- `Held here too (C):` the setups without a grade that made money per trade and per signal day
  in both periods at this heat, with 30+ trades in each. "No other setup held" when none did.

These are facts about past rules, not grades. A C setup that held is still C: in the account,
adding the cool-market C setups lowered the return every way it was tried. The Market page has
the full table for every heat. Rebuild it after the grading study changes:
`uv run python scripts/heat_stats.py --data-dir ../trading-os-data`.

**Managing your positions** (since 22 Oct 2026): the pre-market and EOD pushes carry a 💼 block
for your open positions (from the journal): risk to stops and average R, then one line each with
R so far and what its plan says. EP, EP9M, Luk flush and parabolic long hold 21 sessions: the
morning push says "day 21/21: the plan sells at today's close", the evening before says
"tomorrow". MA-surf and breakouts trail the 20-day MA, a parabolic short covers over it: the EOD
push names a close through it. 📢 marks earnings within two sessions. With Saxo connected
([SAXO.md](SAXO.md)) the stop is your working stop order at Saxo.

**The Saxo ticket**: every A+/A plan, and every pivot buy (BO-Watch, MA-surf), ends with a 🎫 line
to type into Saxo's order ticket: order type, amount, price, duration and the stop loss (an
extended-hours limit for EP-AH, a market order at the plan's time, a stop if traded at the pivot).
Nothing is ever sent to Saxo by the system.

**The job check**: the EOD push has one 🩺 line on the timed jobs since yesterday: all on time,
or which were late, missed or failed.

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

- **Daily notes** (since 22 Oct 2026, Journal → *Daily notes*): a note about the day, tagged with the stocks it is about (the tag field, or `$TICKER` in the text). Filter by stock or by how far back. A tagged note also shows on each tagged stock's Chart page under its notes ("From your daily notes"). Kept for good like the stock notes: an edit or delete adds a row.
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

The sidebar has the page list, ordered by the trading day (since 26 Oct 2026): ☀️ before the open
(Today, Market, Watchlists, Screens), ⚡ live (Positions, Chart, Scans), 🌙 after the close
(Journal, Live results), 🔬 research (Research, System health, Guide). Below it: the data folder,
"Show manual test runs", **Pull latest** (fetch the newest runs from GitHub) and **Save & push**
(send your grades, notes, journal and watchlists to the private repo). The dashboard has a dark
theme.

| Page | What it shows |
|---|---|
| **Today** | The **candidate board** (26 Oct 2026): the newest runs' A+ / A / B signals first (C behind *Show C*). The *Focus view* shows one at a time with a fast TradingView-style chart (TradingView's free Lightweight Charts: candles, volume, MA 10/20/50, the plan's entry and stop; top left the ticker, 1D, the exchange, O H L C and the MA values, following the crosshair) next to its card: the grade, when to buy, entry, stop, shares, risk, its tags (heat, heavily shorted, IBD), its 2016–26 history and the **Saxo ticket**. *Show* picks what you flip through: the A+ / A / B (default), everything pushed incl. C, every scan hit (all scans and tiers, one row per stock) or your own watchlists. Flip with ◀ ▶ or the **arrow keys**. Three views: *Focus* (one at a time), *Grid* (four charts at once, the arrows page by four) and *List* (all cards). Above the chart: **1D / 1W** bars and the indicators to show (MA 10/20/50/200, EMA 9/21, an **anchored VWAP from the signal day**, an **RS line against QQQ** in its own band), remembered while the page is open. Under it, the **key stats**: market cap, ADR, 20-day dollar volume, float, distance to the 52-week high, RS percentile, the industry and its rank, and earnings. **Hotkeys**: ← → flip, **W** daily/weekly, **F** flags the stock green (to the 'Flag green' watchlist), **N** points to the note, **T** shows or hides the ticket. The side panel has three tabs: *Plan* (the card and ticket), *List* (the whole queue; click to jump, like TradingView's watchlist) and *Notes & alerts* (🟥 🟨 🟩 flags to matching watchlists, a note on the stock, a price alert that pushes to your phone when hit, defaulting to the pivot or entry). The fast chart has no drawing tools: drawing stays on the Chart page. The ticket starts with the plan's order type (market at the plan's time, a buy-stop at the pivot, an extended-hours limit, market on close) and can switch to limit, buy-stop or stop-limit or an own price; shares keep the grade's risk; every value has a copy button; *Placed in Saxo* saves it as a plan so your fill matches it. Under the board: the market as tiles (QQQ light, heat, IBD state, SPY, QQQ, VIX; the full lines under *Market details*) and every pushed scan's table, folded per run |
| **Positions** (26 Oct 2026) | A card per open position: the price (live from Alpaca when its keys are on the PC, else the last close), open R and P&L, the distance to the stop, and what the plan says today (day k of 21, or a close under the 20-day MA), with earnings within two sessions flagged |
| **Screens** | Any run, any scan, both tiers: the full table with each hit's study grade and the A+/A/B blocks, an interactive chart, Open in TradingView, and your own grading form (grade, notes, screenshots) |
| **Chart** | Any stock, interactive (drag to pan, scroll or pinch to zoom): daily or weekly candles with volume, 2 or 10 years, MA 10/20/50/200 and EMA 9/21, the scans' past hits (amber triangles, hover for the scan), your buys and sells, today's pivot and stops; anchored VWAPs (from the highest high, the lowest low, the year start, the latest scan hit, or any day you save); trend lines, saved per stock in the data repo as you draw them on the daily bars (the line tool, top right; drag a line or its ends to move it, click it and use the eraser to delete it; a line drawn past the last bar keeps extending each day; or type one in through two points); and an intraday view of any day with minute bars (1/5/15-minute candles, VWAP from the open, pre-/post-market shaded) |
| **Chart → Intraday → Live** (22 Oct 2026) | A recent session's 1/5/15-minute candles from Alpaca's real-time feed, with VWAP, the prior close, the stock's pivot, stops and plan entry, and a line at 10:30. Needs the Alpaca keys on the PC (`scripts\set_local_secrets.ps1`) |
| **Scans** (22 Oct 2026) | Every scan: when it runs (New York · Copenhagen), when its hits are pushed, its grade and settings. *Edit a scan*: on/off, pushed or saved only, when it is pushed, its thresholds, and your own name and note for the push. Each edit is checked like the jobs check config, saved to `config/scans.yaml`, and used by GitHub's jobs after *Commit & push*. Run times live in the timer and change in code |
| **Watchlists** | Your own lists (add by typing or a TradingView export; each ticker with close, change, RVOL, ADR, RS, distance to the high and pivot, earnings, today's scans) the scans' EP-Watch and BO-Watch, your price alerts (add, remove, what fired today), and *TradingView list (.txt)* to download a list (Screens has the same for a scan) for TradingView's Watchlist → Import list |
| **Journal** | Tabs: *Open positions* (open P&L, open R, money at risk to the stops), *Log a trade*, *Plans*, *Closed trades* (stats, R curve, MFE/MAE, review chart, grading), *Real vs study* |
| **Market** | The market tiles (QQQ light, heat, IBD state, SPY, QQQ, VIX) and the IBD state's last 30 sessions (distribution days, the count, the state). Today's market heat and every setup at that heat (or any other heat): net R a trade on 2016–21 and 2022–26, trades, years up, held / lost / mixed. Indexes, sectors and themes. Then the breadth history with the QQQ light and the Market Light: the 5- and 10-day ratios over time |
| **Research** | The history of your rules, one section at a time, each saying what its numbers measure. *How it was tested*: the grade rules in config in words (points, grade per count, when to buy, stop, exit), then the write-up from the data repo (`docs/research/how-we-test.md`): the method, the best time of day, which market each setup likes, and why famous traders win with setups that test flat. *Grades* (net of costs, out of sample: the numbers to decide on): the grading rules per strategy (entry, stop, exit, the score bands, the points per feature, the trading costs), the size and push per grade, the history behind each grade, and the research report. *History* (the graded section net of costs, the tables gross): every strategy's history (2 or 10 years): win rate and median move after 1/5/21/63 sessions, R, the exits compared, splits by year/market/price (EP-Day adds its own filters), the events and their charts. *Entries & exits* (gross): the minute study: the best entry, stop and exit per strategy; every combination with any exit; splits; the trades (2 years) or the summaries and a by-year table (10 years). *Market regime*: how often each light occurred per year, and for any strategy every filter's effect on trades kept, mean R and win rate, overall and per year |
| **Live results** | The live signals since launch. *Grades live vs study*: each live A+ / A / B signal played out by its study plan (the plan's price, its stop checked from the next session, out at the close after the plan's sessions, net of the study's cost), per strategy, entry time and grade next to the history that grade carried, and your journal trades next to the plan of the signal they came from. The verdict says "too few trades yet" until 20 trades have closed, and "below the study" only when both the mean R and the win rate are clearly under it. The same tables arrive as a monthly report (`docs/live-tracking/` in the data repo) and one push on the 1st. *All signals*: outcome statistics of the live signals per scan. *Signals you graded*: the signals you graded, with what happened after |
| **System health** | *Jobs and data*: which scheduled job ran for which session, data freshness, failure logs, whether each timed job started on time (timer vs GitHub), and how late GitHub started each run. *Validation against TradingView*: compare a run with a TradingView screener export and record it in `docs/validation.md` |
| **Guide** | This page |

## 12. Phone access

The dashboard runs on your PC (`scripts\start_dashboard.ps1`, or http://localhost:8501).
With Tailscale on the PC and the phone (same account), it is shared only with your own devices
at `http://<pc-name>.<tailnet>.ts.net`. Open the Tailscale app, switch it on, then open that
address in Safari (Share → Add to Home Screen for one tap). The PC has to be on.

To have it without the PC: [SERVER.md](SERVER.md) moves the dashboard to a small cloud server (about €5 a month), private to your devices the same way, updating and restarting itself.

After the code or `config/scans.yaml` changes, restart the dashboard (Ctrl-C in its terminal, then `scripts\start_dashboard.ps1` again). A running dashboard reloads its own page but keeps the older `trading_os` code it started with, so new config keys can stop it with an error such as `unknown slot`.

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
