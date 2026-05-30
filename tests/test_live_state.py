"""Tests for the dependency-free live_state helpers.

live_state.py must import nothing from Home Assistant so it can be tested
without HA installed. We import it by file path to avoid triggering the
custom_components.orion_sleep package __init__ (which imports HA).
"""

import importlib.util
import pathlib

_MODULE_PATH = (
    pathlib.Path(__file__).parent.parent
    / "custom_components"
    / "orion_sleep"
    / "live_state.py"
)
_spec = importlib.util.spec_from_file_location("orion_live_state", _MODULE_PATH)
live_state = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live_state)


SAMPLE = {
    "zones": [
        {"id": "zone_a", "temp": 21.0, "on": True},
        {"id": "zone_b", "temp": 18.5, "on": False},
    ],
    "status": {
        "zones": [
            {"id": "zone_a", "temp": 20.4, "thermal_state": "standby"},
            {"id": "zone_b", "temp": 19.1, "thermal_state": "standby"},
        ]
    },
}


def test_setpoint_returns_zone_temp():
    assert live_state.zone_setpoint(SAMPLE, "zone_a") == 21.0
    assert live_state.zone_setpoint(SAMPLE, "zone_b") == 18.5


def test_is_on_returns_zone_on():
    assert live_state.zone_is_on(SAMPLE, "zone_a") is True
    assert live_state.zone_is_on(SAMPLE, "zone_b") is False


def test_measured_temp_reads_status_zones():
    assert live_state.zone_measured_temp(SAMPLE, "zone_a") == 20.4
    assert live_state.zone_measured_temp(SAMPLE, "zone_b") == 19.1


def test_none_live_returns_none():
    assert live_state.zone_setpoint(None, "zone_a") is None
    assert live_state.zone_is_on(None, "zone_a") is None
    assert live_state.zone_measured_temp(None, "zone_a") is None


def test_unknown_zone_returns_none():
    assert live_state.zone_setpoint(SAMPLE, "zone_c") is None
    assert live_state.zone_is_on(SAMPLE, "zone_c") is None
    assert live_state.zone_measured_temp(SAMPLE, "zone_c") is None


def test_missing_field_returns_none():
    live = {"zones": [{"id": "zone_a"}], "status": {"zones": [{"id": "zone_a"}]}}
    assert live_state.zone_setpoint(live, "zone_a") is None
    assert live_state.zone_is_on(live, "zone_a") is None
    assert live_state.zone_measured_temp(live, "zone_a") is None


def test_empty_and_malformed_live():
    assert live_state.zone_setpoint({}, "zone_a") is None
    assert live_state.zone_measured_temp({"status": {}}, "zone_a") is None
    assert live_state.zone_setpoint({"zones": "nonsense"}, "zone_a") is None
