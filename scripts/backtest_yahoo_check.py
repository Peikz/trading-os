"""Backtest step 1 check (docs/backlog/backtest.md §10.1): do our adjusted daily closes match
Yahoo's? Local only, never in Actions: it handles tickers and prices.

For each ticker it downloads Yahoo's daily chart (close = split-adjusted, adjclose = split- and
dividend-adjusted), joins it to the bars-alpaca closes on the same sessions and writes the
per-day comparison to the data repo (`docs/validation/backtest_yahoo_check.csv`). Stdout gets
counts and the worst difference per sample, not tickers or prices.

    uv run python scripts/backtest_yahoo_check.py --bars-dir <year files> --data-dir <data repo>
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import pandas as pd
import requests

from trading_os.backtest import data
from trading_os.logsafe import status

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}"
HEADERS = {"User-Agent": "Mozilla/5.0 (trading-os research)"}
TOLERANCE_PCT = 0.5


def yahoo(ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    p1 = int(dt.datetime.combine(start, dt.time()).timestamp())
    p2 = int(dt.datetime.combine(end + dt.timedelta(days=1), dt.time()).timestamp())
    r = requests.get(
        URL.format(t=ticker),
        params={"period1": p1, "period2": p2, "interval": "1d", "events": "div,split"},
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    tz = res["meta"].get("exchangeTimezoneName", "America/New_York")
    days = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert(tz).date
    q = res["indicators"]
    return pd.DataFrame(
        {
            "session_date": days,
            "y_close": q["quote"][0]["close"],
            "y_adjclose": q["adjclose"][0]["adjclose"],
        }
    ).dropna()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bars-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--tickers", nargs="+", default=["AAPL", "NVDA", "CROX"])
    args = parser.parse_args(argv)
    cfg = data.load_config()
    bars = data.load_bars(data.bar_files(cfg, args.bars_dir, None))
    rows, ok = [], True
    for i, t in enumerate(args.tickers, 1):
        ours = bars.loc[bars["ticker"] == t, ["session_date", "close"]]
        y = yahoo(t, ours["session_date"].min(), ours["session_date"].max())
        m = ours.merge(y, on="session_date")
        m["diff_adj_pct"] = (m["close"] / m["y_adjclose"] - 1) * 100
        m["diff_split_pct"] = (m["close"] / m["y_close"] - 1) * 100
        worst = m["diff_adj_pct"].abs().max()
        recent = m.tail(250)["diff_adj_pct"].abs().max()
        good = worst <= TOLERANCE_PCT
        ok &= bool(good)
        status(
            f"Sample {i}: {len(m)} sessions matched of {len(ours)}, worst diff vs Yahoo adjusted "
            f"{worst:.2f} % (last year {recent:.2f} %), vs split-only "
            f"{m['diff_split_pct'].abs().max():.2f} % -> {'ok' if good else 'CHECK'}"
        )
        rows.append(m.assign(ticker=t))
    out = args.data_dir / "docs" / "validation" / "backtest_yahoo_check.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(rows).to_csv(out, index=False)
    verdict = "all samples match" if ok else "a sample differs"
    status(f"Yahoo check: {verdict}; detail in the data repo")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
