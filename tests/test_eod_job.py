"""End-to-end test of the job runner with a synthetic TradingView frame (no network)."""

import datetime as dt

import pandas as pd
import pytest

from trading_os import clock, history, job, notify, store, tv
from trading_os.config import load_config


def ep_day_pushing(cfg):
    """`cfg` with EP-Day pushing again: these tests use it as their example pushing scan
    (the real config only saves it since 21 Oct 2026)."""
    import dataclasses
    from types import MappingProxyType

    scans = dict(cfg.scans)
    for name in ("ep_day", "ep9m", "breakout_trigger"):  # saved only since 21 Oct 2026
        scans[name] = dataclasses.replace(scans[name], action="push")
    return dataclasses.replace(cfg, scans=MappingProxyType(scans))


@pytest.fixture(autouse=True)
def _grades_off(monkeypatch):
    """These tests pin the push layout without study grades (tests/test_grade_live.py has
    the graded one)."""
    import dataclasses
    from types import MappingProxyType

    cfg = ep_day_pushing(load_config())  # EP-Day is the example pushing scan here
    off = dataclasses.replace(cfg, grading=MappingProxyType({**cfg.grading, "enabled": False}))
    monkeypatch.setattr(job, "load_config", lambda *a, **k: off)


def run_eod(argv):
    return job.main("eod", "EOD", "test", argv)


def scans_off(monkeypatch, *names):
    """Switch scans off for one test, so it pins one section of the push."""
    import dataclasses
    from types import MappingProxyType

    cfg = job.load_config()
    scans = {
        n: dataclasses.replace(s, enabled=False) if n in names else s for n, s in cfg.scans.items()
    }
    cfg = dataclasses.replace(cfg, scans=MappingProxyType(scans))
    monkeypatch.setattr(job, "load_config", lambda *a, **k: cfg)


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
    index = {"close": 18.58, "chg_pct": -7.07, "pm_change_pct": 0.3}
    index |= {f"sma{w}": 20.0 for w in (10, 20, 50, 200)}
    monkeypatch.setattr(job.tv, "fetch_index", lambda symbol: index)
    monkeypatch.setattr(job.tv, "fetch_details", lambda symbols, fields: pd.DataFrame())
    monkeypatch.setenv("NTFY_TOPIC", "test-topic")
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
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
    assert message.title.endswith("(manual run)")
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
    assert message.title.startswith("Pre-market ")
    # The push starts with the Light and QQQ against its MAs, then the stocks (Emil, 23 Oct
    # 2026); the breadth, movers and index lines stay in the report.
    head = message.body.split("\n\n")[0].split("\n")
    assert head == ["⚪ Market Light n/a (needs an EOD run)", "QQQ below 10, 20, 50, 200"]
    assert "Pre-market 4%" not in message.body and "SPY pre-market" not in message.body
    assert f"▸ {GAPPER}  +12.0% PM  vol 0.4M  $4M" in message.body
    [run_dir] = (tmp_path / "data" / "manual").iterdir()
    assert run_dir.name.split("_")[1] == "pm"
    report = "".join(p.read_text(encoding="utf-8") for p in run_dir.rglob("*.md"))
    assert "SPY pre-market 🟢 +0.3% · VIX 18.6 -7.1%" in report  # stubbed quotes
    assert "Pre-market 4%: 🟢1 🔴0" in report


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
    assert message.title.startswith("Weekly ")


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


def test_eod_uses_exact_rvol_once_history_exists(tmp_path, capsys, sent):
    cfg = load_config()
    session = clock.session_date(cfg.schedule, "eod", pd.Timestamp.now(tz="UTC").to_pydatetime())
    past = clock.sessions_back(cfg.schedule, session, 56)[:-1]  # 55 sessions before the run's
    for day in past:
        snap = pd.DataFrame(
            {
                "run_ts": [pd.Timestamp(f"{day} 20:17", tz="UTC")] * 2,
                "session_date": [pd.Timestamp(day)] * 2,
                "ticker": [GAPPER, QUIET],
                "open": [10.0, 11.0],
                "high": [10.5, 11.5],
                "low": [9.5, 10.5],
                "close": [10.0, 11.0],
                "volume": [750_000.0, 900_000.0],
            }
        )
        path = history.universe_snapshot_path(tmp_path, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        snap.to_parquet(path, index=False)
    assert run_eod(["--data-dir", str(tmp_path), "--force"]) == 0
    out = capsys.readouterr().out
    assert "exact RVOL on 2 rows" in out
    [run_dir] = (tmp_path / "data" / "manual").iterdir()
    cands = pd.read_parquet(run_dir / "candidates.parquet")
    row = cands[cands["scan"] == "ep_day"].iloc[0]
    assert row["rvol_basis"] == "history_50d_excl_today"
    assert row["rvol50"] == pytest.approx(3_000_000 / 750_000)  # today's volume / prior 50-day mean


def test_push_carries_position_size_when_account_is_set(tmp_path, capsys, sent, monkeypatch):
    settings = tmp_path / "settings" / "account.yaml"
    settings.parent.mkdir(parents=True)
    settings.write_text("currency: DKK\nsize: 500000\nrisk_pct: 0.5\n", encoding="utf-8")
    monkeypatch.setattr(job.tv, "fetch_fx", lambda symbol: 6.667)
    universe = synthetic_universe()
    universe.loc[universe["ticker"] == GAPPER, "adr14_usd_tv"] = 1.5
    monkeypatch.setattr(job.tv, "fetch_universe", lambda u, with_history=False: universe)
    assert run_eod(["--data-dir", str(tmp_path), "--force"]) == 0
    out, _ = capsys.readouterr()
    assert "Sizing: added" in out and "500000" not in out and "374" not in out  # no amounts in logs
    [message] = sent
    # GAPPER: close 11.50, day low 10.50, ADR 1.50 -> stop at the day low, 1.00 risk per share;
    # 2,500 DKK / 6.667 = $374.98 -> 374 shares ($4.3k), risk $374.
    dot = "·"
    assert f"{GAPPER}  +18.0%" in message.body
    assert f"   Buy 11.50 {dot} 🛑 10.50 (day low)\n   374 sh {dot} $4.3k {dot} risk $374" in (
        message.body
    )
    [run_dir] = (tmp_path / "data" / "manual").iterdir()
    cands = pd.read_parquet(run_dir / "candidates.parquet")
    ep = cands[cands["scan"] == "ep_day"].iloc[0]
    assert ep["plan_shares"] > 0 and ep["plan_fx_rate"] == 6.667


def test_push_carries_facts_and_headline(tmp_path, capsys, sent, monkeypatch):
    universe = synthetic_universe()
    universe["tv_ticker"] = "NASDAQ:" + universe["ticker"]
    universe["float_shares"] = 6e6
    monkeypatch.setattr(job.tv, "fetch_universe", lambda u, with_history=False: universe)
    asked = []

    def details(symbols, fields):
        asked.append(symbols)
        return pd.DataFrame(
            {"eps_surprise_percent_fq": [12.0], "revenue_surprise_percent_fq": [3.0]},
            index=pd.Index([f"NASDAQ:{GAPPER}"], name="tv_ticker"),
        ).assign(total_revenue_fq_h=[[150, 140, 120, 110, 100, 100, 90, 80]])

    monkeypatch.setattr(job.tv, "fetch_details", details)
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    fresh = pd.Timestamp.now(tz="UTC").isoformat()
    item = {"title": "Signs a supply deal", "publisher": "PR", "published_utc": fresh, "url": ""}
    monkeypatch.setattr(job_massive(), "news", lambda self, ticker, limit=3: [item])
    assert run_eod(["--data-dir", str(tmp_path), "--force"]) == 0
    out, _ = capsys.readouterr()
    assert "Context: added" in out and "supply deal" not in out
    facts = [a for a in asked if len(a) < 10]  # the other request is the sector ETFs
    assert facts == [[f"NASDAQ:{GAPPER}"]]  # one request, pushed names only
    [message] = sent
    assert "no earnings" not in message.body  # silence means no report
    assert "float 6M (50% traded)" in message.body and "rev +50% / +40%" in message.body
    assert "   📰 Signs a supply deal (PR)" in message.body
    [run_dir] = (tmp_path / "data" / "manual").iterdir()
    ep = pd.read_parquet(run_dir / "candidates.parquet").query("scan == 'ep_day'").iloc[0]
    assert ep["ctx_eps_surprise_pct"] == 12.0 and ep["ctx_news_title"] == "Signs a supply deal"


def test_context_failure_still_pushes(tmp_path, capsys, sent, monkeypatch):
    def down(symbols, fields):
        raise RuntimeError(f"{GAPPER} not found")

    monkeypatch.setattr(job.tv, "fetch_details", down)
    monkeypatch.setattr(job, "TV_RETRY_WAIT_S", 0)
    assert run_eod(["--data-dir", str(tmp_path), "--force"]) == 0
    out, err = capsys.readouterr()
    assert "Context: FAILED (RuntimeError)" in out and GAPPER not in out + err
    [message] = sent
    assert GAPPER in message.body and "no earnings" not in message.body


def job_massive():
    from trading_os.massive import MassiveClient

    return MassiveClient


def test_headline_window_reaches_back_to_the_previous_session(monkeypatch):
    cfg = load_config()
    seen = []

    def news(self, ticker, limit=3):
        seen.append(ticker)
        # Friday 16 Oct after the close; a Monday 19 Oct run is > 48 h later.
        return [{"title": "Beats", "publisher": "PR", "published_utc": "2026-10-16T20:30:00Z"}]

    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    monkeypatch.setattr(job_massive(), "news", news)
    monday = job._news_lookup(cfg, dt.date(2026, 10, 19))
    assert monday("ABC")["title"] == "Beats"
    tuesday = job._news_lookup(cfg, dt.date(2026, 10, 21))  # Wednesday: previous session is Tuesday
    assert tuesday("ABC") is None


def run_intraday(slot, argv):
    return job.main(slot, notify.SLOT_LABELS[slot], "test", argv)


def intraday_universe():
    universe = synthetic_universe()
    # GAPPER normally trades 1M a day (RVOL base); 12x the usual volume by now -> 12M pace.
    universe.loc[universe["ticker"] == GAPPER, "rvol_at_time_tv"] = 12.0
    return universe


def test_intraday_check_pushes_pace_without_a_universe_snapshot(
    tmp_path, capsys, sent, monkeypatch
):
    scans_off(monkeypatch, "ep_am")  # its own test below
    monkeypatch.setattr(job.tv, "fetch_universe", lambda u, with_history=False: intraday_universe())
    assert run_intraday("am", ["--data-dir", str(tmp_path), "--force"]) == 0
    out, err = capsys.readouterr()
    assert "EP9M pace: 1 hits (1 alert), saved" in out and GAPPER not in out + err
    [run_dir] = (tmp_path / "data" / "manual").iterdir()
    assert "_am_" in run_dir.name
    assert not (run_dir / "universe.parquet").exists()  # intraday keeps candidates only
    cands = pd.read_parquet(run_dir / "candidates.parquet")
    assert cands["scan"].tolist() == ["ep9m_pace"]  # nothing else runs during the session
    assert cands["proj_volume"].iloc[0] == pytest.approx(12e6) and bool(cands["pushed"].iloc[0])
    [message] = sent
    assert message.title.startswith("Intraday 10:15 ") and "EP9M pace 1" in message.title
    assert f"▸ {GAPPER}  +20.0%  3.0M → pace 12M" in message.body


def test_1017_check_flags_the_ep_gap_for_a_1030_buy(tmp_path, capsys, sent, monkeypatch):
    monkeypatch.setattr(job.tv, "fetch_universe", lambda u, with_history=False: intraday_universe())
    assert run_intraday("am", ["--data-dir", str(tmp_path), "--force"]) == 0
    out, err = capsys.readouterr()
    assert "EP 10:30: 1 hits (1 alert), saved" in out and GAPPER not in out + err
    [run_dir] = (tmp_path / "data" / "manual").iterdir()
    cands = pd.read_parquet(run_dir / "candidates.parquet")
    assert cands.loc[cands["scan"] == "ep_am", "ticker"].tolist() == [GAPPER]
    [message] = sent
    assert "EP 10:30 1" in message.title and f"▸ {GAPPER}  +18.0%" in message.body


def test_after_hours_check_flags_earnings_movers(tmp_path, capsys, sent, monkeypatch):
    session = clock.session_date(load_config().schedule, "ah", dt.datetime.now(dt.UTC))
    release = pd.Timestamp(f"{session} 20:05", tz="UTC")  # after the close, New York

    def universe(u, with_history=False):
        df = synthetic_universe()
        df["ah_change_pct"], df["ah_volume"], df["ah_price"] = 10.0, 200_000.0, 12.65
        df.loc[df["ticker"] == GAPPER, "earnings_date_last"] = release
        return df  # QUIET moves as much after hours, but without a report

    monkeypatch.setattr(job.tv, "fetch_universe", universe)
    assert run_intraday("ah", ["--data-dir", str(tmp_path), "--force"]) == 0
    out, err = capsys.readouterr()
    assert "EP-AH: 1 hits (1 alert), saved" in out and GAPPER not in out + err
    [run_dir] = (tmp_path / "data" / "manual").iterdir()
    assert "_ah_" in run_dir.name and not (run_dir / "universe.parquet").exists()
    cands = pd.read_parquet(run_dir / "candidates.parquet")
    assert cands["scan"].tolist() == ["ep_ah"] and cands["ticker"].tolist() == [GAPPER]
    assert cands["ah_price"].tolist() == [12.65]
    [message] = sent
    assert message.title.startswith("After hours 16:50 ") and f"▸ {GAPPER}  +10.0%" in message.body


def test_1030_ep_flagged_last_evening_gets_a_note_not_a_second_buy(
    tmp_path, capsys, sent, monkeypatch
):
    monkeypatch.setattr(job.tv, "fetch_universe", lambda u, with_history=False: intraday_universe())
    schedule, now = load_config().schedule, dt.datetime.now(dt.UTC)
    evening = clock.previous_session(schedule, clock.session_date(schedule, "am", now))
    ctx = store.RunContext(session=evening, slot="ah", run_ts=now, run_kind="scheduled")
    path = store.run_paths(tmp_path, ctx)["candidates"]
    path.parent.mkdir(parents=True)
    pd.DataFrame({"scan": ["ep_ah"], "ticker": [GAPPER], "pushed": [True]}).to_parquet(path)
    assert run_intraday("am", ["--data-dir", str(tmp_path), "--force"]) == 0
    out, _ = capsys.readouterr()
    assert "EP 10:30: 1 flagged last evening" in out
    [message] = sent
    assert f"▸ {GAPPER}  +18.0%  ↑ flagged last evening (16:50)" in message.body


def test_midday_check_skips_names_sent_at_1015(tmp_path, capsys, sent, monkeypatch):
    monkeypatch.setattr(job.tv, "fetch_universe", lambda u, with_history=False: intraday_universe())
    now = dt.datetime.now(dt.UTC)
    session = clock.session_date(load_config().schedule, "mid", now)
    morning = store.RunContext(session=session, slot="am", run_ts=now, run_kind="scheduled")
    path = store.run_paths(tmp_path, morning)["candidates"]
    path.parent.mkdir(parents=True)
    pd.DataFrame({"scan": ["ep9m_pace"], "ticker": [GAPPER], "pushed": [True]}).to_parquet(path)
    assert run_intraday("mid", ["--data-dir", str(tmp_path), "--force"]) == 0
    out, _ = capsys.readouterr()
    assert "Push: 1 already sent at 10:15, skipped" in out
    [message] = sent
    assert "Nothing new: EP9M pace (1 sent earlier)" in message.body
    assert GAPPER not in message.body


def test_intraday_script_picks_the_check_by_time(monkeypatch):
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent / "scripts" / "intraday.py"
    spec = importlib.util.spec_from_file_location("intraday_script", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.pick_slot(["--slot", "mid", "--force"]) == ("mid", ["--force"])
    monkeypatch.setattr(module.clock, "in_window", lambda schedule, slot, now: slot == "mid")
    assert module.pick_slot(["--data-dir", "x"]) == ("mid", ["--data-dir", "x"])
    monkeypatch.setattr(module.clock, "in_window", lambda schedule, slot, now: False)
    assert module.pick_slot([])[0] == "am"  # the time guard then turns it away


def test_intraday_pivot_alert_uses_the_latest_eod_levels(tmp_path, capsys, sent, monkeypatch):
    scans_off(monkeypatch, "ep_am")
    universe = intraday_universe()
    universe.loc[universe["ticker"] == GAPPER, "rvol_at_time_tv"] = 2.0  # 2M pace: no EP9M
    monkeypatch.setattr(job.tv, "fetch_universe", lambda u, with_history=False: universe)
    day = dt.date(2026, 10, 1)
    events = pd.DataFrame(
        [
            {
                "ticker": GAPPER,
                "list": "bo_watch",
                "status": "active",
                "status_date": day,
                "added_date": day,
                "source_signal_id": "s",
                "reason": "B1-B4 pass",
                "run_ts": pd.Timestamp("2026-10-01 20:20", tz="UTC"),
            }
        ]
    )
    (tmp_path / "data" / "watchlists" / "2026").mkdir(parents=True)
    events.to_parquet(tmp_path / "data" / "watchlists" / "2026" / "2026-10-01_eod.parquet")
    levels = pd.DataFrame(
        {
            "scan": ["breakout_watch"],
            "ticker": [GAPPER],
            "tier": ["alert"],
            "pushed": [True],
            "pivot": [11.40],
            "order_stop": [10.80],
            "bo_prior_move_pct": [60.0],
            "bo_ma_stacked": [True],
        }
    )
    (tmp_path / "data" / "candidates" / "2026").mkdir(parents=True)
    levels.to_parquet(tmp_path / "data" / "candidates" / "2026" / "2026-10-01_eod.parquet")
    assert run_intraday("am", ["--data-dir", str(tmp_path), "--force"]) == 0
    out, err = capsys.readouterr()
    assert "BO levels: 1 of 1 BO-Watch names have a pivot" in out and GAPPER not in out + err
    [message] = sent
    assert f"▸ {GAPPER}  +20.0%  over pivot +0.9%  RVOL 2.0\n   Pivot 11.40 · 🛑 10.80" in (
        message.body
    )
    assert "   prior move +60%" in message.body and "Nothing new: EP9M pace" in message.body
    [run_dir] = (tmp_path / "data" / "manual").iterdir()
    row = pd.read_parquet(run_dir / "candidates.parquet").query("scan == 'pivot_watch'").iloc[0]
    assert row["pivot_from_session"] == "2026-10-01" and bool(row["pivot_crossed"])
