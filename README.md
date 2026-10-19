# Trading OS

A personal scanning and data-collection pipeline for momentum setups in US equities
(Qullamaggie and Stockbee style scans). Deterministic Python on GitHub Actions: same input,
same output. No AI at runtime, no order placement, no grading of setups by code.

This repo holds code and config only. Scan results live in a separate private data repo, and
the jobs print counts and status only, because Actions logs here are public.

[`SPEC.md`](SPEC.md) is the source of truth, and [`BACKLOG.md`](BACKLOG.md) is the work queue.

## Jobs

| Job | Workflow | When (New York) | Scans |
|---|---|---|---|
| Pre-market | `premarket.yml` | 07:17, trading days | EP-PM |
| End of day | `eod.yml` | 16:17, trading days | EP-Day, EP9M, Momentum Burst up/down, EP-AH (off by default) |
| Weekly | `weekly.yml` | Sunday | Qullamaggie 1/3/6M gainers, Growth Bucket 1 and 2 |

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

## Secrets

Set as GitHub Actions secrets on this repo, never in code:

| Secret | Used for |
|---|---|
| `NTFY_TOPIC` | ntfy.sh topic for the job messages |
| `DATA_REPO_TOKEN` | fine-grained token, contents read/write on the data repo only |
| `CLAUDE_CODE_OAUTH_TOKEN` | the scheduled backlog worker (`claude-backlog.yml`) |
| `MASSIVE_API_KEY` | price history, Phase 2 |

No TradingView credentials are used or stored.
