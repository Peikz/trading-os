"""Days to cover from FINRA (Emil, 25 Oct 2026): A+/A at 5+ days to cover become C and every
heavily shorted hit carries a warning. Synthetic data, no network."""

import datetime as dt

import pandas as pd

from trading_os import notify, short_interest

A, B = "".join(["S", "R", "F"]), "".join(["Q", "X", "Z"])


class FakeHttp:
    def __init__(self, dates, rows):
        self.dates, self.rows, self.posts = dates, rows, 0

    def get(self, url, **kw):
        body = {"availablePartitions": [{"partitions": [d]} for d in self.dates]}
        return type("R", (), {"json": lambda s: body})()

    def post(self, url, json=None, **kw):
        self.posts += 1
        page = self.rows[json["offset"] : json["offset"] + json["limit"]]
        reply = type(
            "R", (), {"text": "[]", "json": lambda s: page, "raise_for_status": lambda s: None}
        )
        r = reply()
        r.text = "[" if page else "[]"
        return r


def rows():
    return [
        {"symbolCode": A, "settlementDate": "2026-09-30", "daysToCoverQuantity": 6.2},
        {"symbolCode": B, "settlementDate": "2026-09-30", "daysToCoverQuantity": 1.4},
    ]


def test_latest_fetches_the_newest_report_once_and_caches_it(tmp_path):
    http = FakeHttp(["2026-09-15", "2026-09-30"], rows())
    t = short_interest.latest(tmp_path, dt.date(2026, 10, 25), http)
    assert set(t.ticker) == {A, B} and t.set_index("ticker").loc[A, "dtc"] == 6.2
    assert (tmp_path / "data" / "short_interest" / "2026-09-30.parquet").exists()
    short_interest.latest(tmp_path, dt.date(2026, 10, 25), http)
    assert http.posts == 1  # cached: no second fetch


def test_a_too_old_report_is_not_used(tmp_path):
    short_interest.latest(tmp_path, dt.date(2026, 10, 1), FakeHttp(["2026-09-30"], rows()))
    assert short_interest.latest(tmp_path, dt.date(2026, 11, 15), FakeHttp([], [])).empty


def test_heavily_shorted_a_plus_becomes_c_with_a_warning():
    table = pd.DataFrame({"ticker": [A, B], "si_date": ["2026-09-30"] * 2, "dtc": [6.2, 1.4]})
    hits = pd.DataFrame({"ticker": [A, B], "grade": ["A+", "A+"], "grade_risk_mult": [2.0, 2.0],
                         "grade_why": ["5 of 6 quality points"] * 2,
                         "plan_shares": [100.0, 100.0]})  # fmt: skip
    out = short_interest.attach({"ep_am": hits, "ma_surf": hits.assign(grade="C")}, table, 5)
    ep = out["ep_am"].set_index("ticker")
    assert ep.loc[A, "grade"] == "C" and ep.loc[A, "grade_risk_mult"] == 0.0
    assert ep.loc[A, "grade_why"] == "heavily shorted (6.2 days to cover)"
    assert pd.isna(ep.loc[A, "plan_shares"])
    assert ep.loc[B, "grade"] == "A+" and ep.loc[B, "plan_shares"] == 100
    assert ep.loc[A, "si_tag"] == "⚠️ heavily shorted · 6.2 days to cover (09-30)"
    assert pd.isna(ep.loc[B, "si_tag"])
    surf = out["ma_surf"].set_index("ticker")
    assert surf.loc[A, "si_tag"].startswith("⚠️ heavily shorted")  # C hits get the warning too


def test_the_push_shows_the_warning_under_the_hit():
    row = {"ticker": A, "grade": "C", "grade_why": "heavily shorted (6.2 days to cover)",
           "si_tag": "⚠️ heavily shorted · 6.2 days to cover (09-30)", "gap_pct": 12.0,
           "rvol50": 2.0, "dollar_volume": 4e7}  # fmt: skip
    lines = [line.text for line in notify._block(row, "ep_day", "eod")]
    assert any("⚠️ heavily shorted · 6.2 days to cover" in t for t in lines)
