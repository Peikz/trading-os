import datetime as dt

import pandas as pd

from trading_os import report
from trading_os.store import RunContext

CTX = RunContext(
    dt.date(2026, 10, 19), "eod", pd.Timestamp("2026-10-19 20:18", tz="UTC"), "scheduled"
)


def ep_hits():
    return pd.DataFrame(
        {
            "rank": [1, 2],
            "ticker": ["AAA", "BBB"],
            "tier": ["alert", "log"],
            "gap_pct": [25.04, 11.0],
            "chg_pct": [20.0, 8.0],
            "rvol50": [6.0, 3.2],
            "dollar_volume": [42e6, 3e6],
            "market_cap": [1.2e9, 8e7],
            "earnings_flag": [True, False],
        }
    )


def test_report_has_market_tables_and_relative_chart_links(tmp_path):
    results = {"ep_day": ep_hits(), "mb_up": ep_hits().iloc[0:0]}
    selected = {"ep_day": ep_hits().iloc[[0]]}
    report_path = tmp_path / "reports" / "2026" / "2026-10-19_eod.md"
    chart = tmp_path / "data" / "charts" / "2026" / "2026-10-19_eod" / "ep_day_AAA.png"
    text = report.build(
        CTX,
        results,
        selected,
        ["Breadth: up 10 / down 5"],
        {("ep_day", "AAA"): chart},
        report_path,
        25,
    )
    assert text.startswith('<a name="top"></a>\n# Trading OS · EOD 2026-10-19')
    assert "Jump to: [Market](#market) · [EP-Day (2)](#scan-ep_day) · " in text
    assert '<a name="scan-ep_day"></a>\n### EP-Day' in text
    assert text.count("[↑ Top](#top)") == 2
    assert "- Breadth: up 10 / down 5" in text
    assert "### EP-Day — 2 hits (1 alert)" in text
    assert "| 1 | AAA | alert | +25.0 | +20.0 | 6.0 | $42M | $1.2B | yes |" in text
    assert "![AAA EP-Day](../../data/charts/2026/2026-10-19_eod/ep_day_AAA.png)" in text
    assert "## Saved only" in text and "_No hits._" in text


def test_long_lists_are_cut_and_report_is_written_once(tmp_path):
    many = pd.concat([ep_hits()] * 20, ignore_index=True)
    text = report.build(CTX, {"ep_day": many}, {}, [], {}, tmp_path / "r.md", 25)
    assert "_15 more in the candidates file._" in text
    path = tmp_path / "r.md"
    assert report.write(path, "first") == path
    assert report.write(path, "second") is None and path.read_text(encoding="utf-8") == "first"


def test_breakout_flags_column():
    hits = pd.DataFrame(
        {
            "rank": [1],
            "ticker": ["BO"],
            "tier": ["alert"],
            "pivot": [15.12],
            "order_stop": [14.88],
            "risk_adr": [1.0],
            "base_len": [27],
            "contraction_depths": ["14.7,7.6"],
            "b1": [True],
            "b2": [True],
            "b3": [False],
            "b4": [True],
            "b5": [pd.NA],
        }
    )
    lines = report.scan_table("breakout_watch", hits, 25)
    assert lines[-1] == "| 1 | BO | alert | 15.12 | 14.88 | 1.00 | 27 | 14.7,7.6 | 12-4- |  |  |"


def test_fact_lines_link_the_headline_and_skip_rows_without_facts():
    hits = pd.DataFrame(
        [
            {
                "ticker": "ABCD",
                "ctx_done": True,
                "earnings_flag": False,
                "ctx_news_title": "Wins [big] contract",
                "ctx_news_publisher": "PR",
                "ctx_news_time": "2026-10-16T16:05:00Z",
                "ctx_news_url": "https://example.com/a",
            },
            {"ticker": "EFGH", "ctx_done": None, "earnings_flag": False},
        ]
    )
    lines = report.fact_lines("ep_day", hits)
    assert lines == [
        "- **ABCD**",
        r"  - [Wins \[big\] contract](https://example.com/a) (PR, 10-16 12:05 ET)",
    ]
    assert report.fact_lines("mb_up", hits) == []


def test_scan_table_shows_the_heavily_shorted_tag():
    hits = ep_hits().assign(si_tag=["⚠️ heavily shorted · 6.2 days to cover (09-30)", None])
    lines = report.scan_table("ep_day", hits, 25)
    assert "| Short |" in lines[0]
    assert "heavily shorted" in lines[2] and "heavily shorted" not in lines[3]
    assert "Short" not in report.scan_table("ep_day", ep_hits(), 25)[0]
