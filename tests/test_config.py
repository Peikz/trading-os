import copy
import datetime as dt

import pytest
import yaml

from trading_os.config import DEFAULT_PATH, ConfigError, load_config, parse_config


@pytest.fixture()
def raw():
    with open(DEFAULT_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_default_config_loads():
    cfg = load_config()
    assert cfg.version == 1
    assert cfg.schedule.windows_et["eod"] == (dt.time(16, 15), dt.time(23, 59))
    assert cfg.schedule.windows_et["pm"] == (dt.time(7, 15), dt.time(7, 55))


def test_ep_day_thresholds_match_spec():
    ep = load_config().scans["ep_day"]
    assert ep.enabled and ep.slot == "eod" and ep.action == "push"
    assert ep["gap_min_pct"] == 10
    assert ep["rvol_min"] == 3
    assert ep["volume_min"] == 300_000
    assert ep["price_min"] == 1.0
    assert ep["market_cap_min"] == 50_000_000
    assert ep["push_tier"] == "alert"


def test_underscored_numbers_parse_as_ints():
    cfg = load_config()
    assert cfg.universe["alert"]["signal_dollar_volume_min"] == 5_000_000
    assert isinstance(cfg.universe["logged"]["market_cap_min"], int)


def test_ep_ah_is_off_by_default():
    assert load_config().scans["ep_ah"].enabled is False


def test_unknown_scan_key_raises(raw):
    bad = copy.deepcopy(raw)
    bad["scans"]["ep_day"]["gap_min"] = 10
    with pytest.raises(ConfigError, match="unknown keys"):
        parse_config(bad)


def test_missing_scan_key_raises(raw):
    bad = copy.deepcopy(raw)
    del bad["scans"]["ep_day"]["rvol_min"]
    with pytest.raises(ConfigError, match="missing keys"):
        parse_config(bad)


def test_scan_not_in_spec_raises(raw):
    bad = copy.deepcopy(raw)
    bad["scans"]["my_new_setup"] = {"enabled": True, "phase": 1, "slot": "eod", "action": "push"}
    with pytest.raises(ConfigError, match="not in SPEC.md"):
        parse_config(bad)


def test_threshold_must_be_a_number(raw):
    bad = copy.deepcopy(raw)
    bad["scans"]["ep_day"]["gap_min_pct"] = "10%"
    with pytest.raises(ConfigError, match="expected a number"):
        parse_config(bad)


def test_config_is_read_only():
    cfg = load_config()
    with pytest.raises(TypeError):
        cfg.scans["ep_day"].params["gap_min_pct"] = 5


def test_pm_gap_basis_must_be_known(raw):
    bad = copy.deepcopy(raw)
    bad["scans"]["ep9m_early"]["pm_gap_basis"] = "premarket_open"
    with pytest.raises(ConfigError, match="pm_gap_basis"):
        parse_config(bad)
