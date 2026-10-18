"""End-to-end test of scripts/eod.py with a synthetic TradingView frame (no network)."""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from trading_os import tv

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "eod.py"
spec = importlib.util.spec_from_file_location("eod_job", SCRIPT)
eod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eod)

GAPPER = "".join(["GP", "QX"])  # built at runtime, like real data
QUIET = "".join(["QT", "ZZ"])


def synthetic_universe() -> pd.DataFrame:
    base = {column: 0.0 for column in tv.FIELDS if column != "symbol"}
    base |= {
        "tv_ticker": "",
        "exchange": "NASDAQ",
        "type": "stock",
        "typespecs": "common",
        "is_primary": True,
        "sector": "",
        "industry": "",
        "open": 11.0,
        "high": 12.0,
        "low": 10.5,
        "close": 11.5,
        "market_cap": 800_000_000.0,
        "avg_volume_30d_tv": 900_000.0,
        "avg_dollar_volume_30d_tv": 9_000_000.0,
        "earnings_date_last": pd.Timestamp("2026-07-01", tz="UTC"),
        "earnings_date_next": pd.Timestamp("2026-11-01", tz="UTC"),
    }
    gapper = base | {
        "ticker": GAPPER,
        "gap_pct": 18.0,
        "chg_pct": 20.0,
        "volume": 3_000_000,
        "avg_volume_60d_tv": 62_000_000 / 60,  # RVOL 3.0 once today is removed
    }
    quiet = base | {
        "ticker": QUIET,
        "gap_pct": 1.0,
        "chg_pct": 0.5,
        "volume": 900_000,
        "avg_volume_60d_tv": 900_000.0,
    }
    return pd.DataFrame([gapper, quiet])


@pytest.fixture()
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(eod.tv, "fetch_universe", lambda universe: synthetic_universe())
    monkeypatch.setattr(eod.notify, "send", lambda server, topic, msg: messages.append(msg))
    monkeypatch.setenv("NTFY_TOPIC", "test-topic")
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    return messages


def test_forced_run_writes_manual_files_and_pushes(tmp_path, capsys, sent):
    assert eod.main(["--data-dir", str(tmp_path), "--force"]) == 0
    out, err = capsys.readouterr()
    # Public log: counts only.
    assert GAPPER not in out + err and QUIET not in out + err
    assert "EP-Day: 1 hits (1 alert), saved" in out

    [run_dir] = (tmp_path / "data" / "manual").iterdir()
    candidates = pd.read_parquet(run_dir / "candidates.parquet")
    assert candidates["ticker"].tolist() == [GAPPER]
    assert candidates["pushed"].tolist() == [True]
    assert candidates["run_kind"].tolist() == ["manual"]
    assert len(pd.read_parquet(run_dir / "universe.parquet")) == 2
    assert (run_dir / "export.xlsx").exists()
    assert not (tmp_path / "data" / "candidates").exists()  # canonical history untouched

    [message] = sent
    assert message.title.endswith("(manual)")
    assert GAPPER in message.body


def test_outside_window_does_nothing(tmp_path, capsys, sent, monkeypatch):
    monkeypatch.setattr(eod.clock, "in_window", lambda *a: False)
    assert eod.main(["--data-dir", str(tmp_path)]) == 0
    assert "nothing to do" in capsys.readouterr().out
    assert not (tmp_path / "data").exists()
    assert sent == []


def test_missing_topic_fails_without_leaking(tmp_path, capsys, sent, monkeypatch):
    monkeypatch.delenv("NTFY_TOPIC")
    assert eod.main(["--data-dir", str(tmp_path), "--force"]) == 1
    out, _ = capsys.readouterr()
    assert "EOD: FAILED (RuntimeError)" in out
    assert list((tmp_path / "logs").glob("*_eod.log"))
