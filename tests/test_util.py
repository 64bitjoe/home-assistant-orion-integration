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
