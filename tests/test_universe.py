import pandas as pd
import pytest

from trading_os.config import load_config
from trading_os.universe import build_universe


@pytest.fixture(scope="module")
def universe_cfg():
    return load_config().universe


def row(ticker, **overrides):
    base = {
        "ticker": ticker,
        "exchange": "NASDAQ",
        "type": "stock",
        "typespecs": "common",
        "close": 20.0,
        "market_cap": 500_000_000,
        "avg_volume_20d": 1_000_000,
        "avg_dollar_volume_20d": 20_000_000,
        "dollar_volume": 30_000_000,
    }
    return base | overrides


def frame(*rows):
    return pd.DataFrame(list(rows))


def test_exclusions(universe_cfg):
    df = frame(
        row("KEEP"),
        row("ADR", type="dr", typespecs=""),
        row("OTCX", exchange="OTC"),
        row("FUND", type="fund", typespecs="etf"),
        row("PREF", typespecs="preferred"),
        row("UNIT", typespecs="unit"),
    )
    out = build_universe(df, universe_cfg, "eod")
    assert sorted(out["ticker"]) == ["ADR", "KEEP"]


def test_logged_tier_floors(universe_cfg):
    df = frame(
        row("CHEAP", close=0.49),
        row("FLOOR", close=0.50, market_cap=50_000_000, avg_dollar_volume_20d=500_000),
        row("SMALL", market_cap=49_999_999),
        row("THIN", avg_dollar_volume_20d=499_999),
    )
    assert build_universe(df, universe_cfg, "eod")["ticker"].tolist() == ["FLOOR"]


def test_alert_tier(universe_cfg):
    df = frame(
        row("ALERT"),
        row("LOWVOL", avg_volume_20d=499_999),
        row("SUB1", close=0.99),
        row("SWVL", dollar_volume=4_999_999),
        row("EDGE", close=1.0, market_cap=50_000_000, avg_volume_20d=500_000, dollar_volume=5e6),
    )
    eod = build_universe(df, universe_cfg, "eod").set_index("ticker")["tier"]
    assert eod.to_dict() == {
        "ALERT": "alert",
        "LOWVOL": "log",
        "SUB1": "log",
        "SWVL": "log",
        "EDGE": "alert",
    }
    # The signal-day dollar-volume guard applies to EOD signals only.
    pm = build_universe(df, universe_cfg, "pm").set_index("ticker")["tier"]
    assert pm["SWVL"] == "alert"
