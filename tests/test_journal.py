"""Trade journal on hand-built fills."""

import datetime as dt

import pandas as pd
import pytest

from trading_os import journal
from trading_os.config import load_config

D = [dt.date(2026, 11, d) for d in (2, 3, 4, 5, 6)]


@pytest.fixture(scope="module")
def rules():
    return load_config().journal


def write_csv(tmp_path, rows, name="fills.csv"):
    path = tmp_path / name
    pd.DataFrame(
        rows, columns=["trade_date", "ticker", "side", "quantity", "price", "fees"]
    ).to_csv(path, index=False)
    return path


ROWS = [
    ["2026-11-02", "AAPL:xnas", "Buy", 100, 10.0, 1.0],
    ["2026-11-03", "AAPL:xnas", "Buy", 100, 11.0, 1.0],  # scale in: avg entry 10.50
    ["2026-11-05", "AAPL:xnas", "Sell", 200, 12.0, 2.0],  # flat: trade closed
    ["2026-11-04", "NYSE:XYZ", "Sell", 50, 20.0, 0.0],  # a short
    ["2026-11-06", "NYSE:XYZ", "Buy", 50, 18.0, 0.0],
    ["2026-11-06", "OPEN", "Buy", 10, 5.0, 0.0],  # still open
]


def test_read_normalize_and_dedupe(tmp_path, rules):
    fills = journal.read_fills(write_csv(tmp_path, ROWS), rules)
    assert set(fills["ticker"]) == {"AAPL", "XYZ", "OPEN"}
    assert set(fills["side"]) == {"buy", "sell"}
    again = journal.read_fills(write_csv(tmp_path, ROWS, "again.csv"), rules)
    assert journal.new_fills(fills, again).empty  # re-importing adds nothing


def test_trades_flat_to_flat(tmp_path, rules):
    fills = journal.read_fills(write_csv(tmp_path, ROWS), rules)
    trades, open_positions = journal.build_trades(fills)
    t = trades.set_index("ticker")
    aapl = t.loc["AAPL"]
    assert aapl["direction"] == "long" and aapl["entry_avg"] == pytest.approx(10.5)
    assert aapl["pnl"] == pytest.approx((12.0 - 10.5) * 200 - 4.0)  # 296
    xyz = t.loc["XYZ"]
    assert xyz["direction"] == "short" and xyz["pnl"] == pytest.approx((20 - 18) * 50)
    assert open_positions["ticker"].tolist() == ["OPEN"]


def test_signal_link_and_r_multiple(tmp_path, rules):
    fills = journal.read_fills(write_csv(tmp_path, ROWS), rules)
    trades, _ = journal.build_trades(fills)
    candidates = pd.DataFrame(
        {
            "signal_id": ["old", "sig"],
            "scan": ["ep_day", "breakout_trigger"],
            "ticker": ["AAPL", "AAPL"],
            "session_date": [dt.date(2026, 10, 1), dt.date(2026, 10, 30)],
            "pushed": [True, True],
            "order_stop": [None, 9.5],
        }
    )
    windows = {D[0]: [dt.date(2026, 10, 27), dt.date(2026, 10, 30), D[0]], D[2]: [D[2]]}
    linked = journal.link_signals(trades, candidates, ["ep_day", "breakout_trigger"], windows)
    aapl = linked.set_index("ticker").loc["AAPL"]
    assert aapl["signal_id"] == "sig" and aapl["order_stop"] == 9.5
    stops = pd.DataFrame({"ticker": ["XYZ"], "entry_date": [D[2]], "stop": [21.0]})
    with_r = journal.add_r_multiples(linked, stops).set_index("ticker")
    # AAPL: risk (10.50 − 9.50) × 200 = 200 → R = 296 / 200 = 1.48
    assert with_r.loc["AAPL", "r_multiple"] == pytest.approx(1.48)
    # XYZ short: risk (21 − 20) × 50 = 50 → R = 100 / 50 = 2
    assert with_r.loc["XYZ", "r_multiple"] == pytest.approx(2.0)


def test_unknown_side_is_rejected(tmp_path, rules):
    with pytest.raises(ValueError, match="unknown side"):
        journal.read_fills(write_csv(tmp_path, [["2026-11-02", "A", "Short", 1, 1.0, 0.0]]), rules)


def test_import_end_to_end(tmp_path, capsys):
    data = tmp_path / "data-repo"
    assert journal.main(["--csv", str(write_csv(tmp_path, ROWS)), "--data-dir", str(data)]) == 0
    assert "6 new fills, 2 closed trades" in capsys.readouterr().out
    assert journal.main(["--csv", str(write_csv(tmp_path, ROWS)), "--data-dir", str(data)]) == 0
    assert "0 new fills, 2 closed trades" in capsys.readouterr().out
