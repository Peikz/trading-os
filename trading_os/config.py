"""Load and validate config/scans.yaml.

Every threshold lives in that file (SPEC §1.5). The loader checks the exact key set of every
section, so a typo fails loudly instead of silently dropping a filter.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "scans.yaml"

SLOTS = frozenset({"pm", "eod", "weekly"})
ACTIONS = frozenset({"push", "log", "watchlist"})
TIERS = frozenset({"alert", "log"})
# Pre-market "gap": TradingView field -> canonical column (docs/fields.md).
PM_GAP_COLUMNS = {"premarket_change": "pm_change_pct", "premarket_gap": "pm_gap_pct"}

TOP_LEVEL_KEYS = {
    "version",
    "universe",
    "proxies",
    "schedule",
    "scans",
    "market_light",
    "breakout",
    "history",
    "outcomes",
    "charts",
    "notify",
}
BREAKOUT_KEYS = {
    "prior_move_min_pct",
    "prior_move_max_days",
    "base_min_days",
    "base_max_days",
    "contraction_ratio_max",
    "min_contractions",
    "swing_adr_mult",
    "base_volume_ratio_max",
    "right_side_days",
    "right_side_range_adr_max",
    "trigger_range_adr_min",
    "trigger_rvol_min",
    "stop_adr_mult",
}
HISTORY_KEYS = {
    "massive_base_url",
    "calls_per_minute",
    "adjusted",
    "backfill_sessions",
    "daily_catchup_calls",
}
OUTCOME_KEYS = {"horizons"}
CHART_KEYS = {"sessions"}
UNIVERSE_KEYS = {
    "market",
    "include_types",
    "exclude_exchanges",
    "exclude_typespecs",
    "logged",
    "alert",
}
LOGGED_TIER_KEYS = {"price_min", "market_cap_min", "avg_dollar_volume_20d_min"}
ALERT_TIER_KEYS = {
    "price_min",
    "market_cap_min",
    "avg_volume_20d_min",
    "signal_dollar_volume_min",
}
PROXY_KEYS = {
    "rvol_avg_volume",
    "rvol_avg_days",
    "avg_volume_20d",
    "avg_dollar_volume_20d",
    "returns",
    "adr",
}
SCHEDULE_KEYS = {"timezone", "calendar", "windows_et", "weekly_day"}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MARKET_LIGHT_KEYS = {
    "qqq": {"symbol", "sma_windows", "slope_lookback"},
    "breadth": {"strong_ratio10_min", "weak_ratio10_below", "thrust_ratio5_gt", "quarter_move_pct"},
    "scan_count": {
        "country",
        "price_gt",
        "avg_volume_gt",
        "avg_volume_field",
        "perf_3m_min_pct",
        "above_sma",
    },
    "thresholds": {"stop_count_below", "red_count_below", "green_count_min"},
}
NOTIFY_KEYS = {"server", "max_tickers_per_scan"}

SCAN_COMMON_KEYS = {"enabled", "phase", "slot", "action"}
# Scan-specific keys. Adding a scan here requires it to be in SPEC.md first (CLAUDE.md).
SCAN_PARAM_KEYS: dict[str, set[str]] = {
    "ep_pm": {"push_tier", "pm_change_min_pct", "price_min", "pm_volume_min", "market_cap_min"},
    "ep9m_early": {"push_tier", "pm_volume_min", "pm_gap_min_pct", "pm_gap_basis"},
    "watchlist_gappers": {"lists", "pm_gap_min_pct", "pm_gap_basis"},
    "ep_day": {
        "push_tier",
        "gap_min_pct",
        "rvol_min",
        "volume_min",
        "price_min",
        "market_cap_min",
    },
    "ep_ah": {"push_tier", "ah_change_min_pct", "price_min", "market_cap_min", "ah_volume_min"},
    "ep9m": {"push_tier", "volume_min", "chg_min_pct"},
    "mb_up": {"chg_min_pct", "volume_min", "volume_gt_prior", "close_loc_min"},
    "mb_down": {"chg_max_pct", "volume_min", "volume_gt_prior"},
    "parabolic_short": {
        "lookback_days_max",
        "large_cap_min",
        "gain_min_pct_large_cap",
        "gain_min_pct_small_cap",
        "consec_up_min",
    },
    "parabolic_long": {"lookback_days_max", "drop_min_pct", "consec_down_min"},
    "breadth": {
        "universe_price_min",
        "universe_volume_min",
        "ratio_windows",
        "quarter_move_pct",
        "ma_windows",
        "up_count_rule",
    },
    "breakout_watch": {"push_tier"},
    "breakout_trigger": {"push_tier"},
    "universe_snapshot": set(),
    "qm_gainers": {
        "top_pct",
        "return_windows",
        "adr_min_pct",
        "avg_dollar_volume_20d_min",
        "price_gt",
    },
    "growth_bucket_1": {
        "price_gt",
        "avg_volume_gt",
        "rev_growth_q_min_pct",
        "quarters_to_check",
        "annual_revenue_gt",
    },
    "growth_bucket_2": {
        "price_gt",
        "avg_volume_gt",
        "eps_growth_q_min_pct",
        "rev_growth_q_min_pct",
        "quarters_to_check",
    },
    "tight_bases": {
        "high_52w_within_pct",
        "adr_min_pct",
        "above_ma",
        "range_days",
        "range_adr_mult_below",
        "volume_short_days",
        "volume_long_days",
    },
}

# Keys with these suffixes are thresholds and must be plain numbers.
_NUMERIC_SUFFIXES = ("_min", "_max", "_gt", "_below", "_pct", "_lookback")


class ConfigError(ValueError):
    """Raised when scans.yaml does not match the expected schema."""


@dataclass(frozen=True)
class ScanConfig:
    name: str
    enabled: bool
    phase: int
    slot: str
    action: str
    params: Mapping[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.params[key]


@dataclass(frozen=True)
class Schedule:
    timezone: str
    calendar: str
    windows_et: Mapping[str, tuple[dt.time, dt.time]]
    weekly_weekday: int  # Monday = 0


@dataclass(frozen=True)
class Config:
    version: int
    universe: Mapping[str, Any]
    proxies: Mapping[str, str]
    schedule: Schedule
    scans: Mapping[str, ScanConfig]
    market_light: Mapping[str, Any]
    breakout: Mapping[str, Any]
    history: Mapping[str, Any]
    outcomes: Mapping[str, Any]
    charts: Mapping[str, Any]
    notify: Mapping[str, Any]


def load_config(path: Path | str = DEFAULT_PATH) -> Config:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return parse_config(raw)


def parse_config(raw: Any) -> Config:
    _check_keys("top level", raw, TOP_LEVEL_KEYS)

    universe = raw["universe"]
    _check_keys("universe", universe, UNIVERSE_KEYS)
    _check_keys("universe.logged", universe["logged"], LOGGED_TIER_KEYS)
    _check_keys("universe.alert", universe["alert"], ALERT_TIER_KEYS)
    _check_numbers("universe.logged", universe["logged"])
    _check_numbers("universe.alert", universe["alert"])

    _check_keys("proxies", raw["proxies"], PROXY_KEYS)
    windows = {str(w) for w in raw["scans"].get("qm_gainers", {}).get("return_windows", [])}
    if not windows <= set(raw["proxies"]["returns"]):
        raise ConfigError(
            f"proxies.returns: missing windows {sorted(windows - set(raw['proxies']['returns']))}"
        )

    market_light = raw["market_light"]
    _check_keys("market_light", market_light, set(MARKET_LIGHT_KEYS))
    for section, keys in MARKET_LIGHT_KEYS.items():
        _check_keys(f"market_light.{section}", market_light[section], keys)
        _check_numbers(f"market_light.{section}", market_light[section])

    _check_keys("breakout", raw["breakout"], BREAKOUT_KEYS)
    _check_numbers("breakout", raw["breakout"])
    _check_keys("history", raw["history"], HISTORY_KEYS)
    _check_keys("outcomes", raw["outcomes"], OUTCOME_KEYS)
    _check_keys("charts", raw["charts"], CHART_KEYS)
    _check_keys("notify", raw["notify"], NOTIFY_KEYS)

    return Config(
        version=raw["version"],
        universe=_freeze(universe),
        proxies=_freeze(raw["proxies"]),
        schedule=_parse_schedule(raw["schedule"]),
        scans=MappingProxyType(_parse_scans(raw["scans"])),
        market_light=_freeze(market_light),
        breakout=_freeze(raw["breakout"]),
        history=_freeze(raw["history"]),
        outcomes=_freeze(raw["outcomes"]),
        charts=_freeze(raw["charts"]),
        notify=_freeze(raw["notify"]),
    )


def _parse_schedule(raw: Any) -> Schedule:
    _check_keys("schedule", raw, SCHEDULE_KEYS)
    windows = {}
    for slot, pair in raw["windows_et"].items():
        if slot not in SLOTS:
            raise ConfigError(f"schedule.windows_et: unknown slot {slot!r}")
        if not isinstance(pair, list) or len(pair) != 2:
            raise ConfigError(f"schedule.windows_et.{slot}: expected [start, end]")
        start, end = (dt.time.fromisoformat(t) for t in pair)
        if start >= end:
            raise ConfigError(f"schedule.windows_et.{slot}: start must be before end")
        windows[slot] = (start, end)
    if raw["weekly_day"] not in WEEKDAYS:
        raise ConfigError(f"schedule.weekly_day: {raw['weekly_day']!r} not in {WEEKDAYS}")
    return Schedule(
        timezone=raw["timezone"],
        calendar=raw["calendar"],
        windows_et=MappingProxyType(windows),
        weekly_weekday=WEEKDAYS.index(raw["weekly_day"]),
    )


def _parse_scans(raw: Any) -> dict[str, ScanConfig]:
    if not isinstance(raw, dict):
        raise ConfigError("scans: expected a mapping")
    unknown = raw.keys() - SCAN_PARAM_KEYS.keys()
    if unknown:
        raise ConfigError(f"scans: not in SPEC.md: {sorted(unknown)}")
    scans = {}
    for name, body in raw.items():
        _check_keys(f"scans.{name}", body, SCAN_COMMON_KEYS | SCAN_PARAM_KEYS[name])
        if not isinstance(body["enabled"], bool):
            raise ConfigError(f"scans.{name}.enabled: expected true/false")
        if body["slot"] not in SLOTS:
            raise ConfigError(f"scans.{name}.slot: {body['slot']!r} not in {sorted(SLOTS)}")
        if body["action"] not in ACTIONS:
            raise ConfigError(f"scans.{name}.action: {body['action']!r} not in {sorted(ACTIONS)}")
        if "pm_gap_basis" in body and body["pm_gap_basis"] not in PM_GAP_COLUMNS:
            allowed = sorted(PM_GAP_COLUMNS)
            raise ConfigError(
                f"scans.{name}.pm_gap_basis: {body['pm_gap_basis']!r} not in {allowed}"
            )
        if body.get("up_count_rule", "stockbee_4pct") not in ("stockbee_4pct", "mb_up"):
            raise ConfigError(f"scans.{name}.up_count_rule: {body['up_count_rule']!r}")
        if "push_tier" in body and body["push_tier"] not in TIERS:
            raise ConfigError(f"scans.{name}.push_tier: {body['push_tier']!r} not in {TIERS}")
        params = {k: v for k, v in body.items() if k not in SCAN_COMMON_KEYS}
        _check_numbers(f"scans.{name}", params)
        scans[name] = ScanConfig(
            name=name,
            enabled=body["enabled"],
            phase=body["phase"],
            slot=body["slot"],
            action=body["action"],
            params=_freeze(params),
        )
    return scans


def _check_keys(where: str, mapping: Any, expected: set[str]) -> None:
    if not isinstance(mapping, dict):
        raise ConfigError(f"{where}: expected a mapping")
    missing = expected - mapping.keys()
    unknown = mapping.keys() - expected
    if missing or unknown:
        raise ConfigError(
            f"{where}: missing keys {sorted(missing)}, unknown keys {sorted(unknown)}"
        )


def _check_numbers(where: str, mapping: Mapping[str, Any]) -> None:
    for key, value in mapping.items():
        if key.endswith(_NUMERIC_SUFFIXES) and (
            isinstance(value, bool) or not isinstance(value, int | float)
        ):
            raise ConfigError(f"{where}.{key}: expected a number, got {value!r}")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value
