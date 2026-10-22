"""The dashboard's search: tickers everywhere, words in notes and the guide (synthetic data)."""

import pandas as pd

from trading_os import search

GUIDE = """# Push
The heat lines show
## Market Light
STOP means no new entries
"""


def test_tickers_and_words():
    assert search.looks_like_ticker("nvda") and search.looks_like_ticker("$BRK.B")
    assert not search.looks_like_ticker("gap and go")
    frames = {
        "ep_am": pd.DataFrame(
            {"ticker": ["AAA", "BBB"], "tier": ["alert", "log"], "grade": ["C", "C"],
             "grade_why": ["1 of 6", "0 of 6"]}
        )
    }  # fmt: skip
    found = search.scan_hits([("2026-10-22 · am", frames)], "AAA", {"ep_am": "EP 10:30"})
    assert found.to_dict("records")[0]["scan"] == "EP 10:30" and len(found) == 1
    notes = pd.DataFrame({"text": ["Held VWAP all day", "sold early"], "ticker": ["AAA", "BBB"]})
    assert search.text_hits(notes, ["text"], "vwap")["ticker"].tolist() == ["AAA"]
    assert search.guide_hits(GUIDE, "stop") == [("Market Light", "STOP means no new entries")]
