import datetime as dt

import pandas as pd

from trading_os import notify
from trading_os.config import load_config as _load_config
from trading_os.store import RunContext


def ep_day_pushing(cfg):
    """`cfg` with EP-Day pushing again: these tests use it as their example pushing scan
    (the real config only saves it since 21 Oct 2026)."""
    import dataclasses
    from types import MappingProxyType

    scans = dict(cfg.scans)
    scans["ep_day"] = dataclasses.replace(scans["ep_day"], action="push")
    return dataclasses.replace(cfg, scans=MappingProxyType(scans))


def load_config():
    """EP-Day pushing: these tests pin the push layout with it as the example scan."""
    return ep_day_pushing(_load_config())


CTX = RunContext(
    session=dt.date(2026, 10, 19),
    slot="eod",
    run_ts=dt.datetime(2026, 10, 19, 20, 18, tzinfo=dt.UTC),
    run_kind="scheduled",
)
DOT = "·"


def hits(n_alert, n_log=0):
    rows = []
    for i in range(n_alert + n_log):
        rows.append(
            {
                "ticker": f"T{i:02d}",
                "rank": i + 1,
                "tier": "alert" if i < n_alert else "log",
                "gap_pct": 30.0 - i,
                "rvol50": 5.06,
                "dollar_volume": 82_000_000.0,
                "earnings_flag": i == 0,
            }
        )
    columns = ["ticker", "rank", "tier", "gap_pct", "rvol50", "dollar_volume", "earnings_flag"]
    return pd.DataFrame(rows, columns=columns)


def test_format_hit():
    row = {
        "ticker": "ABCD",
        "gap_pct": 14.2,
        "rvol50": 5.1,
        "dollar_volume": 82e6,
        "earnings_flag": True,
    }
    assert notify.format_hit(row) == "ABCD  +14.2%  RVOL 5.1  $82M  📢"
    row |= {"dollar_volume": 2.34e9, "earnings_flag": False, "rvol50": 333.0}
    assert notify.format_hit(row) == "ABCD  +14.2%  RVOL 333  $2.3B"
    # EP9M shows the day's change instead of the gap.
    assert notify.format_hit(row | {"chg_pct": 6.0}, "chg_pct").startswith("ABCD  +6.0%")


def test_select_for_push_alert_tier_and_limit():
    cfg = load_config()
    results = {"ep_day": hits(n_alert=12, n_log=3)}
    chosen = notify.select_for_push(results, cfg)["ep_day"]
    assert len(chosen) == cfg.notify["max_tickers_per_scan"] == 10
    assert set(chosen["tier"]) == {"alert"}
    assert chosen["rank"].tolist() == list(range(1, 11))


def test_message_title_counts_and_sections():
    cfg = load_config()
    results = {"ep_day": hits(n_alert=2, n_log=1)}
    msg = notify.build_message(CTX, results, notify.select_for_push(results, cfg), cfg)
    assert msg.title == f"EOD Mon 19 Oct 16:18 NY {DOT} 22:18 CPH {DOT} EP 2"
    assert msg.body.splitlines() == [
        f"━━ ⚡ EP-Day {DOT} 2 of 3 ━━",
        "▸ T00  +30.0%  RVOL 5.1  $82M  📢",
        "▸ T01  +29.0%  RVOL 5.1  $82M",
    ]
    assert msg.click is None


def test_message_without_hits_and_the_market_icon():
    cfg = load_config()
    results = {"ep_day": hits(0)}
    msg = notify.build_message(CTX, results, notify.select_for_push(results, cfg), cfg)
    assert msg.title == f"EOD Mon 19 Oct 16:18 NY {DOT} 22:18 CPH {DOT} no alerts"
    assert msg.body == "Nothing new: EP-Day"
    results = {"ep_day": hits(0, n_log=2)}
    header = ["🟡 Market Light YELLOW"]
    msg = notify.build_message(
        CTX, results, notify.select_for_push(results, cfg), cfg, header, click="https://x/r.md"
    )
    assert msg.title.startswith("🟡 EOD Mon 19 Oct")
    assert msg.body.splitlines() == [
        "🟡 Market Light YELLOW",
        "",
        "Nothing new: EP-Day (2 below alert tier)",
        "Tap for the full report with charts.",
    ]
    assert msg.click == "https://x/r.md"


def test_a_stock_shown_above_gets_one_line():
    cfg = load_config()
    day = hits(1).assign(ctx_done=True)
    nine = day.assign(chg_pct=40.0)
    results = {"ep_day": day, "ep9m": nine}
    msg = notify.build_message(CTX, results, notify.select_for_push(results, cfg), cfg)
    assert "▸ T00  +40.0%  ↑ see EP-Day" in msg.body
    assert msg.body.count("\n   ") == 1  # the facts appear once, under EP-Day


def test_send_posts_json_with_the_report_link(monkeypatch):
    calls = {}

    class Ok:
        def raise_for_status(self):
            calls["checked"] = True

    def fake_post(url, json, timeout):
        calls.update(url=url, json=json)
        return Ok()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    notify.send("https://ntfy.sh", "topic-x", notify.Message("t", "b", click="https://x"))
    assert calls["url"] == "https://ntfy.sh/"
    assert calls["json"]["topic"] == "topic-x" and calls["json"]["click"] == "https://x"
    assert calls["json"]["title"] == "t" and calls["json"]["message"] == "b"
    assert calls["checked"]


def test_report_url_needs_the_repo_owner(monkeypatch):
    cfg = load_config()
    monkeypatch.delenv("GITHUB_REPOSITORY_OWNER", raising=False)
    assert notify.report_url(cfg, "reports/2026/a.md") is None
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "someone")
    assert notify.report_url(cfg, "reports/2026/a.md") == (
        "https://github.com/someone/trading-os-data/blob/main/reports/2026/a.md"
    )


def test_breakout_lines_show_flags_and_the_plan():
    row = {
        "ticker": "BRKO",
        "pivot": 15.12,
        "order_stop": 14.88,
        "risk_adr": 1.0,
        "base_len": 12,
        "b1": True,
        "b2": True,
        "b3": False,
        "b4": True,
        "b5": True,
        "chg_pct": 6.8,
        "trig_rvol": 2.5,
    }
    assert notify.format_breakout(row, "breakout_watch") == "BRKO  base 12d  B🟩🟩🟥🟩"
    assert (
        notify.format_breakout(row | {"b3": True}, "breakout_watch") == "BRKO  base 12d  B🟩🟩🟩🟩"
    )
    assert notify.format_breakout(row, "breakout_trigger") == "BRKO  +6.8%  RVOL 2.5  B🟩🟩🟥🟩🟩"
    assert notify.plan_lines(row) == [f"Pivot 15.12 {DOT} 🛑 14.88"]  # no account file
    sized = row | {
        "plan_shares": 1500,
        "plan_entry": 15.12,
        "plan_stop": 14.88,
        "plan_stop_basis": "order stop, buy-stop at pivot",
        "plan_position_usd": 22680.0,
        "plan_risk_usd": 360.0,
        "plan_capped": False,
    }
    assert notify.plan_lines(sized) == [
        f"Buy-stop 15.12 {DOT} 🛑 14.88 (1.0 ADR)",
        f"1,500 sh {DOT} $22.7k {DOT} risk $360",
    ]


def test_facts_only_for_rows_with_them_and_wrapped():
    row = {"ticker": "ABCD", "gap_pct": 14.2, "rvol50": 5.1, "dollar_volume": 82e6}
    assert [x.text for x in notify._block(row, "ep_day", "eod")] == [
        "▸ ABCD  +14.2%  RVOL 5.1  $82M"
    ]
    facts = row | {"ctx_done": True, "earnings_flag": False, "ctx_news_title": "Deal signed"}
    facts |= {"rs_pct": 88.0, "industry": "Semis", "ctx_news_publisher": "PR"}
    lines = [x.text for x in notify._block(facts, "ep_day", "eod")]
    assert lines[1] == f"   RS 88 {DOT} Semis"
    assert lines[2] == "   📰 Deal signed (PR)"
    assert all(len(x) <= notify.WIDTH for x in lines)


def test_wrap_packs_phrases_into_phone_lines():
    assert notify.wrap(["aaaa", "bbbb", "cccc"], 11) == [f"aaaa {DOT} bbbb", "cccc"]
    assert notify.wrap(["x" * 20], 10) == ["x" * 20]


def test_fit_drops_headlines_then_facts_from_the_bottom_then_cuts():
    fact, news = "   FACT " + "f" * 25, "   📰 " + "n" * 30

    def block(t):
        return [
            notify.Line("hit", f"▸ {t}  +14.2%"),
            notify.Line("plan", "   Buy 10.00 · stop 9.50"),
            notify.Line("fact", fact),
            notify.Line("news", news),
        ]

    def size(text):
        return len(text.encode("utf-8"))

    lines = [*block("AAA"), notify.Line("gap", ""), *block("BBB")]
    full = notify.fit(lines, limit=10_000)
    news_b, fact_b = size("\n" + news), size("\n" + fact)
    assert notify.fit(lines, limit=size(full)) == full
    one_news = notify.fit(lines, limit=size(full) - 1)
    assert one_news.count("📰") == 1 and "📰" in one_news.split("\n\n")[0]  # top keeps its
    no_news = notify.fit(lines, limit=size(full) - 2 * news_b)
    assert "📰" not in no_news and no_news.count("FACT") == 2
    top_facts = notify.fit(lines, limit=size(full) - 2 * news_b - fact_b)
    assert top_facts.count("FACT") == 1 and "FACT" in top_facts.split("\n\n")[0]
    assert "▸ BBB" in top_facts
    cut = notify.fit(lines, limit=60)
    assert size(cut) <= 60 and cut.endswith("more in the report")


def test_format_pace_and_pivot():
    row = {"ticker": "ABCD", "chg_pct": 6.2, "volume": 4.1e6, "proj_volume": 11.4e6}
    row |= {"dollar_volume": 82e6, "earnings_flag": True}
    assert notify.format_pace(row) == "ABCD  +6.2%  4.1M → pace 11M  📢"
    pivot = {"ticker": "ABCD", "chg_pct": 3.1, "pivot_crossed": True, "pivot_dist_pct": 0.9}
    assert notify.format_pivot(pivot | {"rvol_at_time_tv": 2.34}) == (
        "ABCD  +3.1%  over pivot +0.9%  RVOL 2.3"
    )


def test_weekly_growth_caps_tiny_bases():
    row = {"ticker": "ABCD", "eps_growth_q": 432900.0, "eps_growth_q_prev": 115.0}
    row |= {"rev_growth_q": 36.0, "rev_growth_q_prev": float("nan")}
    assert notify.format_weekly(row, "growth_bucket_2") == "ABCD  EPS >+999% / +115%  rev +36%"


def triggers():
    rows = []
    for i, flags in enumerate([(1, 1, 1, 1), (1, 0, 1, 0), (0, 0, 1, 0), (1, 1, 0, 1)]):
        row = {"ticker": f"BO{i}", "rank": i + 1, "tier": "alert", "chg_pct": 3.0 + i}
        row |= {"trig_rvol": 2.0, "pivot": 10.0, "order_stop": 9.5, "b5": True}
        row |= {f"b{k + 1}": bool(v) for k, v in enumerate(flags)}
        rows.append(row)
    return pd.DataFrame(rows)


def test_full_setups_get_blocks_and_b5_only_get_one_line_each():
    cfg = load_config()
    results = {"breakout_trigger": triggers()}
    chosen = notify.select_for_push(results, cfg)["breakout_trigger"]
    assert chosen["ticker"].tolist() == ["BO0", "BO1", "BO2", "BO3"]
    assert chosen["push_partial"].tolist() == [False, True, True, True]
    msg = notify.build_message(CTX, results, notify.select_for_push(results, cfg), cfg)
    assert msg.title == f"EOD Mon 19 Oct 16:18 NY {DOT} 22:18 CPH {DOT} BO 1 {DOT} B5-only 3"
    body = msg.body.splitlines()
    assert body[0] == f"━━ 🚀 Breakout {DOT} 1 of 4 ━━"
    assert body[1] == f"B: move {DOT} base {DOT} trend {DOT} tight {DOT} trigger"
    assert body[2] == "▸ BO0  +3.0%  RVOL 2.0  B🟩🟩🟩🟩🟩"
    assert body[3] == f"   Pivot 10.00 {DOT} 🛑 9.50"
    assert body[4:] == [
        "",
        f"B5 only {DOT} top 3 of 3:",
        "▸ BO1  +4.0%  RVOL 2.0  B🟩🟥🟩🟥🟩",
        "▸ BO2  +5.0%  RVOL 2.0  B🟥🟥🟩🟥🟩",
        "▸ BO3  +6.0%  RVOL 2.0  B🟩🟩🟥🟩🟩",
    ]


def test_b5_only_shown_under_a_section_without_full_setups():
    cfg = load_config()
    results = {"breakout_trigger": triggers().iloc[1:]}
    msg = notify.build_message(CTX, results, notify.select_for_push(results, cfg), cfg)
    assert msg.body.splitlines()[:3] == [
        f"━━ 🚀 Breakout {DOT} no full setup ━━",
        f"B: move {DOT} base {DOT} trend {DOT} tight {DOT} trigger",
        f"B5 only {DOT} top 3 of 3:",
    ]
