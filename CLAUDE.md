# CLAUDE.md — Trading OS

You are building Trading OS for Emil. `SPEC.md` is the source of truth. `BACKLOG.md` is the work queue.

## Every session
1. Read `SPEC.md` and `BACKLOG.md` before doing anything.
2. Take the first unchecked item in the current phase. Do not skip ahead to later phases.
3. Finish the item end to end: code, tests, a manual run, then commit.
4. Tick the item in `BACKLOG.md`, add a one-line note under "Session log" (date, what was done, what's next), commit.
5. If blocked, write the blocker under "Blocked" in `BACKLOG.md` and stop, rather than guessing.

## Unattended runs (scheduled GitHub Action)
- Work on a new branch `claude/backlog-<date>`; open a pull request; **never merge your own PR**. Emil reviews and merges.
- Before starting, check open PRs from earlier runs. If one is unmerged, continue on that branch instead of starting a new one.
- Do at most 2 backlog items per run, then commit, push, update the PR description with what was done and what's next.
- If an item needs Emil (a decision, a secret, a validation check), write it under "Questions for Emil" or "Blocked", skip to the next unblocked item, and say so in the PR.
- If nothing unblocked is left, open no PR and exit.

## Hard rules
- **Never change a threshold or filter** in `config/scans.yaml` without Emil saying so. If a rule looks wrong, write it under "Questions for Emil".
- **Never add a new scan or setup** that is not in SPEC.md. Emil follows a single-setup discipline; scope creep is the main risk to this project.
- **Point-in-time:** historical Parquet files are append-only. Never rewrite past rows. Outcomes go in their own table.
- **No AI at runtime.** No LLM or API-model calls in any scheduled job.
- **This code repo is public; its Actions logs are public.** Never print tickers, scan results, prices, P&L or journal content to logs, PR descriptions, issues or commit messages. All data goes to the private `trading-os-data` repo. Log counts and status only.
- **No secrets in code or commits.** Use environment variables and GitHub Secrets. Never store TradingView credentials.
- **No automated trading.** Nothing places orders.
- **Respect rate limits:** TradingView screener — a few requests per run, never loops; Massive free tier — max 5 calls/minute.

## Code conventions
- Python 3.12, `pyproject.toml`, `ruff` for lint/format, `pytest` for tests.
- Layout: `trading_os/` (package), `config/scans.yaml`, `scripts/` (job entry points), `tests/`, `data/`, `docs/`.
- Every metric in SPEC.md §5 has a unit test with a hand-computed example.
- Every scan is a pure function: (dataframe, config) → dataframe of hits. Easy to test.
- Store every intermediate value a human might want to audit (pivot, base length, contraction depths).
- Small commits with clear messages: `feat(scan): EP-Day`, `fix(metrics): ADR uses 20 days`.

## Verification
- Before trusting a TradingView field name, check it against the package's field documentation and print a sample.
- When a scan is first built, run it manually and write the top results to `docs/validation.md` **in the private data repo** so Emil can compare against his own TradingView screen.
- A job is not done until it has run successfully in GitHub Actions at least once.
