import datetime as dt

import pandas as pd

from trading_os import jobs_log


def test_normalize_drops_suffixes_and_punctuation():
    assert jobs_log.normalize("AMERICAN VANGUARD CORP") == "americanvanguard"
    assert jobs_log.normalize("Bristol-Myers Squibb Co.") == "bristolmyerssquibb"
    assert jobs_log.slug_key("greenhouse", "american-vanguard") == "americanvanguard"
    assert jobs_log.slug_key("workday", "acme|wd5|careers") == "acme"


def test_boards_match_exact_names_only_and_drop_ambiguous_keys():
    companies = pd.DataFrame(
        {
            "cik": [1, 2, 3, 4],
            "name": ["Acme Robotics Inc", "Beta Corp", "Gamma Holdings", "Gamma Group"],
            "ticker": ["ACME", "BETA", "GAM", "GAMG"],
        }
    )
    lists = {
        "greenhouse": ["acmerobotics", "betacorporation", "gamma"],
        "workday": ["beta|wd1|ext"],
    }
    out = jobs_log.build_boards(companies, lists)
    got = set(zip(out["ticker"], out["ats"], strict=True))
    assert got == {("ACME", "greenhouse"), ("BETA", "workday")}


class FakeHttp:
    def __init__(self):
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(url)
        return Resp(200, {"jobs": [1, 2, 3]})

    def post(self, url, **kw):
        self.calls.append(url)
        return Resp(200, {"total": 42})


class Resp:
    def __init__(self, code, body):
        self.ok, self._body = code == 200, body

    def json(self):
        return self._body


def test_snapshot_counts_each_board_once():
    boards = pd.DataFrame(
        {
            "ticker": ["A", "B"],
            "cik": [1, 2],
            "ats": ["greenhouse", "workday"],
            "entry": ["acme", "beta|wd1|ext"],
        }
    )
    http = FakeHttp()
    snap = jobs_log.snapshot(boards, dt.date(2026, 10, 26), http, pause_s=0)
    assert snap["open_jobs"].tolist() == [3, 42]
    assert http.calls[1].endswith("/wday/cxs/beta/ext/jobs")
    assert (
        jobs_log.snapshot_path("x", dt.date(2026, 10, 26))
        .as_posix()
        .endswith("data/jobs/2026/2026-10-26.parquet")
    )
