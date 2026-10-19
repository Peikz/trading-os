import datetime as dt

import pandas as pd

from trading_os import epstudy

COLUMNS = ["session_date", "scan", "ticker", "pivot", "b1", "signal_id"]


def candidates():
    return pd.DataFrame(
        {
            "session_date": [pd.Timestamp("2026-10-19")] * 3,
            "scan": ["breakout_trigger", "breakout_watch", "ep_day"],
            "ticker": ["BO", "BW", "EP"],
            "pivot": [15.123456, 20.0, float("nan")],
            "b1": [True, False, pd.NA],
            "signal_id": ["s1", "s2", "s3"],
        }
    )


def test_rows_use_configured_scans_and_columns():
    rows = epstudy.rows_for(candidates(), ["breakout_trigger", "breakout_watch"], COLUMNS)
    assert rows == [
        ["2026-10-19", "breakout_trigger", "BO", 15.1235, "TRUE", "s1"],
        ["2026-10-19", "breakout_watch", "BW", 20.0, "FALSE", "s2"],
    ]


def test_column_letters():
    assert [epstudy._column_letter(i) for i in (0, 5, 25, 26, 27)] == ["A", "F", "Z", "AA", "AB"]


class FakeHTTP:
    def __init__(self, existing):
        self.existing, self.posted, self.urls = existing, None, []

    def get(self, url):
        self.urls.append(url)
        return Response({"values": [[x] for x in self.existing]})

    def post(self, url, params, json):
        self.urls.append(url)
        self.posted = json["values"]
        return Response({})


class Response:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def test_append_skips_rows_already_in_the_sheet():
    rows = epstudy.rows_for(candidates(), ["breakout_trigger", "breakout_watch"], COLUMNS)
    http = FakeHTTP(existing=["signal_id", "s1"])  # header + one row already logged
    added = epstudy.append_new(http, "SHEET", "Breakout Log", COLUMNS, rows)
    assert added == 1 and http.posted == [rows[1]]
    assert http.urls[0].endswith("/SHEET/values/Breakout%20Log!F:F")
    assert epstudy.append_new(FakeHTTP(["s1", "s2"]), "SHEET", "Breakout Log", COLUMNS, rows) == 0


def test_to_cell_types():
    assert epstudy.to_cell(dt.date(2026, 10, 19)) == "2026-10-19"
    assert epstudy.to_cell(float("nan")) == "" and epstudy.to_cell(None) == ""
