# Trading OS

A personal scanning and data-collection pipeline for momentum setups in US equities
(Qullamaggie and Stockbee style scans). Deterministic Python on GitHub Actions: same input,
same output. No AI at runtime, no order placement, no grading of setups by code.

This repo holds code and config only. Scan results live in a separate private data repo, and
the jobs print counts and status only, because Actions logs here are public.

[`SPEC.md`](SPEC.md) is the source of truth, and [`BACKLOG.md`](BACKLOG.md) is the work queue.

## Jobs

| Job | Workflow | When | What |
|---|---|---|---|
| Pre-market | `premarket.yml` | 07:17 New York, trading days | EP-PM |
| End of day | `eod.yml` | 16:17 New York, trading days | EP-Day, EP9M, Momentum Burst up/down, EP-AH (off by default), Parabolic Short/Long, Breakout watch (B1-B4) and trigger (B5) |
| Weekly | `weekly.yml` | Sunday | Qullamaggie 1/3/6M gainers, Growth Bucket 1 and 2, tight bases |
| Outcomes | `outcomes.yml` | after the EOD job | 5/10/20/60-session outcomes of past signals |
| Backfill | `backfill.yml` | daily catch-up, or manual | Massive grouped-daily bars (needs `MASSIVE_API_KEY`) |
| Keepalive | `keepalive.yml` | 1st of each month | Re-enables the scheduled workflows (GitHub disables them after 60 idle days) |

Scans that need daily history (Parabolic, breakouts, tight bases) find nothing until enough
sessions of bars exist, from Massive or from the jobs' own EOD snapshots. Pushed candidates
get a before-shot chart PNG in the data repo.

Each workflow has two UTC crons, one per daylight-saving state. The script exits unless New
York time is inside its window on a trading day (NYSE calendar), and it skips a session that
is already saved. Every workflow also has a manual `workflow_dispatch` with a `force` option,
which skips the time guard and writes to `data/manual/` instead of the session history.

A run fetches the TradingView screener universe once (no login, 15-minute delayed), computes
metrics, runs the slot's scans, sends one ntfy message, and appends Parquet and an xlsx export
to the data repo. Historical files are never rewritten.

## Layout

```
config/scans.yaml     every threshold (no magic numbers in code)
trading_os/           package: config, clock, tv, universe, metrics, scans/, store, notify, job
scripts/              job entry points (premarket.py, eod.py, weekly.py) and verify_fields.py
tests/                pytest, synthetic data only
docs/fields.md        verified TradingView field names, units and checks
```

## Running locally

Needs [uv](https://docs.astral.sh/uv/) and a clone of the data repo next to this one.

```bash
uv sync
uv run pytest
uv run python scripts/eod.py --data-dir ../trading-os-data --force --no-push
```

`--force` writes to `data/manual/` and `--no-push` skips ntfy. `scripts/verify_fields.py`
prints sample rows with tickers, so run it locally only, never in Actions.

Two more local helpers (both print tickers, so never in Actions):

- `scripts/compare_screen.py` diffs a run against a TradingView screener CSV export for the
  Phase 1 validation, with the reason for every difference.
- `scripts/build_duckdb.py` (`uv run --group analysis ...`) builds a views-only DuckDB file
  over the data repo for ad-hoc queries and Power BI.
- `scripts/import_fills.py` imports a broker fills CSV into the trade journal (Phase 4):
  trades flat to flat, linked to their signal, with R-multiples. See `docs/powerbi.md` for
  Power BI on top.

## Dashboard

A private web app over your local clone of the data repo: today's market and pushed scans
with charts, every screen, watchlists, the trade journal (import fills, grade A/B/C, notes,
screenshots), graded signals with outcomes, breadth history, statistics and the TradingView
validation helper.

```bash
uv run --group app streamlit run app/streamlit_app.py
```

It opens at http://localhost:8501 and reads `../trading-os-data` (change it in the sidebar, or
pass `-- --data-dir PATH`). Grades and notes are saved as append-only files in the data repo;
"Save & push" in the sidebar sends them to GitHub. `.streamlit/config.toml` keeps it on this
computer only. Never deploy it from this public repo with data in it.

## Secrets

Set as GitHub Actions secrets on this repo, never in code:

| Secret | Used for |
|---|---|
| `NTFY_TOPIC` | ntfy.sh topic for the job messages |
| `DATA_REPO_TOKEN` | fine-grained token, contents read/write on the data repo only |
| `CLAUDE_CODE_OAUTH_TOKEN` | the scheduled backlog worker (`claude-backlog.yml`) |
| `MASSIVE_API_KEY` | price history, Phase 2 |

No TradingView credentials are used or stored.

`DATA_REPO_TOKEN` expires after the period you chose (1 year suggested). When it does, the jobs
fail with a failure push; create a new token the same way and replace the secret.
