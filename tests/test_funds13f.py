"""Fund holdings on the card (13F): file order, CUSIP mapping, breadth, attach, card line.
Synthetic data only."""

import datetime as dt

import pandas as pd

from trading_os import board_data, funds13f

A = "".join(["Z", "Q", "X"])


def test_newest_files_by_their_end_date():
    links = [
        f"https://x/{n}_form13f.zip"
        for n in [
            "2013q2",
            "01jun2026-31aug2026",
            "2023q4",
            "01mar2026-31may2026",
            "01dec2025-28feb2026",
        ]
    ]
    assert [u.rsplit("/", 1)[-1][:9] for u in funds13f.newest(links)] == [
        "01dec2025",
        "01mar2026",
        "01jun2026",
    ]
    assert funds13f._file_end(links[2]) == dt.date(2023, 12, 31)


class _Http:
    def __init__(self):
        self.calls = 0

    def post(self, url, json, timeout):
        self.calls += 1
        answers = [
            {"data": [{"ticker": "X/B", "exchCode": "LN"}, {"ticker": "BRK/B", "exchCode": "US"}]},
            {"warning": "none"},
        ]
        return type(
            "R",
            (),
            {
                "status_code": 200,
                "raise_for_status": lambda self: None,
                "json": lambda self: answers[: len(json)],
            },
        )()


def test_figi_maps_new_cusips_only_and_prefers_the_us_listing():
    cache = pd.DataFrame({"cusip": ["OLD000001"], "ticker": [A]})
    http = _Http()
    out = funds13f.figi(["OLD000001", "NEW000001", "NEW000002"], cache, http, pause=0)
    assert http.calls == 1
    assert dict(zip(out.cusip, out.ticker, strict=True)) == {
        "OLD000001": A,
        "NEW000001": "BRK.B",
        "NEW000002": "",
    }


def test_breadth_needs_the_quarter_before_and_five_holders():
    h = pd.DataFrame({
        "cusip": ["C1", "C1", "C2", "C2"],
        "period": [dt.date(2026, 3, 31), dt.date(2026, 6, 30)] * 2,
        "available": [dt.date(2026, 5, 18), dt.date(2026, 8, 17)] * 2, "n_holders": [10, 13, 4, 6],
        "shares": [1e6, 2e6, 1e5, 1e5], "n_new": [0, 4, 0, 3], "n_exit": [0, 1, 0, 0],
    })  # fmt: skip
    cache = pd.DataFrame({"cusip": ["C1", "C2"], "ticker": [A, "ZZZ"]})
    t = funds13f.by_ticker(h, cache).set_index(["ticker", "period"])
    assert t.loc[(A, dt.date(2026, 6, 30)), "breadth"] == 0.3  # (4 - 1) / 10
    assert pd.isna(t.loc[("ZZZ", dt.date(2026, 6, 30)), "breadth"])  # 4 holders before: too few
    assert pd.isna(t.loc[(A, dt.date(2026, 3, 31)), "breadth"])


def test_attach_only_after_the_quarter_is_known_and_the_card_line(tmp_path):
    t = pd.DataFrame({
        "ticker": [A], "cusip": ["C1"], "period": [dt.date(2026, 6, 30)],
        "available": [dt.date(2026, 8, 17)], "n_holders": [120], "shares": [9e6], "breadth": [0.02],
    })  # fmt: skip
    (tmp_path / funds13f.TABLE).parent.mkdir(parents=True)
    t.to_parquet(tmp_path / funds13f.TABLE, index=False)
    df = pd.DataFrame({"ticker": [A, "OTHER"], "market_cap": [100e6, 5e6], "close": [10.0, 1.0]})
    early = funds13f.attach(df, tmp_path, dt.date(2026, 8, 17))
    assert early["fund_holders"].isna().all()
    out = funds13f.attach(df, tmp_path, dt.date(2026, 8, 18))
    row = out.iloc[0].to_dict()
    assert row["fund_holders"] == 120 and abs(row["fund_own"] - 0.9) < 1e-9
    assert pd.isna(out.iloc[1]["fund_own"])
    line = funds13f.card_tag(row)
    assert line.startswith("🏦 Funds own 90% (13F, Q2 2026)") and "worse in the study" in line
    assert line in board_data.tags(row)
    piling = {**row, "fund_own": 0.4, "fund_breadth": 0.15}
    assert funds13f.card_tag(piling) == "🏦 Funds piling in: +15% net new holders (13F, Q2 2026)"
    assert funds13f.card_tag({**row, "fund_own": 0.4}) is None
    assert funds13f.attach(df, tmp_path / "none", dt.date(2026, 9, 1)).equals(df)
