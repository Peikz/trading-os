# BACKLOG — Trading OS

Work top to bottom. Tick items when done (code + tests + manual run + commit).

## Phase 1 — Core scans

### Setup
- [x] Emil: create public repo `trading-os` (add SPEC.md, CLAUDE.md, BACKLOG.md, `.github/workflows/claude-backlog.yml`) and private repo `trading-os-data` — done 18 Oct via gh; backlog worker disabled until START-HERE Step 6
- [ ] Emil: fine-grained PAT with contents read/write on `trading-os-data` only → secret `DATA_REPO_TOKEN` in `trading-os`
- [ ] Data-repo client: checkout, write, commit, push from workflows; log only counts/status (SPEC §2 two-repo rules) — built in `eod.yml`, `premarket.yml` and `weekly.yml`, waiting for the first Actions run
- [x] Project skeleton: `pyproject.toml`, `ruff`, `pytest`, package layout per CLAUDE.md
- [x] `config/scans.yaml` with every threshold from SPEC.md §4 and §6 (Phase 1 scans)
- [x] Market calendar + New York time guard (premarket / eod windows, holidays)

### Data
- [x] TradingView client wrapper: verify field names (SPEC §11.1), print samples, document in `docs/fields.md`
- [x] Universe builder: exclusions + logged/alert tiers (SPEC §4)
- [ ] Metrics module with unit tests (SPEC §5) — Phase 1 uses TradingView fields where they exist — partial: dollar volume, close location, RVOL (today removed), 20-day proxies, MA position, ADR % and distance from MA10 in ADR (TradingView ADR proxy), returns (Perf.1M/3M/6M proxy), previous-quarter growth, pre-market dollar volume, earnings flag. MA rising and consecutive days need more history than TradingView serves (see Questions)
- [x] Parquet writer (append-only, partitioned per SPEC §7) + xlsx export

### Scans — EOD
- [ ] EP-Day — built and run locally on 16 Oct; ticks after the first Actions run
- [ ] EP9M — built and run locally on 16 Oct (5 hits); ticks after the first Actions run
- [ ] Momentum Burst up / down — built and run locally on 16 Oct (24 up, 308 down); ticks after the first Actions run
- [ ] Parabolic Short / Long — needs a decision, see Questions
- [ ] Breadth line + Market Light count — needs a decision, see Questions
- [ ] EP-AH (built, toggle OFF) — built and tested; ticks after the first Actions run

### Scans — pre-market
- [ ] EP-PM — built, `premarket.py` + `premarket.yml`; smoke-tested locally; ticks after the first Actions run
- [ ] EP9M early warning — needs a decision, see Questions
- [ ] Watchlist gappers (empty watchlist OK until Phase 2) — same gap question as EP9M early warning

### Scans — weekly
- [ ] Qullamaggie 1/3/6M gainers — built, `weekly.py` + `weekly.yml`; run locally on the week to 16 Oct (73 hits); ticks after the first Actions run
- [ ] Growth Bucket 1 and 2 (record quarters checked) — built; previous quarter comes from `total_revenue_fq_h` / EPS history (SPEC §11.2: available); run locally (202 / 150 hits); ticks after the first Actions run

### Delivery
- [ ] ntfy notifications (one message per job + failure message) — built; ticks after the first real push
- [ ] GitHub Actions: `premarket.yml`, `eod.yml`, `weekly.yml` with dual cron + guard + `workflow_dispatch` + commit of `data/` — all three done (weekly: Sunday 16:00 and 17:00 UTC, guard on the New York weekday)
- [ ] Secret set: `NTFY_TOPIC` (Massive key not needed until Phase 2)

### Validation
- [ ] `docs/validation.md` **in the private data repo**: first 2 weeks, EP-Day and gainers vs Emil's manual TradingView screens — started with 16 Oct
- [ ] 10 consecutive trading days without manual intervention → Phase 1 done

## Phase 2 — Breakouts and history
- [ ] Emil: create free Massive account, add `MASSIVE_API_KEY` as GitHub Secret (agent: if missing, log under Blocked and continue with other items)
- [ ] Massive 2-year grouped-daily backfill (rate limited, resumable)
- [ ] Daily Massive update in `eod` job
- [ ] Metrics on full history (ADR, returns, MA slopes, consecutive days)
- [ ] Base detection B2 (configurable heuristic, store intermediates)
- [ ] B1, B3, B4 (pivot, order stop, risk_adr), B5 trigger
- [ ] Watchlists: EP-Watch → BO-Watch flow
- [ ] Tight bases scan, CATS score
- [ ] Hand audit of 20 random breakout hits

## Phase 3 — Outcomes and journal
- [ ] Outcomes job (5/10/20/60 days)
- [ ] Before-shot chart PNGs per alert candidate
- [ ] Write Breakout Log rows to EPStudyDatabase (Google service account)

## Phase 4 — Trade tracking
- [ ] Saxo fills import (OpenAPI or CSV) → journal with R-multiples
- [ ] Power BI model over DuckDB/Parquet

---

## Questions for Emil
- Your manual EP-Day screen: does it filter on TradingView's "Relative Volume" column (10-day base) and have "Primary listing" switched on? Both change which names show up. The system uses a 59-day RVOL and keeps ADRs and second share classes; `docs/validation.md` in the data repo shows both RVOL columns.
- EP-Day hits are ranked by gap % (largest first) and the `[earnings]` flag means the last earnings release fell on the signal session or the session before. SPEC doesn't specify either; OK?
- **History for Parabolic, breadth ratios and Market Light.** TradingView serves only the last 2 prior bars (`close[1]`, `close[2]`; `[3]` and beyond are empty). Parabolic needs 10-day gains and 3+ consecutive days, breadth needs 5- and 10-day up/down ratios, and Market Light needs "SMA20 lower than 5 sessions ago". Options: (a) build that history from our own daily universe snapshots, so those parts start working after 5-10 sessions; (b) bring the Massive key forward for a small backfill now; (c) leave them for Phase 2. Recommendation: (a). It's point-in-time by construction and needs nothing from you.
- **EP9M pushes alert tier only.** I applied SPEC §11.7 ("only alert-tier EP hits push") to EP9M. That means a quiet stock averaging under 500K shares that suddenly trades 9M won't push (it's still saved). Keep that, or push every EP9M hit?
- **"Gap" in the pre-market scans.** For EP9M early warning (gap >= 4 %) and watchlist gappers (gap >= 2 %): is gap the pre-market price vs prior close (`premarket_change`), or TradingView's "Pre-market Gap" (`premarket_gap`, the first pre-market print vs prior close)? Not built until you say.
- EP-PM uses the prior close for its price >= $1 floor (same price the alert tier uses). OK?
- **QM gainers:** the top 2 % is taken over the whole logged-tier universe (~4,000 names), and the ADR / dollar-volume / price floors apply after that, so the list is "top 2 % of the market that also passes the floors". Returns use TradingView's Perf.1M/3M/6M and ADR % uses TradingView's 14-day ADR / close (same nearest-field rule as the volume windows). OK?
- **Growth buckets:** "avg volume" uses the same 30-day field as the other 20-day averages, and "annual revenue" is trailing-12-month revenue. OK?
- **Market Light scan count** (Sunday): which average-volume field does your TradingView screen use for "average volume > 500K": 10, 30, 60 or 90 days? Since that screen must not change, it isn't built until you say.

## Blocked
- 18 Oct: secrets `NTFY_TOPIC` and `DATA_REPO_TOKEN` not set yet. The first Actions runs of `eod.yml` and `premarket.yml` wait on them (Emil).

## Session log
- 2026-10-18: Repos created; skeleton, config, clock guard, TradingView client (fields verified, see `docs/fields.md`), universe tiers, Phase 1 metrics subset, EP-Day, store, ntfy, `eod.py`, `eod.yml`. Local forced run on 16 Oct data OK. Next: secrets, then the first Actions run of `eod.yml`.
- 2026-10-19: EP9M, Momentum Burst up/down, EP-AH (off), EP-PM + `premarket.yml`; shared job runner. Local runs on 16 Oct data written to `docs/validation.md` in the data repo. Probed TradingView history depth (2 bars only). Next: secrets → first Actions runs; then answers on the Questions above.
- 2026-10-19 (later): QM gainers, Growth Bucket 1 and 2, weekly job + `weekly.yml`; ADR %, returns and previous-quarter growth metrics; reported revenue history verified (100 % match). Local weekly run written to `docs/validation.md`. Next: secrets → first Actions runs; answers on the Questions.
- 2026-10-19 (later): Hardening for the 10-day goal: one retry on TradingView/ntfy errors, data saved even if the push fails. READMEs for both repos (data repo: layout + DuckDB query). All unblocked Phase 1 items done; the rest waits on the secrets and the Questions above.
