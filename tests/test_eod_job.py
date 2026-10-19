"""End-to-end test of the job runner with a synthetic TradingView frame (no network)."""

import pandas as pd
import pytest

from trading_os import job, tv


def run_eod(argv):
    return job.main("eod", "EOD", "test", argv)


GAPPER = "".join(["GP", "QX"])  # built at runtime, like real data
QUIET = "".join(["QT", "ZZ"])


def synthetic_universe(with_history: bool = False) -> pd.DataFrame:
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
        "pm_price": 11.0,
    }
    gapper = base | {
        "ticker": GAPPER,
        "gap_pct": 18.0,
        "chg_pct": 20.0,
        "volume": 3_000_000,
        "avg_volume_60d_tv": 62_000_000 / 60,  # RVOL 3.0 once today is removed
        "pm_change_pct": 12.0,
        "pm_volume": 400_000.0,
    }
    quiet = base | {
        "ticker": QUIET,
        "gap_pct": 1.0,
        "chg_pct": 0.5,
        "volume": 900_000,
        "avg_volume_60d_tv": 900_000.0,
    }
    df = pd.DataFrame([gapper, quiet])
    if with_history:
        # Gapper: revenue +50 % and +40 % YoY in the last two quarters.
        df["revenue_q_hist"] = [[150, 140, 120, 110, 100, 100, 90, 80], [10] * 8]
        df["eps_q_hist"] = [[1.0] * 8, [0.1] * 8]
    return df


@pytest.fixture()
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(
        job.tv,
        "fetch_universe",
        lambda universe, with_history=False: synthetic_universe(with_history),
    )
    monkeypatch.setattr(job.notify, "send", lambda server, topic, msg: messages.append(msg))
    qqq = {"close": 100.0, "sma10": 98.0, "sma20": 97.0, "sma50": 95.0}
    monkeypatch.setattr(job.tv, "fetch_quote", lambda symbol: qqq)
    monkeypatch.setenv("NTFY_TOPIC", "test-topic")
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    return messages


def test_forced_run_writes_manual_files_and_pushes(tmp_path, capsys, sent):
    assert run_eod(["--data-dir", str(tmp_path), "--force"]) == 0
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
    monkeypatch.setattr(job.clock, "in_window", lambda *a: False)
    assert run_eod(["--data-dir", str(tmp_path)]) == 0
    assert "nothing to do" in capsys.readouterr().out
    assert not (tmp_path / "data").exists()
    assert sent == []


def test_missing_topic_fails_without_leaking(tmp_path, capsys, sent, monkeypatch):
    monkeypatch.delenv("NTFY_TOPIC")
    assert run_eod(["--data-dir", str(tmp_path), "--force"]) == 1
    out, _ = capsys.readouterr()
    assert "EOD: FAILED (RuntimeError)" in out
    assert list((tmp_path / "logs").glob("*_eod.log"))


def test_premarket_run_pushes_ep_pm(tmp_path, capsys, sent):
    assert job.main("pm", "Pre-market", "test", ["--data-dir", str(tmp_path), "--force"]) == 0
    out, err = capsys.readouterr()
    assert GAPPER not in out + err
    assert "EP-PM: 1 hits (1 alert), saved" in out
    [message] = sent
    assert message.title.startswith("Trading OS · Pre-market ")
    assert "Market Light for today: n/a" in message.body
    assert "Pre-market: up 4%+ 1 / down 4%+ 0" in message.body
    assert f"{GAPPER}  +12.0%  PM vol 0.4M  $4M" in message.body
    [run_dir] = (tmp_path / "data" / "manual").iterdir()
    assert run_dir.name.split("_")[1] == "pm"


def test_weekly_run_fetches_history_and_stores_no_arrays(tmp_path, capsys, sent, monkeypatch):
    calls = []
    monkeypatch.setattr(
        job.tv,
        "fetch_universe",
        lambda universe, with_history=False: (
            calls.append(with_history) or synthetic_universe(with_history)
        ),
    )
    assert job.main("weekly", "Weekly", "test", ["--data-dir", str(tmp_path), "--force"]) == 0
    assert calls == [True]
    out, err = capsys.readouterr()
    assert GAPPER not in out + err
    [run_dir] = (tmp_path / "data" / "manual").iterdir()
    universe = pd.read_parquet(run_dir / "universe.parquet")
    assert "revenue_q_hist" not in universe.columns
    assert universe.set_index("ticker").loc[GAPPER, "rev_growth_q_prev"] == pytest.approx(40.0)
    [message] = sent
    assert message.title.startswith("Trading OS · Weekly ")


def test_push_failure_still_saves_data(tmp_path, capsys, sent, monkeypatch):
    def down(server, topic, msg):
        raise job.requests.ConnectionError("ntfy down")

    monkeypatch.setattr(job.notify, "send", down)
    monkeypatch.setattr(job, "NTFY_RETRY_WAIT_S", 0)
    assert run_eod(["--data-dir", str(tmp_path), "--force"]) == 1
    out, _ = capsys.readouterr()
    assert "Push: FAILED (ConnectionError), saving data anyway" in out
    assert "EOD: FAILED (PushFailed)" in out
    [run_dir] = (tmp_path / "data" / "manual").iterdir()
    candidates = pd.read_parquet(run_dir / "candidates.parquet")
    assert candidates["pushed"].tolist() == [False]
