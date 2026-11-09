"""Load and check `config/backtest.yaml` (docs/backlog/backtest.md §11: every threshold lives in
the config, not in code). Each section's key set is checked exactly, so a typo fails loudly."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "backtest.yaml"

_KEYS = {
    "": {"version", "data", "universe", "indicators", "setups"},
    "data": {"source", "years", "warmup_sessions", "index_tickers"},
    "universe": {
        "price_min",
        "avg_volume_days",
        "avg_volume_min",
        "market_cap_min",
        "exclude_types",
        "spac_name_patterns",
    },
    "indicators": {
        "adr_days",
        "ema_spans",
        "sma_windows",
        "vol_avg_days",
        "perf_windows",
        "rising_lookback",
        "leader",
        "avwap_lookback",
        "regime",
        "breadth",
    },
    "indicators.leader": {"top_pct", "above_sma"},
    "indicators.regime": {"ticker", "fast_sma", "mid_sma", "slow_sma", "slope_lookback"},
    "indicators.breadth": {"perf_window", "move_pct", "strong_ratio_min", "weak_ratio_below"},
    "setups": {"b0", "l1", "l2", "l3", "s1", "s2"},
    "setups.b0": {
        "prior_move_min_pct",
        "prior_move_days",
        "base_min_days",
        "base_max_days",
        "base_depth_max_pct",
        "tight_days",
        "tight_range_max_adr",
        "trigger_above_pivot",
        "limit_above_trigger",
        "stop_low_days",
    },
    "setups.l1": {
        "prior_move_min_pct",
        "prior_move_days",
        "high_age_min",
        "high_age_max",
        "touch_adr",
        "stop_max_adr",
    },
    "setups.l2": {"undercut_days", "stop_max_adr"},
    "setups.l3": {
        "gap_min_pct",
        "volume_min_x",
        "volume_min",
        "neglect_perf_max_pct",
        "stop_max_adr",
    },
    "setups.s1": {
        "former_leader_days",
        "breakdown_days",
        "breakdown_volume_x",
        "bounce_min_days",
        "bounce_max_days",
        "touch_adr",
        "stop_max_adr",
    },
    "setups.s2": {
        "extension_adr",
        "up_closes_min",
        "up_closes_days",
        "perf21_min_pct",
        "stop_max_adr",
    },
}


@dataclass(frozen=True)
class DataConfig:
    source: str
    years: tuple[int, ...]
    warmup_sessions: int
    index_tickers: tuple[str, ...]


@dataclass(frozen=True)
class UniverseConfig:
    price_min: float
    avg_volume_days: int
    avg_volume_min: float
    market_cap_min: float | None
    exclude_types: frozenset[str]
    spac_name_patterns: tuple[str, ...]


@dataclass(frozen=True)
class LeaderConfig:
    top_pct: float  # percent of the universe, per perf window
    above_sma: int


@dataclass(frozen=True)
class RegimeConfig:
    ticker: str
    fast_sma: int
    mid_sma: int
    slow_sma: int
    slope_lookback: int


@dataclass(frozen=True)
class BreadthConfig:
    perf_window: int
    move_pct: float
    strong_ratio_min: float
    weak_ratio_below: float


@dataclass(frozen=True)
class IndicatorConfig:
    adr_days: int
    ema_spans: tuple[int, ...]
    sma_windows: tuple[int, ...]
    vol_avg_days: int
    perf_windows: tuple[int, ...]
    rising_lookback: int
    leader: LeaderConfig
    avwap_lookback: int
    regime: RegimeConfig
    breadth: BreadthConfig


@dataclass(frozen=True)
class BacktestConfig:
    data: DataConfig
    universe: UniverseConfig
    indicators: IndicatorConfig
    setups: Mapping[str, Mapping[str, float]]  # setup id -> its thresholds (all numbers)


def _check_keys(section: str, got: Mapping[str, Any]) -> None:
    want = _KEYS[section]
    missing, unknown = want - set(got), set(got) - want
    where = section or "top level"
    if missing:
        raise ValueError(f"backtest config {where}: missing {sorted(missing)}")
    if unknown:
        raise ValueError(f"backtest config {where}: unknown {sorted(unknown)}")


def _ints(values: Any) -> tuple[int, ...]:
    return tuple(int(v) for v in values)


def parse_config(raw: Mapping[str, Any]) -> BacktestConfig:
    _check_keys("", raw)
    if raw["version"] != 1:
        raise ValueError(f"backtest config: version {raw['version']} is not supported")
    d, u, ind = raw["data"], raw["universe"], raw["indicators"]
    _check_keys("data", d)
    _check_keys("universe", u)
    _check_keys("indicators", ind)
    for sub in ("leader", "regime", "breadth"):
        _check_keys(f"indicators.{sub}", ind[sub])
    st = raw["setups"]
    _check_keys("setups", st)
    for name in st:
        _check_keys(f"setups.{name}", st[name])
    years = _ints(d["years"])
    if not years or list(years) != sorted(set(years)):
        raise ValueError("backtest config data.years: must be ascending and unique")
    lead, reg, br = ind["leader"], ind["regime"], ind["breadth"]
    return BacktestConfig(
        data=DataConfig(
            source=str(d["source"]),
            years=years,
            warmup_sessions=int(d["warmup_sessions"]),
            index_tickers=tuple(str(t) for t in d["index_tickers"]),
        ),
        universe=UniverseConfig(
            price_min=float(u["price_min"]),
            avg_volume_days=int(u["avg_volume_days"]),
            avg_volume_min=float(u["avg_volume_min"]),
            market_cap_min=None if u["market_cap_min"] is None else float(u["market_cap_min"]),
            exclude_types=frozenset(str(t) for t in u["exclude_types"]),
            spac_name_patterns=tuple(str(p).lower() for p in u["spac_name_patterns"]),
        ),
        indicators=IndicatorConfig(
            adr_days=int(ind["adr_days"]),
            ema_spans=_ints(ind["ema_spans"]),
            sma_windows=_ints(ind["sma_windows"]),
            vol_avg_days=int(ind["vol_avg_days"]),
            perf_windows=_ints(ind["perf_windows"]),
            rising_lookback=int(ind["rising_lookback"]),
            leader=LeaderConfig(top_pct=float(lead["top_pct"]), above_sma=int(lead["above_sma"])),
            avwap_lookback=int(ind["avwap_lookback"]),
            regime=RegimeConfig(
                ticker=str(reg["ticker"]),
                fast_sma=int(reg["fast_sma"]),
                mid_sma=int(reg["mid_sma"]),
                slow_sma=int(reg["slow_sma"]),
                slope_lookback=int(reg["slope_lookback"]),
            ),
            breadth=BreadthConfig(
                perf_window=int(br["perf_window"]),
                move_pct=float(br["move_pct"]),
                strong_ratio_min=float(br["strong_ratio_min"]),
                weak_ratio_below=float(br["weak_ratio_below"]),
            ),
        ),
        setups=MappingProxyType(
            {n: MappingProxyType({k: float(v) for k, v in st[n].items()}) for n in sorted(st)}
        ),
    )


def load_config(path: Path = DEFAULT_PATH) -> BacktestConfig:
    return parse_config(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
