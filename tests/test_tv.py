import pandas as pd

from trading_os import tv
from trading_os.config import load_config


def test_universe_query_uses_explicit_exclusions_only():
    query = tv.build_universe_query(load_config().universe)
    payload = query.query
    assert "filter2" not in payload  # package default (primary listings only) removed
    lefts = {f["left"]: f for f in payload["filter"]}
    assert lefts["close"]["operation"] == "egreater" and lefts["close"]["right"] == 0.5
    assert lefts["market_cap_basic"]["right"] == 50_000_000
    assert lefts["exchange"]["right"] == ["OTC"]
    assert lefts["type"]["right"] == ["stock", "dr"]
    assert "preferred" in lefts["typespecs"]["right"]
    assert "is_primary" not in lefts
    assert payload["range"] == [0, tv.MAX_ROWS]
    assert payload["columns"] == list(tv.FIELDS.values())


def test_canonical_resolves_proxy_fields():
    assert tv.canonical("average_volume_60d_calc") == "avg_volume_60d_tv"
    assert tv.canonical("AvgValue.Traded_30d") == "avg_dollar_volume_30d_tv"


def test_normalize_renames_and_types():
    raw = pd.DataFrame(
        {
            "ticker": ["NASDAQ:AAA", "NYSE:BBB"],
            **{field: [None, None] for field in tv.FIELDS.values()},
        }
    )
    raw["name"] = ["AAA", "BBB"]
    raw["typespecs"] = [["common"], []]
    raw["earnings_release_date"] = [1_760_000_000, None]
    df = tv.normalize(raw)
    assert list(df.columns[:2]) == ["ticker", "tv_ticker"]
    assert df["ticker"].tolist() == ["AAA", "BBB"]
    assert df["typespecs"].tolist() == ["common", ""]
    assert str(df["earnings_date_last"].dt.tz) == "UTC"
    assert "gap_pct" in df.columns and "gap" not in df.columns
