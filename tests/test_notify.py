import datetime as dt

import pandas as pd

from trading_os import notify
from trading_os.config import load_config
from trading_os.store import RunContext

CTX = RunContext(
    session=dt.date(2026, 10, 19),
    slot="eod",
    run_ts=dt.datetime(2026, 10, 19, 20, 18, tzinfo=dt.UTC),
    run_kind="scheduled",
)


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


def test_format_hit_matches_spec():
    row = {
        "ticker": "ABCD",
        "gap_pct": 14.2,
        "rvol50": 5.1,
        "dollar_volume": 82e6,
        "earnings_flag": True,
    }
    assert notify.format_hit(row) == "ABCD  +14.2%  RVOL 5.1  $82M  [earnings]"
    row |= {"dollar_volume": 2.34e9, "earnings_flag": False}
    assert notify.format_hit(row) == "ABCD  +14.2%  RVOL 5.1  $2.3B"
    # EP9M shows the day's change instead of the gap.
    assert notify.format_hit(row | {"chg_pct": 6.0}, "chg_pct").startswith("ABCD  +6.0%")


def test_select_for_push_alert_tier_and_limit():
    cfg = load_config()
    results = {"ep_day": hits(n_alert=12, n_log=3)}
    chosen = notify.select_for_push(results, cfg)["ep_day"]
    assert len(chosen) == cfg.notify["max_tickers_per_scan"] == 10
    assert set(chosen["tier"]) == {"alert"}
    assert chosen["rank"].tolist() == list(range(1, 11))


def test_message_one_per_job():
    cfg = load_config()
    results = {"ep_day": hits(n_alert=2, n_log=1)}
    msg = notify.build_message(CTX, results, notify.select_for_push(results, cfg))
    assert msg.title == "Trading OS · EOD 2026-10-19"
    lines = msg.body.splitlines()
    assert lines[0] == "EP-Day: 2 alert of 3 hits"
    assert lines[1] == "T00  +30.0%  RVOL 5.1  $82M  [earnings]"
    assert len(lines) == 3


def test_message_without_hits():
    cfg = load_config()
    results = {"ep_day": hits(0)}
    msg = notify.build_message(CTX, results, notify.select_for_push(results, cfg))
    assert msg.body == "EP-Day: no alerts"
    results = {"ep_day": hits(0, n_log=2)}
    msg = notify.build_message(CTX, results, notify.select_for_push(results, cfg))
    assert msg.body == "EP-Day: no alerts (2 below alert tier)"


def test_send_posts_json(monkeypatch):
    calls = {}

    class Ok:
        def raise_for_status(self):
            calls["checked"] = True

    def fake_post(url, json, timeout):
        calls.update(url=url, json=json)
        return Ok()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    notify.send("https://ntfy.sh", "topic-x", notify.Message("t", "b"))
    assert calls["url"] == "https://ntfy.sh/"
    assert calls["json"]["topic"] == "topic-x"
    assert calls["json"]["title"] == "t" and calls["json"]["message"] == "b"
    assert calls["checked"]
