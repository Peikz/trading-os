"""Side-by-side check of a scan against a manual TradingView screen (SPEC §1.6, §9).

Export the TradingView screen as CSV, point this at a run folder, and it lists the names
only the system found, only TradingView found, and both, with the reason for each
difference. LOCAL USE ONLY: the output names tickers, so it goes in the private data repo's
docs/validation.md, never in this public repo or its Actions logs.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from trading_os.config import ScanConfig, load_config

# Which universe column each EP-Day threshold applies to (for the "why not" column).
EP_DAY_RULES = {
    "gap_min_pct": ("gap_pct", ">="),
    "rvol_min": ("rvol50", ">="),
    "volume_min": ("volume", ">="),
    "price_min": ("close", ">="),
    "market_cap_min": ("market_cap", ">="),
}
RULES = {"ep_day": EP_DAY_RULES}
SYMBOL_COLUMNS = ("Symbol", "Ticker", "symbol", "ticker", "Name")


def read_screen(csv_path: Path) -> set[str]:
    """Tickers from a TradingView screener CSV export (`NASDAQ:ABC` or `ABC`)."""
    screen = pd.read_csv(csv_path)
    column = next((c for c in SYMBOL_COLUMNS if c in screen.columns), screen.columns[0])
    return {str(s).split(":")[-1].strip().upper() for s in screen[column].dropna()}


def failed_rules(row: Mapping[str, Any], scan: ScanConfig) -> list[str]:
    reasons = []
    for key, (column, op) in RULES.get(scan.name, {}).items():
        value, limit = row.get(column), scan[key]
        if value is None or pd.isna(value):
            reasons.append(f"{column} missing")
        elif op == ">=" and not value >= limit:
            reasons.append(f"{column} {value:,.2f} < {limit:,}")
    return reasons


def compare(
    candidates: pd.DataFrame, universe: pd.DataFrame, screen: set[str], scan: ScanConfig
) -> pd.DataFrame:
    """One row per ticker found by either side, with `side` and `why`."""
    mine = candidates[candidates["scan"] == scan.name].set_index("ticker")
    by_ticker = universe.set_index("ticker")
    rows = []
    for ticker in sorted(set(mine.index) | screen):
        in_system, in_screen = ticker in mine.index, ticker in screen
        side = "both" if in_system and in_screen else ("system only" if in_system else "TV only")
        info = by_ticker.loc[ticker].to_dict() if ticker in by_ticker.index else None
        if side == "TV only":
            why = (
                "; ".join(failed_rules(info, scan)) or "passes here; check the run time"
                if info is not None
                else "not in the logged-tier universe (excluded type/exchange or below a floor)"
            )
        elif side == "system only":
            why = "check your screen's settings (RVOL column, primary listing, price/mcap floors)"
        else:
            why = ""
        rows.append(
            {
                "ticker": ticker,
                "side": side,
                "tier": mine.loc[ticker, "tier"] if in_system else (info or {}).get("tier"),
                "gap_pct": (info or {}).get("gap_pct"),
                "rvol50": (info or {}).get("rvol50"),
                "rvol10_tv": (info or {}).get("rvol10_tv"),
                "volume": (info or {}).get("volume"),
                "why": why,
            }
        )
    return pd.DataFrame(rows)


def to_markdown(result: pd.DataFrame, title: str) -> str:
    counts = result["side"].value_counts().to_dict()
    lines = [
        f"### {title}",
        "",
        f"Both: {counts.get('both', 0)} · system only: {counts.get('system only', 0)} · "
        f"TradingView only: {counts.get('TV only', 0)}",
        "",
        "| Ticker | Side | Tier | Gap % | RVOL (59d) | RVOL TV | Volume | Why |",
        "|---|---|---|---|---|---|---|---|",
    ]

    def num(x, fmt):
        return "" if x is None or pd.isna(x) else format(x, fmt)

    for r in result.to_dict("records"):
        lines.append(
            f"| {r['ticker']} | {r['side']} | {'' if pd.isna(r['tier']) else r['tier']} | "
            f"{num(r['gap_pct'], '.1f')} | "
            f"{num(r['rvol50'], '.1f')} | {num(r['rvol10_tv'], '.1f')} | "
            f"{num(r['volume'], ',.0f')} | {r['why']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare a scan with a TradingView screen CSV")
    parser.add_argument("--run", type=Path, required=True, help="run folder or candidates file")
    parser.add_argument("--csv", type=Path, required=True, help="TradingView screener export")
    parser.add_argument("--scan", default="ep_day")
    parser.add_argument("--append-to", type=Path, help="markdown file to append the table to")
    args = parser.parse_args(argv)

    if args.run.is_dir():
        candidates = pd.read_parquet(args.run / "candidates.parquet")
        universe = pd.read_parquet(args.run / "universe.parquet")
    else:  # canonical files: data/candidates/YYYY/<stem>.parquet next to data/universe/...
        candidates = pd.read_parquet(args.run)
        universe = pd.read_parquet(Path(str(args.run).replace("candidates", "universe")))
    scan = load_config().scans[args.scan]
    result = compare(candidates, universe, read_screen(args.csv), scan)
    text = to_markdown(result, f"{args.scan} vs TradingView ({args.csv.name})")
    print(text)
    if args.append_to:
        with open(args.append_to, "a", encoding="utf-8") as fh:
            fh.write("\n" + text)
    return 0
