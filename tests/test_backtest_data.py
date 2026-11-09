import datetime as dt
from pathlib import Path

import pandas as pd
import pytest
import yaml

from trading_os.backtest import data

CONFIG = Path(__file__).resolve().parent.parent / "config" / "backtest.yaml"


def raw():
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def small_cfg(**universe):
    r = raw()
    r["universe"].update({"avg_volume_days": 3, **universe})
    return data.parse_config(r)


def frame(ticker, closes, volumes, start=dt.date(2020, 1, 2)):
    days = [start + dt.timedelta(days=i) for i in range(len(closes))]
    return pd.DataFrame(
        {
            "session_date": days,
            "ticker": ticker,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": volumes,
        }
    )


def test_config_file_loads():
    cfg = data.load_config(CONFIG)
    assert cfg.data.index_tickers == ("QQQ",)
    assert cfg.universe.price_min == 5.0
    assert "ADRC" in cfg.universe.exclude_types


def test_unknown_key_fails():
    r = raw()
    r["universe"]["price_minn"] = 5
    with pytest.raises(ValueError, match="unknown"):
        data.parse_config(r)


def test_missing_key_fails():
    r = raw()
    del r["data"]["years"]
    with pytest.raises(ValueError, match="missing"):
        data.parse_config(r)


def test_excluded_tickers_types_and_spacs():
    listed = pd.DataFrame(
        {
            "ticker": ["AAA", "ETFX", "ADRY", "BOTH", "BOTH", "SPCA"],
            "name": ["Aaa Inc", "Some ETF", "Y plc ADR", "Both", "Both", "Alpha Acquisition Corp"],
            "type": ["CS", "ETF", "ADRC", "ETF", "CS", "CS"],
        }
    )
    out = data.excluded_tickers(listed, small_cfg().universe)
    assert out == {"ETFX", "ADRY", "SPCA"}  # BOTH is also listed as a common stock


def test_avg_volume_uses_only_rows_up_to_t():
    cfg = small_cfg(avg_volume_min=0, price_min=0)
    bars = frame("AAA", [10, 10, 10, 10], [100, 200, 300, 900])
    out = data.with_universe(bars, cfg, set())
    assert out["avg_volume"].isna().tolist()[:2] == [True, True]
    assert out["avg_volume"].iloc[2] == pytest.approx(200)  # (100+200+300)/3
    assert out["avg_volume"].iloc[3] == pytest.approx(1400 / 3)
    # changing a later bar never moves an earlier value
    later = bars.copy()
    later.loc[3, "volume"] = 10**9
    again = data.with_universe(later, cfg, set())
    assert again["avg_volume"].iloc[2] == pytest.approx(200)


def test_universe_floors_exclusions_and_index():
    cfg = small_cfg(avg_volume_min=500, price_min=5)
    bars = pd.concat(
        [
            frame("AAA", [6, 6, 6, 4], [600] * 4),  # price drops under the floor on day 4
            frame("LOW", [6, 6, 6, 6], [100] * 4),  # volume too low
            frame("ETFX", [6, 6, 6, 6], [600] * 4),  # excluded type
            frame("QQQ", [6, 6, 6, 6], [600] * 4),  # index: rows kept, never in the universe
            frame("ABCDW", [6, 6, 6, 6], [600] * 4),  # warrant symbol
        ]
    )
    out = data.with_universe(bars, cfg, {"ETFX"})
    inu = out.groupby("ticker")["in_universe"].apply(list)
    assert inu["AAA"] == [False, False, True, False]
    assert not any(inu["LOW"]) and not any(inu["ETFX"]) and not any(inu["QQQ"])
    assert not any(inu["ABCDW"])
    assert len(data.index_bars(out, "QQQ")) == 4


def test_row_counts_per_year():
    cfg = small_cfg(avg_volume_min=0, price_min=0)
    bars = pd.concat(
        [
            frame("AAA", [6] * 4, [1] * 4, start=dt.date(2020, 12, 30)),
            frame("BBB", [6] * 2, [1] * 2, start=dt.date(2021, 1, 1)),
        ]
    )
    out = data.row_counts(data.with_universe(bars, cfg, set()))
    assert out.loc[2020, "rows"] == 2 and out.loc[2021, "rows"] == 4
    assert out.loc[2021, "tickers"] == 2
    assert out.loc[2020, "universe_rows"] == 0  # warm-up rows have no average yet
    assert out.loc[2021, "universe_rows"] == 2  # AAA's 3rd and 4th day


def test_load_bars_dedupes_and_sorts(tmp_path):
    a = frame("BBB", [1, 2], [1, 1])
    b = frame("AAA", [3], [1])
    a.to_parquet(tmp_path / "2020.parquet")
    pd.concat([b, a.iloc[[1]]]).to_parquet(tmp_path / "2021.parquet")
    out = data.load_bars([tmp_path / "2020.parquet", tmp_path / "2021.parquet"])
    assert out["ticker"].tolist() == ["AAA", "BBB", "BBB"]
    assert isinstance(out["session_date"].iloc[0], dt.date)


def test_main_logs_counts_only(tmp_path, capsys):
    frame("SECRETTKR"[:4], [6] * 3, [600_000] * 3).to_parquet(tmp_path / "2020.parquet")
    cfg = raw()
    cfg["data"]["years"] = [2020]
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    assert data.main(["--config", str(path), "--bars-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "SECR" not in out and "6.0" not in out
    assert out.splitlines()[1].startswith("Survivorship:")
