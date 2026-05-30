"""Tests for the dependency-free util helpers.

util.py must import nothing from Home Assistant so it can be tested
without HA installed. We import it by file path to avoid triggering the
custom_components.orion_sleep package __init__ (which imports HA).
"""

import importlib.util
import pathlib

_MODULE_PATH = (
    pathlib.Path(__file__).parent.parent
    / "custom_components"
    / "orion_sleep"
    / "util.py"
)
_spec = importlib.util.spec_from_file_location("orion_util", _MODULE_PATH)
util = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(util)


def test_dedupe_removes_duplicate_ids_keeping_first():
    devices = [
        {"id": "a", "name": "first"},
        {"id": "b", "name": "other"},
        {"id": "a", "name": "second"},
    ]
    result = util.dedupe_devices_by_id(devices)
    assert [d["name"] for d in result] == ["first", "other"]


def test_dedupe_preserves_order():
    devices = [{"id": "x"}, {"id": "y"}, {"id": "z"}]
    assert [d["id"] for d in util.dedupe_devices_by_id(devices)] == ["x", "y", "z"]


def test_dedupe_keeps_id_less_devices():
    devices = [{"name": "no-id-1"}, {"name": "no-id-2"}, {"id": "a"}]
    result = util.dedupe_devices_by_id(devices)
    assert len(result) == 3


def test_dedupe_skips_non_dict_entries():
    devices = [{"id": "a"}, "nonsense", None, {"id": "a"}, {"id": "b"}]
    result = util.dedupe_devices_by_id(devices)
    assert [d["id"] for d in result] == ["a", "b"]


def test_dedupe_none_and_empty():
    assert util.dedupe_devices_by_id(None) == []
    assert util.dedupe_devices_by_id([]) == []


INSIGHTS = {
    "2026-05-28": {
        "sessions": [
            {"session_id": "s1", "zone_id": "zone_a", "hrv": {"average": 40}},
            {"session_id": "s2", "zone_id": "zone_b", "hrv": {"average": 55}},
        ]
    },
    "2026-05-29": {
        "sessions": [
            {"session_id": "s3", "zone_id": "zone_a", "hrv": {"average": 42}},
        ]
    },
}


def test_latest_session_for_zone_newest_date():
    s = util.latest_session_for_zone(INSIGHTS, "zone_a")
    assert s["session_id"] == "s3"


def test_latest_session_for_zone_falls_back_to_older_date():
    s = util.latest_session_for_zone(INSIGHTS, "zone_b")
    assert s["session_id"] == "s2"


def test_latest_session_for_zone_no_match():
    assert util.latest_session_for_zone(INSIGHTS, "zone_c") is None


def test_latest_session_for_zone_empty_and_malformed():
    assert util.latest_session_for_zone(None, "zone_a") is None
    assert util.latest_session_for_zone({}, "zone_a") is None
    assert util.latest_session_for_zone({"d": {"sessions": "x"}}, "zone_a") is None
    assert util.latest_session_for_zone({"d": {}}, "zone_a") is None


def test_latest_session_for_zone_ignores_sessions_without_zone_id():
    data = {"2026-05-29": {"sessions": [{"session_id": "x"}]}}
    assert util.latest_session_for_zone(data, "zone_a") is None
