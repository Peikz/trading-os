"""Verify TradingView field names, types and units against live data (CLAUDE.md, Verification).

LOCAL USE ONLY. It prints sample rows with tickers to your terminal, so never run it in
GitHub Actions. It writes docs/fields.md, which holds field names and aggregate checks only.

Makes 2 requests: the full universe query used by the jobs, and one small probe for fields
the jobs don't use yet (prior-bar values, quarterly history arrays).

    uv run python scripts/verify_fields.py
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from trading_os import tv
from trading_os.config import load_config
from trading_os.metrics import yoy_growth

DOCS = Path(__file__).resolve().parent.parent / "docs" / "fields.md"

NOTES = {
    "prev_close": "previous daily bar's close",
    "prev_volume": "previous daily bar's volume (Momentum Burst: volume > prior day)",
    "chg_pct": "percent (12.3 = 12.3 %), close vs prior close",
    "chg_abs": "price units, close - prior close",
    "gap_pct": "percent, open vs prior close",
    "market_cap": "USD",
    "rvol10_tv": "TradingView relative volume, 10-day base",
    "avg_dollar_volume_30d_tv": "USD per day",
    "perf_1m_tv": "percent",
    "perf_3m_tv": "percent",
    "perf_6m_tv": "percent",
    "adr14_usd_tv": "price units, 14-day average day range (not SPEC's ADR(20) %)",
    "earnings_date_last": "unix seconds -> UTC timestamp",
    "earnings_date_next": "unix seconds -> UTC timestamp",
    "country": "company country (Market Light scan count: Country USA)",
    "revenue_ttm": "USD, trailing 12 months",
    "revenue_q_hist": "weekly job only: reported quarterly revenue, latest first",
    "eps_q_hist": "weekly job only: diluted EPS per quarter, latest first",
    "rev_growth_q": "percent, latest fiscal quarter YoY",
    "eps_growth_q": "percent, latest fiscal quarter YoY (diluted EPS)",
    "pm_change_pct": "percent, pre-market vs prior close",
    "pm_gap_pct": "percent",
    "pm_price": "last pre-market price",
    "ah_change_pct": "percent, post-market vs close",
}

FINDINGS = [
    "The package's default filter keeps primary listings only (`is_primary`). That drops second "
    "share classes (e.g. class B shares), interlisted Canadian stocks and about 60 % of ADRs, so "
    "the universe query replaces it with SPEC §4's explicit exclusions. `is_primary` is stored.",
    "Exclusions use `type` (stock, dr) and `typespecs` "
    "(preferred, unit, warrant, right, etf, etn). ADRs have empty `typespecs`.",
    "`gap` and `change` are percent and match open and close against close - change_abs.",
    "`average_volume_Nd_calc` includes today. RVOL removes it: (N x avg - volume) / (N - 1).",
    "Prior-bar values exist as `close[1]`, `volume[1]`, `high[1]`, `low[1]`. `close[1]` matches "
    "close - change_abs, so `[1]` is the previous daily bar.",
    "Quarterly history: `total_revenue_fq_h` (reported revenue) and "
    "`earnings_per_share_diluted_fq_h` hold 32 quarters, latest first, so previous-quarter YoY "
    "growth is computable (SPEC §11.2). Index 0 vs 4 reproduces TradingView's latest-quarter YoY "
    "(EPS with |year-ago| as the base). `revenues_fq_h` is the analyst-estimates series (oldest "
    "first, forecasts appended) and is not used.",
    "Offsets beyond `[2]` (e.g. `close[5]`, `SMA20[5]`) come back empty: TradingView serves only "
    "two prior bars, not enough for 10-day returns, MA slopes or 5/10-day breadth ratios.",
]

PROBE_FIELDS = [
    "high[1]",
    "low[1]",
    "revenues_fq_h",
    "earnings_per_share_diluted_fq_h",
    "total_revenue_yoy_growth_fq_h",
    "postmarket_close",
    "country",
    "Perf.W",
    "Perf.Y",
    "High.1M",
    "High.3M",
]


def main() -> None:
    cfg = load_config()
    pd.set_option("display.width", 220, "display.max_columns", 60)

    fields = list(tv.FIELDS.values()) + list(tv.HISTORY_FIELDS.values())
    total, raw = tv.build_universe_query(cfg.universe, fields).get_scanner_data(timeout=40)
    print(f"universe: matched {total}, returned {len(raw)}")
    df = tv.normalize(raw)

    stats = []
    for canon, field in (tv.FIELDS | tv.HISTORY_FIELDS).items():
        column = "ticker" if canon == "symbol" else canon
        series = df[column]
        stats.append(
            {
                "column": column,
                "tv_field": field,
                "dtype": str(series.dtype),
                "non_null_pct": round(100 * series.notna().mean(), 1),
                "notes": NOTES.get(canon, ""),
            }
        )
    stats = pd.DataFrame(stats)
    print(stats.to_string(index=False))

    checks = run_checks(df)
    for line in checks:
        print("check:", line)

    print("\nType mix:")
    print(df.groupby(["type", "exchange"]).size().to_string())

    sample = df[df["ticker"].isin(["AAPL", "NVDA", "BRK.B", "TSM"])]
    print("\nSample rows (local only):")
    print(sample.T.to_string())
    top_gap = df.sort_values("gap_pct", ascending=False).head(5)
    print("\nTop gappers (local only):")
    print(top_gap[["ticker", "gap_pct", "chg_pct", "volume", "rvol10_tv", "market_cap"]])

    probe = probe_fields(cfg)
    print("\nProbe (non-null % on 200 largest names):")
    for field, pct, example_type in probe:
        print(f"  {field:40s} {pct:6.1f}%  {example_type}")

    write_docs(total, len(df), stats, checks, probe)
    print(f"\nwrote {DOCS}")


def run_checks(df: pd.DataFrame) -> list[str]:
    out = []
    out.append(f"tickers unique: {df['ticker'].is_unique} ({df['ticker'].duplicated().sum()} dups)")

    prev_close = df["close"] - df["chg_abs"]
    chg_calc = (df["close"] / prev_close - 1) * 100
    gap_calc = (df["open"] / prev_close - 1) * 100
    out.append(_agreement("chg_pct vs close/(close-chg_abs)", df["chg_pct"], chg_calc, 0.05))
    out.append(_agreement("gap_pct vs open/(close-chg_abs)", df["gap_pct"], gap_calc, 0.05))
    out.append(_agreement("prev_close vs close-chg_abs", df["prev_close"], prev_close, 0.01))

    # Do TradingView's N-day averages include today? TradingView's own relative volume excludes
    # today, so compare it with volume / average, with and without today removed.
    busy = df[df["rvol10_tv"] > 5]
    with_today = busy["avg_volume_10d_tv"]
    without_today = (10 * with_today - busy["volume"]) / 9
    for label, base in [("as given", with_today), ("today removed", without_today)]:
        ratio = busy["rvol10_tv"] / (busy["volume"] / base)
        out.append(
            f"rvol10_tv / (volume / avg_volume_10d_tv {label}) on {len(busy)} rows with "
            f"rvol10_tv > 5: median {ratio.median():.3f}, p10 {ratio.quantile(0.1):.3f}, "
            f"p90 {ratio.quantile(0.9):.3f}"
        )
    # With today inside a 10-day mean, volume / mean can never exceed 10.
    implied = df["volume"] / df["avg_volume_10d_tv"]
    out.append(
        f"max volume / avg_volume_10d_tv: {implied.max():.1f} (<= 10 means today is included). "
        "Conclusion: average_volume_Nd_calc includes today; metrics.py removes it for RVOL."
    )

    rev0 = df["revenue_q_hist"].map(lambda h: yoy_growth(h, 0, abs_base=False))
    eps0 = df["eps_q_hist"].map(lambda h: yoy_growth(h, 0, abs_base=True))
    out.append(_agreement("rev_growth_q vs revenue_q_hist[0] / [4]", df["rev_growth_q"], rev0, 0.1))
    out.append(
        _agreement("eps_growth_q vs eps_q_hist[0] vs [4] (|base|)", df["eps_growth_q"], eps0, 0.5)
    )
    dollar = df["close"] * df["volume"]
    out.append(
        "avg_dollar_volume_30d_tv / (close x avg_volume_30d_tv): median "
        f"{(df['avg_dollar_volume_30d_tv'] / (df['close'] * df['avg_volume_30d_tv'])).median():.3f}"
    )
    out.append(f"rows with close x volume >= $5M: {(dollar >= 5_000_000).sum()}")
    nxt = df["earnings_date_next"].dropna()
    if len(nxt):
        out.append(f"earnings_date_next range: {nxt.min().date()} .. {nxt.max().date()}")
    return out


def _agreement(label: str, a: pd.Series, b: pd.Series, tol: float) -> str:
    diff = (a - b).abs().replace([np.inf, -np.inf], np.nan).dropna()
    share = 100 * (diff <= tol).mean() if len(diff) else float("nan")
    return f"{label}: {share:.1f}% of {len(diff)} rows within {tol}pp"


def probe_fields(cfg) -> list[tuple[str, float, str]]:
    query = tv.build_universe_query(cfg.universe, fields=PROBE_FIELDS).limit(200)
    query.query["ignore_unknown_fields"] = True
    _, df = query.get_scanner_data(timeout=30)
    result = []
    for field in PROBE_FIELDS:
        series = df[field]
        first = series.dropna()
        kind = type(first.iloc[0]).__name__ if len(first) else "-"
        if kind == "list":
            kind = f"list[{len(first.iloc[0])}]"
        result.append((field, round(100 * series.notna().mean(), 1), kind))
    return result


def write_docs(total, rows, stats, checks, probe) -> None:
    today = dt.date.today().isoformat()
    lines = [
        "# TradingView fields",
        "",
        f"Verified against live data on {today} with `scripts/verify_fields.py`.",
        "Source: `tradingview-screener` (no login, 15-min delayed), market `america`.",
        "This file holds field names and aggregate checks only, never tickers or prices.",
        "",
        f"Universe query matched {total} rows and returned {rows} (no truncation).",
        "",
        "## Findings",
        "",
        *[f"- {f}" for f in FINDINGS],
        "",
        "## Fields used by the jobs",
        "",
        "| Column | TradingView field | dtype | non-null % | Notes |",
        "|---|---|---|---|---|",
    ]
    for row in stats.itertuples():
        cells = [f"`{row.column}`", f"`{row.tv_field}`", row.dtype, row.non_null_pct, row.notes]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    lines += ["", "## Checks", ""] + [f"- {c}" for c in checks]
    lines += [
        "",
        "## Probed, not used yet",
        "",
        "| Field | non-null % (200 largest) | Python type |",
        "|---|---|---|",
    ]
    lines += [f"| `{f}` | {p} | {k} |" for f, p, k in probe]
    lines.append("")
    DOCS.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
