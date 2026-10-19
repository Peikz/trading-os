import pandas as pd

from trading_os import validation
from trading_os.config import load_config


def test_compare_explains_each_difference(tmp_path):
    scan = load_config().scans["ep_day"]
    candidates = pd.DataFrame(
        {"scan": ["ep_day", "ep_day"], "ticker": ["BOTH", "MINE"], "tier": ["alert", "log"]}
    )
    universe = pd.DataFrame(
        {
            "ticker": ["BOTH", "MINE", "LOWRV"],
            "tier": ["alert", "log", "alert"],
            "gap_pct": [12.0, 15.0, 11.0],
            "rvol50": [4.0, 3.5, 2.1],
            "rvol10_tv": [5.0, 4.0, 3.4],
            "volume": [1e6, 5e5, 9e5],
            "close": [5.0, 3.0, 8.0],
            "market_cap": [3e8, 1e8, 6e8],
        }
    )
    csv = tmp_path / "screen.csv"
    pd.DataFrame({"Symbol": ["NASDAQ:BOTH", "NYSE:LOWRV", "OTC:GONE"]}).to_csv(csv, index=False)
    result = validation.compare(candidates, universe, validation.read_screen(csv), scan)
    sides = dict(zip(result["ticker"], result["side"], strict=True))
    assert sides == {"BOTH": "both", "GONE": "TV only", "LOWRV": "TV only", "MINE": "system only"}
    why = dict(zip(result["ticker"], result["why"], strict=True))
    assert why["LOWRV"] == "rvol50 2.10 < 3"
    assert why["GONE"].startswith("not in the logged-tier universe")
    text = validation.to_markdown(result, "t")
    assert "Both: 1 · system only: 1 · TradingView only: 2" in text
