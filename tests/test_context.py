import pandas as pd
import pytest

from trading_os import context

DOT = "·"
TICKER = "".join(["CT", "XA"])  # built at runtime, like real data


def details():
    raw = pd.DataFrame(
        {
            "tv_ticker": [f"NASDAQ:{TICKER}"],
            "eps_surprise_percent_fq": [6.2],
            "revenue_surprise_percent_fq": [-4.4],
            "earnings_release_time": [1.0],
            "Perf.Y": [-40.0],
            # Latest first: q0 vs q4 and q1 vs q5.
            "total_revenue_fq_h": [[206.0, 180.0, 150.0, 120.0, 100.0, 100.0, 90.0, 80.0]],
            "earnings_per_share_diluted_fq_h": [[2.28, 1.8, 1.0, 0.5, 1.0, 1.0, 0.9, 0.8]],
        }
    ).set_index("tv_ticker")
    return context.growth_columns(raw.rename(columns=context.DETAIL_FIELDS))


def hit(**extra):
    row = {
        "ticker": TICKER,
        "tv_ticker": f"NASDAQ:{TICKER}",
        "chg_pct": 50.0,
        "perf_6m_tv": -55.0,  # includes today's +50 %
        "volume": 168e6,
        "pm_volume": 9.5e6,
        "float_shares": 19e6,
    }
    return pd.DataFrame([row | extra])


def test_growth_columns_from_histories():
    d = details().iloc[0]
    assert d["ctx_eps_growth_q"] == pytest.approx(128)
    assert d["ctx_eps_growth_q_prev"] == pytest.approx(80)
    assert d["ctx_rev_growth_q"] == pytest.approx(106)
    assert d["ctx_rev_growth_q_prev"] == pytest.approx(80)
    assert "ctx_eps_hist" not in d and "ctx_rev_hist" not in d


def test_add_context_joins_details_and_excludes_today_from_the_prior_move():
    out = context.add_context(hit(), details()).iloc[0]
    assert out["ctx_eps_surprise_pct"] == 6.2
    assert out["ctx_earnings_time"] == 1.0
    # 6M return -55 % including today's +50 %: 0.45 / 1.5 - 1 = -70 % before the gap.
    assert out["ctx_prior_6m_pct"] == pytest.approx(-70)
    assert out["ctx_float_turnover"] == pytest.approx(168 / 19)
    assert bool(out["ctx_done"])
    assert pd.isna(out["ctx_news_title"])


def test_add_context_before_the_open_uses_pm_volume_and_the_full_6m_return():
    out = context.add_context(hit(), details(), premarket=True).iloc[0]
    assert out["ctx_prior_6m_pct"] == pytest.approx(-55)
    assert out["ctx_float_turnover"] == pytest.approx(9.5 / 19)


def test_add_context_without_details_still_marks_rows():
    out = context.add_context(hit(), pd.DataFrame()).iloc[0]
    assert pd.isna(out["ctx_eps_growth_q"]) and bool(out["ctx_done"])


def test_add_context_news():
    item = {
        "title": "Company raises guidance",
        "publisher": "Reuters",
        "published_utc": "2026-10-16T16:05:00Z",
        "url": "https://example.com/a",
    }
    asked = []
    out = context.add_context(hit(), details(), lambda t: asked.append(t) or item).iloc[0]
    assert asked == [TICKER]
    assert out["ctx_news_title"] == "Company raises guidance"
    assert out["ctx_news_publisher"] == "Reuters"


def test_ep_line_reads_like_the_spec_example():
    row = context.add_context(hit(), details()).iloc[0].to_dict()
    row |= {
        "earnings_flag": True,
        "earnings_date_last": pd.Timestamp("2026-10-15 20:05", tz="UTC"),
        "close": 12.0,
        "high_52w": 30.0,
        "ma200": 15.0,
        "industry": "Financial Conglomerates",
    }
    assert context.ep_line(row) == (
        f"   📢 earnings 10-15 after close {DOT} EPS +128% / +80% (beat +6%) {DOT} "
        f"rev +106% / +80% (miss -4%) {DOT} float 19M (8.8x traded) {DOT} 6M before -70% {DOT} "
        f"-60% from 52w high {DOT} ❌ below 200d {DOT} Financial Conglomerates"
    )


def test_ep_line_premarket_measures_the_gap_from_the_pm_price():
    row = {
        "earnings_flag": False,
        "close": 10.0,
        "pm_price": 14.0,
        "high_52w": 14.1,
        "ma200": 12.0,
    }
    line = context.ep_line(row, premarket=True)
    assert line == f"   at 52w high {DOT} ✅ above 200d"
    assert "below 200d" in context.ep_line(row)  # the close is under the 200d


def test_breakout_line_uses_the_trigger_columns():
    row = {
        "trig_prior_move_pct": 85.0,
        "bo_prior_move_pct": 10.0,
        "ret_63": 40.0,
        "ret_126": 120.0,
        "pct_from_52w_high": -2.0,
        "adr20_pct": 6.3,
        "trig_ma_stacked": True,
        "ctx_eps_growth_q": 45.0,
        "ctx_rev_growth_q": 30.0,
        "industry": "Semiconductors",
    }
    assert context.breakout_line(row, "breakout_trigger") == (
        f"   prior move +85% {DOT} 3M +40% {DOT} 6M +120% {DOT} -2% from 52w high {DOT} "
        f"ADR 6.3% {DOT} ✅ MA 10>20>50 {DOT} EPS +45% {DOT} rev +30% {DOT} Semiconductors"
    )
    assert context.breakout_line(row, "breakout_watch").startswith("   prior move +10%")


def test_news_line_trims_and_shows_new_york_time():
    row = {
        "ctx_news_title": "x" * 200,
        "ctx_news_publisher": "Reuters",
        "ctx_news_time": "2026-10-16T16:05:00Z",
    }
    line = context.news_line(row)
    assert line.endswith('…" (Reuters, 10-16 12:05 ET)')
    assert len(line.split('"')[1]) == 110
    assert context.news_line({"ctx_news_title": float("nan")}) is None


def test_lines_per_scan():
    row = {"earnings_flag": False, "ctx_news_title": "Deal signed", "ctx_news_publisher": "PR"}
    assert len(context.lines(row, "ep_day")) == 2
    assert len(context.lines(row, "breakout_watch")) == 1
    assert context.lines(row, "mb_up") == []


def test_formatting_caps_tiny_bases_and_avoids_minus_zero():
    row = {
        "earnings_flag": False,
        "ctx_eps_growth_q": 5838.0,
        "ctx_eps_growth_q_prev": -11320.0,
        "ctx_eps_surprise_pct": -0.3,
        "ctx_rev_growth_q": -0.4,
        "ctx_rev_growth_q_prev": 0.2,
        "ctx_rev_surprise_pct": 0.6,
        "float_shares": 1.9e9,
        "ctx_float_turnover": 0.003,
    }
    line = context.ep_line(row)
    assert f"EPS >+999% / <-999% (in line) {DOT} rev +0% / +0% (beat +1%)" in line
    assert "float 1.9B (<1% traded)" in line
    assert "(12% traded)" in context.ep_line(row | {"ctx_float_turnover": 0.12})
