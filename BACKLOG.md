# BACKLOG — Trading OS

Work top to bottom. Tick items when done (code + tests + manual run + commit).

## Phase 1 — Core scans

### Setup
- [ ] Emil: create public repo `trading-os` (add SPEC.md, CLAUDE.md, BACKLOG.md, `.github/workflows/claude-backlog.yml`) and private repo `trading-os-data`
- [ ] Emil: fine-grained PAT with contents read/write on `trading-os-data` only → secret `DATA_REPO_TOKEN` in `trading-os`
- [ ] Data-repo client: checkout, write, commit, push from workflows; log only counts/status (SPEC §2 two-repo rules)
- [ ] Project skeleton: `pyproject.toml`, `ruff`, `pytest`, package layout per CLAUDE.md
- [ ] `config/scans.yaml` with every threshold from SPEC.md §4 and §6 (Phase 1 scans)
- [ ] Market calendar + New York time guard (premarket / eod windows, holidays)

### Data
- [ ] TradingView client wrapper: verify field names (SPEC §11.1), print samples, document in `docs/fields.md`
- [ ] Universe builder: exclusions + logged/alert tiers (SPEC §4)
- [ ] Metrics module with unit tests (SPEC §5) — Phase 1 uses TradingView fields where they exist
- [ ] Parquet writer (append-only, partitioned per SPEC §7) + xlsx export

### Scans — EOD
- [ ] EP-Day
- [ ] EP9M
- [ ] Momentum Burst up / down
- [ ] Parabolic Short / Long
- [ ] Breadth line + Market Light count
- [ ] EP-AH (built, toggle OFF)

### Scans — pre-market
- [ ] EP-PM
- [ ] EP9M early warning
- [ ] Watchlist gappers (empty watchlist OK until Phase 2)

### Scans — weekly
- [ ] Qullamaggie 1/3/6M gainers
- [ ] Growth Bucket 1 and 2 (record quarters checked)

### Delivery
- [ ] ntfy notifications (one message per job + failure message)
- [ ] GitHub Actions: `premarket.yml`, `eod.yml`, `weekly.yml` with dual cron + guard + `workflow_dispatch` + commit of `data/`
- [ ] Secret set: `NTFY_TOPIC` (Massive key not needed until Phase 2)

### Validation
- [ ] `docs/validation.md` **in the private data repo**: first 2 weeks, EP-Day and gainers vs Emil's manual TradingView screens
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

## Blocked

## Session log
