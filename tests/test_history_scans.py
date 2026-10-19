import datetime as dt

import pandas as pd
import pytest

from trading_os import enrich
from trading_os.config import load_config
from trading_os.scans.history_scans import parabolic_long, parabolic_short, tight_bases


@pytest.fixture(scope="module")
def scans():
    return load_config().scans


def run(fn, scan, *rows):
    return fn(pd.DataFrame(list(rows)), scan)["ticker"].tolist()


def short_row(ticker, **kw):
    base = {"ticker": ticker, "market_cap": 2e9, "hist_gain_max_pct": 50.0, "hist_consec_up": 3}
    return base | kw


def test_parabolic_short_size_dependent_threshold(scans):
    s = scans["parabolic_short"]
    assert run(parabolic_short, s, short_row("BIG")) == ["BIG"]
    assert run(parabolic_short, s, short_row("BIG2", hist_gain_max_pct=49.9)) == []
    assert run(parabolic_short, s, short_row("RUN2", hist_consec_up=2)) == []
    # Under $1B the bar is +200 %.
    assert run(parabolic_short, s, short_row("SMALL", market_cap=9e8)) == []
    assert run(parabolic_short, s, short_row("SMALL", market_cap=9e8, hist_gain_max_pct=200.0)) == [
        "SMALL"
    ]
    # No history yet: nothing, not an error.
    no_hist = short_row("NEW", hist_gain_max_pct=float("nan"), hist_consec_up=pd.NA)
    assert run(parabolic_short, s, no_hist) == []


def test_parabolic_long(scans):
    s = scans["parabolic_long"]
    row = {"ticker": "DROP", "hist_drop_max_pct": 30.0, "hist_consec_down": 3}
    assert run(parabolic_long, s, row) == ["DROP"]
    assert run(parabolic_long, s, row | {"hist_drop_max_pct": 29.9}) == []
    assert run(parabolic_long, s, row | {"hist_consec_down": 2}) == []


def base_row(ticker, **kw):
    base = {
        "ticker": ticker,
        "pct_from_52w_high": -15.0,
        "hist_adr20_pct": 4.0,
        "hist_adr20_usd": 1.0,
        "close": 25.0,
        "ma50": 24.9,
        "hist_range_nd": 1.49,
        "hist_avg_volume_short": 400_000.0,
        "hist_avg_volume_long": 400_001.0,
    }
    return base | kw


def test_tight_bases_each_rule(scans):
    s = scans["tight_bases"]
    assert run(tight_bases, s, base_row("EDGE")) == ["EDGE"]
    assert run(tight_bases, s, base_row("FAR", pct_from_52w_high=-15.01)) == []
    assert run(tight_bases, s, base_row("SLOW", hist_adr20_pct=3.99)) == []
    assert run(tight_bases, s, base_row("BELOW", ma50=25.0)) == []
    assert run(tight_bases, s, base_row("WIDE", hist_range_nd=1.5)) == []  # < 1.5 × ADR $
    assert run(tight_bases, s, base_row("LOUD", hist_avg_volume_short=400_001.0)) == []
    tight = tight_bases(pd.DataFrame([base_row("A"), base_row("B", hist_range_nd=0.5)]), s)
    assert tight["ticker"].tolist() == ["B", "A"]  # tightest first
    assert tight["tightness_adr"].tolist() == pytest.approx([0.5, 1.49])


def test_attach_history_with_no_past_bars(tmp_path):
    cfg = load_config()
    df = pd.DataFrame(
        {
            "ticker": ["AAA"],
            "open": [1.0],
            "high": [1.1],
            "low": [0.9],
            "close": [1.0],
            "volume": [5],
        }
    )
    out, covered = enrich.attach_history(df, tmp_path, cfg, dt.date(2026, 10, 16))
    assert covered == 1
    assert pd.isna(out.loc[0, "hist_adr20_pct"]) and pd.isna(out.loc[0, "hist_gain_max_pct"])
    assert {f"hist_{c}" for c in enrich.HIST_COLUMNS} <= set(out.columns)
