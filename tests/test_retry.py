import pytest
import requests

from trading_os.retry import once_more


def flaky(failures):
    calls = []

    def call():
        calls.append(1)
        if len(calls) <= failures:
            raise requests.ConnectionError("blip")
        return "ok"

    return call, calls


def test_one_failure_is_retried(capsys):
    call, calls = flaky(1)
    waits = []
    assert once_more(call, label="TradingView", wait_s=30, sleep=waits.append) == "ok"
    assert len(calls) == 2 and waits == [30]
    assert "TradingView: ConnectionError, retrying once in 30s" in capsys.readouterr().out


def test_second_failure_raises():
    call, calls = flaky(2)
    with pytest.raises(requests.ConnectionError):
        once_more(call, label="ntfy", wait_s=1, sleep=lambda s: None)
    assert len(calls) == 2  # never loops


def test_other_errors_are_not_retried():
    calls = []

    def call():
        calls.append(1)
        raise ValueError("bug")

    with pytest.raises(ValueError):
        once_more(call, label="x", wait_s=1, sleep=lambda s: None)
    assert len(calls) == 1
