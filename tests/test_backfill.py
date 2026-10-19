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
    assert result.fetched == 3 and result.still_missing == result.window - 3
    assert 490 <= result.window <= 504  # capped at max_history_days
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


def test_check_without_key_fails_cleanly(capsys, monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    assert backfill.main(["--check"]) == 1
    assert "MASSIVE_API_KEY not set" in capsys.readouterr().out


def test_check_reports_counts_only(capsys, monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "k")
    monkeypatch.setattr(
        backfill.MassiveClient,
        "grouped_daily",
        lambda self, day, adjusted=True: FakeClient().grouped_daily(day),
    )
    monkeypatch.setattr(backfill.RateLimiter, "wait", lambda self: None)
    monkeypatch.setattr(backfill.MassiveClient, "news", lambda self, t, limit=3: [{"title": "x"}])
    assert backfill.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert out.count("OK, 1 tickers") == 2 and "AAA" not in out
    assert "news OK, 1 headlines" in out


def test_window_never_goes_past_the_plan():
    cfg = load_config()
    sessions = backfill.window(cfg, FRI)
    assert sessions[-1] == FRI
    assert (FRI - sessions[0]).days <= cfg.history["max_history_days"]


def test_403_on_an_old_session_is_skipped(tmp_path):
    cfg = load_config()

    class PlanLimited(FakeClient):
        def grouped_daily(self, day, adjusted=True):
            if day < dt.date(2026, 10, 14):
                response = backfill.requests.Response()
                response.status_code = 403
                raise backfill.requests.HTTPError("403", response=response)
            return super().grouped_daily(day, adjusted)

    result = backfill.run_backfill(tmp_path, cfg, PlanLimited(), FRI, max_calls=5)
    assert (result.fetched, result.unavailable) == (3, 2)
