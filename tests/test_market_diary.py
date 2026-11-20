"""The market diary: calendar flags, ETF metrics by hand, movers, the news cap, the guard,
write-once and the Markdown. Synthetic data only."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest
import requests

from trading_os import clock, history, market_diary
from trading_os.config import load_config

CFG = load_config()
DAY = dt.date(2026, 11, 18)
PREV = dt.date(2026, 11, 17)
MACRO = {
    "fomc": {dt.date(2026, 12, 9)},
    "cpi": {dt.date(2026, 11, 10)},
    "nfp": {dt.date(2026, 11, 6)},
}


@pytest.fixture(autouse=True)
def _symbols(monkeypatch):
    """Synthetic ETF symbols instead of the real list."""
    monkeypatch.setattr(market_diary, "INDEX_ETFS", ("IDXA",))
    monkeypatch.setattr(market_diary, "SECTOR_ETFS", ("SECA", "SECB"))
    monkeypatch.setattr(market_diary, "THEME_ETFS", ())
    monkeypatch.setattr(market_diary, "ALL_ETFS", ("IDXA", "SECA", "SECB"))


def bars(day, rows):
    df = pd.DataFrame(rows, columns=["ticker", "open", "high", "low", "close", "volume"])
    df["vwap"], df["trades"] = np.nan, pd.array([None] * len(df), dtype="Int64")
    df["session_date"], df["source"], df["adjusted"] = day, "massive", True
    df["fetched_ts"] = pd.Timestamp("2026-11-19", tz="UTC")
    return df[history.BAR_COLUMNS]


def put_bars(data_dir, day, rows):
    history.write_bars(data_dir, "massive", day, bars(day, rows))


@pytest.fixture
def data_dir(tmp_path):
    sessions = clock.sessions_back(CFG.schedule, DAY, 30)
    for i, s in enumerate(sessions):
        etf = [
            ("IDXA", 100 + i, 101 + i, 99 + i, 100 + i, 1e6),
            ("SECA", 50.0, 51.0, 49.0, 50.0 + (i == len(sessions) - 1) * 5, 1e6),
            ("SECB", 50.0, 51.0, 49.0, 50.0 - (i == len(sessions) - 1) * 5, 1e6),
        ]
        stocks = [
            ("STKA", 10, 11, 9, 10.0 if s != DAY else 12.0, 3e6),  # +20 %, $36M
            ("STKB", 10, 11, 9, 10.0 if s != DAY else 8.0, 3e6),  # -20 %, $24M
            ("STKC", 10, 11, 9, 10.0 if s != DAY else 15.0, 1e5),  # too thin
            ("STKD", 3, 4, 2, 3.0 if s != DAY else 4.0, 5e7),  # under $5
        ]
        put_bars(tmp_path, s, etf + stocks)
    cand_dir = tmp_path / "data" / "candidates" / "2026"
    cand_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "signal_id": [f"s{i}" for i in range(5)],
            "scan": ["ep_day"] * 3 + ["mb_up"] * 2,
            "slot": ["eod"] * 5,
            "ticker": ["STKA", "STKB", "STKC", "STKD", "STKE"],
            "pushed": [True, True, False, True, False],
            "rank": [1, 2, 3, 4, 5],
            "grade": ["A+", "C", "C", "B", "A"],
            "earnings_in_sessions": [1.0, 40.0, 3.0, 0.0, 0.0],
        }
    ).to_parquet(cand_dir / f"{DAY.isoformat()}_eod.parquet")
    return tmp_path


class FakeClient:
    def __init__(self, fail_after=None, status=403):
        self.calls = []
        self.fail_after, self.status = fail_after, status

    def grouped_daily(self, day):
        raise requests.HTTPError("no", response=type("R", (), {"status_code": 403})())

    def news_window(self, start, end, ticker=None, limit=20):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise requests.HTTPError("x", response=type("R", (), {"status_code": self.status})())
        self.calls.append((ticker, limit))
        return [
            {
                "title": f"headline {ticker or 'market'}",
                "publisher": "pub",
                "published_utc": "2026-11-18T15:00:00Z",
                "url": "u",
                "tickers": [ticker] if ticker else [],
            }
        ]


def build(data_dir, client=None, **kw):
    return market_diary.build_diary(data_dir, CFG, DAY, macro=MACRO, client=client, **kw)


def meta(df, key):
    row = df[(df["kind"] == "meta") & (df["key"] == key)].iloc[0]
    return row["text"] if pd.notna(row["text"]) else row["value"]


# ---- calendar ---------------------------------------------------------------------------


def flags(day):
    return market_diary.calendar_flags(CFG.schedule, day, MACRO)


def test_macro_flags():
    assert flags(dt.date(2026, 11, 10))["cpi_day"]
    assert flags(dt.date(2026, 11, 6))["jobs_day"]
    assert flags(dt.date(2026, 12, 9))["fomc_day"]
    assert not any(flags(dt.date(2026, 11, 11)).values())


def test_opex_is_the_third_friday_and_quad_witching_in_quarter_months():
    assert flags(dt.date(2026, 12, 18))["opex_day"]
    assert flags(dt.date(2026, 12, 18))["quad_witching"]
    assert flags(dt.date(2026, 11, 20))["opex_day"]
    assert not flags(dt.date(2026, 11, 20))["quad_witching"]
    assert not flags(dt.date(2026, 11, 13))["opex_day"]  # second Friday


def test_opex_moves_to_thursday_when_the_third_friday_is_a_holiday():
    # Juneteenth, Friday 19 June 2026, is a market holiday
    assert flags(dt.date(2026, 6, 18))["opex_day"]
    assert flags(dt.date(2026, 6, 18))["quad_witching"]


def test_half_day():
    assert flags(dt.date(2026, 11, 27))["half_day"]  # day after Thanksgiving
    assert not flags(dt.date(2026, 11, 25))["half_day"]


def test_macro_calendar_covers_next_year():
    """Fails when the calendar needs renewing: it must hold next year's dates."""
    macro = market_diary.load_macro()
    next_year = dt.date.today().year + 1
    for name, days in macro.items():
        assert any(d.year == next_year for d in days), (
            f"macro_calendar.yaml: no {name} for {next_year}"
        )


# ---- ETF metrics, by hand ----------------------------------------------------------------


def test_etf_metrics_by_hand():
    sessions = clock.sessions_back(CFG.schedule, DAY, 25)
    hist = pd.DataFrame(
        {
            "session_date": sessions[:-1],
            "ticker": "IDXA",
            "high": [101.0 + i for i in range(24)],
            "low": [99.0 + i for i in range(24)],
            "close": [100.0 + i for i in range(24)],
        }
    )
    today = pd.DataFrame({"ticker": ["IDXA"], "close": [124.0], "high": [125.0], "low": [123.0]})
    table, _ = market_diary.etf_metrics(hist, today, sessions, ("IDXA",))
    r = table.loc["IDXA"]
    assert r["close"] == 124.0
    assert r["chg_pct"] == pytest.approx((124 / 123 - 1) * 100)
    assert r["ret_5d_pct"] == pytest.approx((124 / 119 - 1) * 100)
    assert r["ret_20d_pct"] == pytest.approx((124 / 104 - 1) * 100)
    assert r["adr20_pct"] == pytest.approx(
        np.mean([(101.0 + i) / (99.0 + i) - 1 for i in range(5, 25)]) * 100
    )
    sma10 = np.mean(range(115, 125))
    assert r["dist_sma10_pct"] == pytest.approx((124 / sma10 - 1) * 100)
    assert r["dist_sma10_adr"] == pytest.approx(r["dist_sma10_pct"] / r["adr20_pct"])
    assert np.isnan(r["dist_sma50_pct"])  # 25 sessions: no 50-day average
    assert r["dist_high52w_pct"] == pytest.approx((124 / 125 - 1) * 100)


def test_etf_without_a_close_on_the_last_session_is_left_out():
    sessions = clock.sessions_back(CFG.schedule, DAY, 5)
    hist = pd.DataFrame(
        {"session_date": sessions[:-1], "ticker": "IDXA", "high": 2.0, "low": 1.0, "close": 1.5}
    )
    today = pd.DataFrame({"ticker": ["SECA"], "close": [3.0]})
    table, _ = market_diary.etf_metrics(hist, today, sessions, ("IDXA", "SECA"))
    assert list(table.index) == ["SECA"]


# ---- movers ------------------------------------------------------------------------------


def test_movers_apply_price_and_dollar_volume_floors(data_dir):
    today = history.load_bars(data_dir, [DAY])
    before = history.load_bars(data_dir, [PREV])
    up, down = market_diary.movers(today, before)
    assert list(up["ticker"][:1]) == ["STKA"] and "STKC" not in set(up["ticker"])
    assert "STKD" not in set(up["ticker"]) | set(down["ticker"])
    assert down["ticker"].iloc[0] == "STKB"
    assert up["chg_pct"].iloc[0] == pytest.approx(20.0)


# ---- the diary ---------------------------------------------------------------------------


def test_diary_without_vix_or_news_key(data_dir):
    df = build(data_dir)
    assert meta(df, "vix") == "null"
    vix = df[df["kind"] == "vix"].iloc[0]
    assert pd.isna(vix["close"])
    assert meta(df, "news") == "no_key"
    assert meta(df, "news_tickers_skipped") == 3  # the pushed tickers, none looked up
    assert set(df["kind"]) >= {"market", "sector", "vix", "heat", "mover_up", "scan", "calendar"}
    sectors = df[df["kind"] == "sector"].set_index("key")
    assert sectors.loc["SECA", "rank"] == 1 and sectors.loc["SECB", "rank"] == 2
    scan = df[(df["kind"] == "scan") & (df["key"] == "ep_day/eod")].iloc[0]
    assert (scan["hits"], scan["pushed"], scan["grade_a_plus"], scan["grade_c"]) == (3, 2, 1, 2)
    assert scan["tickers"] == "STKA,STKB"
    assert (
        df[(df["kind"] == "calendar") & (df["key"] == "pushed_earnings_within_1_session")][
            "value"
        ].iloc[0]
        == 2
    )  # one at 1 session, one at 0


def test_vix_comes_from_the_breadth_row(data_dir):
    path = data_dir / "data" / "breadth" / "2026"
    path.mkdir(parents=True)
    pd.DataFrame(
        {"session_date": [DAY], "up4": [140], "vix_close": [18.6], "vix_chg_pct": [-7.1]}
    ).to_parquet(path / f"{DAY.isoformat()}_eod.parquet")
    df = build(data_dir)
    vix = df[df["kind"] == "vix"].iloc[0]
    assert vix["close"] == pytest.approx(18.6) and vix["chg_pct"] == pytest.approx(-7.1)
    assert meta(df, "vix") == "ok"
    assert df[(df["kind"] == "breadth") & (df["key"] == "up4")]["value"].iloc[0] == 140


def test_news_lookups_are_capped_at_15_tickers(data_dir):
    cands = pd.DataFrame(
        {
            "signal_id": [f"x{i}" for i in range(20)],
            "scan": "ep_day",
            "slot": "eod",
            "ticker": [f"T{chr(65 + i)}" for i in range(20)],
            "pushed": True,
            "rank": range(20),
            "grade": "C",
        }
    )
    cands.to_parquet(data_dir / "data" / "candidates" / "2026" / f"{DAY.isoformat()}_pm.parquet")
    client = FakeClient()
    df = build(data_dir, client=client)
    assert len(client.calls) == 1 + market_diary.MAX_NEWS_TICKERS  # market + 15 tickers
    assert meta(df, "news_tickers_looked_up") == 15
    assert meta(df, "news_tickers_skipped") == 20 + 3 - 15
    assert (df["kind"] == "news_market").sum() == 1
    assert df[df["kind"] == "news_ticker"]["key"].nunique() == 15


def test_news_failure_is_recorded_and_stops_the_lookups(data_dir):
    client = FakeClient(fail_after=1)
    df = build(data_dir, client=client)
    assert meta(df, "news") == "error 403"
    assert len(client.calls) == 1
    assert (df["kind"] == "news_market").sum() == 1  # what was fetched before is kept


def test_news_off_and_backfill_flag(data_dir):
    df = build(data_dir, client=FakeClient(), news=False, backfilled=True)
    assert meta(df, "news") == "disabled" and meta(df, "news_backfilled") == 1


def test_markdown_is_facts_and_says_when_vix_is_missing(data_dir):
    df = build(data_dir)
    md = market_diary.render_md(DAY, df)
    assert md.startswith("# Market diary 2026-11-18")
    assert "VIX: not available" in md
    for part in ("## Market", "## Sectors and themes", "## Our scans", "## News", "## Sources"):
        assert part in md
    assert "ep_day/eod: 3 hits, 2 pushed" in md


# ---- write once, the guard ---------------------------------------------------------------


def test_second_write_changes_nothing_unless_forced(data_dir):
    df = build(data_dir)
    assert market_diary.write_diary(data_dir, DAY, df, "first\n", force=False)
    parquet, md = market_diary.diary_paths(data_dir, DAY)
    before = parquet.read_bytes()
    assert not market_diary.write_diary(data_dir, DAY, df, "second\n", force=False)
    assert parquet.read_bytes() == before and md.read_text() == "first\n"
    assert market_diary.write_diary(data_dir, DAY, df, "third\n", force=True)
    assert md.read_text() == "third\n"
    assert pd.read_parquet(parquet).shape == df.shape


def test_run_twice_writes_once(data_dir, monkeypatch, capsys):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.setattr(market_diary, "load_macro", lambda: MACRO)
    args = ["--data-dir", str(data_dir), "--date", DAY.isoformat(), "--force"]
    assert market_diary.main(args[:-1]) == 0  # no --force: the day is past, so it is closed
    parquet, _ = market_diary.diary_paths(data_dir, DAY)
    first = parquet.read_bytes()
    assert market_diary.main(args[:-1]) == 0
    assert parquet.read_bytes() == first
    assert "nothing new to write" in capsys.readouterr().out


def test_guard_future_and_unclosed_sessions_write_nothing(data_dir, monkeypatch):
    monkeypatch.setattr(market_diary, "load_macro", lambda: MACRO)
    future = dt.date.today() + dt.timedelta(days=10)
    assert market_diary.main(["--data-dir", str(data_dir), "--date", future.isoformat()]) == 0
    assert not (data_dir / "data" / "diary").exists()
    now = dt.datetime(2026, 11, 18, 20, 0, tzinfo=dt.UTC)  # 15:00 New York: still open
    assert not market_diary._closed(CFG, DAY, now)
    assert market_diary._closed(CFG, DAY, now + dt.timedelta(hours=2))
    assert not market_diary._closed(CFG, dt.date(2026, 11, 21), now + dt.timedelta(days=5))  # Sat


def test_backfill_range_writes_each_session_once(data_dir, monkeypatch):
    monkeypatch.setattr(market_diary, "load_macro", lambda: MACRO)
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    args = ["--data-dir", str(data_dir), "--from", "2026-11-12", "--to", "2026-11-18"]
    assert market_diary.main(args) == 0
    files = sorted((data_dir / "data" / "diary" / "2026").glob("*.parquet"))
    assert [f.stem for f in files] == [
        "2026-11-12",
        "2026-11-13",
        "2026-11-16",
        "2026-11-17",
        "2026-11-18",
    ]
    df = pd.read_parquet(files[0])
    assert meta(df, "news_backfilled") == 1
