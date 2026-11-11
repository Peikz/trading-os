"""Shared test setup."""

import pytest

from trading_os import board_data


@pytest.fixture(autouse=True)
def _no_live_candle(monkeypatch):
    """Tests never ask TradingView for today's candle (board_data.with_today); the tests of
    that function pass their own session and fetch."""
    monkeypatch.setattr(board_data, "_session_today", lambda now=None: None)
    board_data._today_cache.clear()
