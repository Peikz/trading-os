import datetime as dt

import numpy as np
import pandas as pd

from trading_os import audit
from trading_os.config import load_config

from .test_breakouts import textbook


def textbook_bars():
    h, lo, c, v = textbook()
    v = v * 10  # liquid enough for the alert-tier dollar-volume floor
    days = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(len(c))]
    frames = []
    for ticker, scale in (("BRKO", 1.0), ("FLAT", 0.0)):
        closes = c if scale else np.full_like(c, 20.0)
        frames.append(
            pd.DataFrame(
                {
                    "session_date": days,
                    "ticker": ticker,
                    "open": closes,
                    "high": h if scale else closes * 1.01,
                    "low": lo if scale else closes * 0.99,
                    "close": closes,
                    "volume": v,
                    "source": "massive",
                }
            )
        )
    frames.append(frames[0].assign(ticker="BRKOW"))  # warrant-shaped ticker: skipped
    return pd.concat(frames, ignore_index=True), days


def test_replay_finds_the_textbook_breakout(tmp_path):
    bars, days = textbook_bars()
    hits = audit.replay(bars, days, replay_days=3, cfg=load_config())
    triggers = hits[hits["kind"] == "trigger"]
    assert triggers["ticker"].tolist() == ["BRKO"]  # FLAT has no base, BRKOW is skipped
    assert triggers["session_date"].tolist() == [days[-1]]
    sheet = audit.write_sheet(hits, bars, tmp_path, n=20, seed=1, today=days[-1])
    text = sheet.read_text(encoding="utf-8")
    assert "BRKO · trigger" in text and "B5=yes" in text and "- [ ] B1 prior move" in text
    assert list((tmp_path / "docs").glob("breakout_audit_*/*.png"))


def test_main_without_history(tmp_path, capsys):
    assert audit.main(["--data-dir", str(tmp_path)]) == 1
    assert "not enough history" in capsys.readouterr().out


def test_pick_draws_half_from_each_kind():
    hits = pd.DataFrame(
        {"kind": ["watch"] * 3 + ["trigger"] * 50, "ticker": [f"T{i}" for i in range(53)]}
    )
    picked = audit.pick(hits, 20, seed=1)
    assert picked["kind"].value_counts().to_dict() == {"trigger": 17, "watch": 3}
    even = audit.pick(pd.concat([hits, hits.assign(kind="watch")]), 20, seed=1)
    assert even["kind"].value_counts().to_dict() == {"trigger": 10, "watch": 10}
    repeats = pd.DataFrame({"kind": ["watch"] * 4 + ["trigger"] * 4, "ticker": list("AABBCDEF")})
    assert len(audit.pick(repeats, 20, seed=1)) == 6  # A and B once each
    assert audit.pick(hits.iloc[0:0], 20, seed=1).empty
