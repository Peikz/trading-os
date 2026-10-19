import datetime as dt

from trading_os import backfill, history
from trading_os.config import load_config
from trading_os.massive import to_bars

FRI = dt.date(2026, 10, 16)


class FakeClient:
    def __init__(self, empty_days=()):
        self.days, self.empty_days = [], set(empty_days)

    def grouped_daily(self, day, adjusted=True):
        self.days.append(day)
        bar = {"T": "AAA", "o": 1, "h": 2, "l": 1, "c": 2, "v": 10, "vw": 1.5, "n": 3}
        rows = [] if day in self.empty_days else [bar]
        return to_bars(rows, day, adjusted)


def test_backfill_newest_first_capped_and_resumable(tmp_path):
    cfg = load_config()
    first = FakeClient()
    result = backfill.run_backfill(tmp_path, cfg, first, FRI, max_calls=3)
    assert first.days == [dt.date(2026, 10, 16), dt.date(2026, 10, 15), dt.date(2026, 10, 14)]
    assert (result.fetched, result.still_missing, result.window) == (3, 501, 504)
    second = FakeClient()
    backfill.run_backfill(tmp_path, cfg, second, FRI, max_calls=2)
    assert second.days == [dt.date(2026, 10, 13), dt.date(2026, 10, 12)]  # resumes
    assert history.have_bars(tmp_path, "massive", dt.date(2026, 10, 12))


def test_unpublished_session_is_left_for_later(tmp_path):
    cfg = load_config()
    result = backfill.run_backfill(tmp_path, cfg, FakeClient(empty_days={FRI}), FRI, max_calls=2)
    assert (result.fetched, result.empty) == (1, 1)
    assert not history.have_bars(tmp_path, "massive", FRI)


def test_missing_key_is_a_clean_skip(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    assert backfill.main(["--data-dir", str(tmp_path), "--catchup"]) == 0
    assert "MASSIVE_API_KEY not set" in capsys.readouterr().out
