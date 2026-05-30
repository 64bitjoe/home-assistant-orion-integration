"""Pure helpers for reading per-zone state from a live-device dict.

This module imports nothing from Home Assistant so it can be unit-tested
standalone. A "live" dict is one entry of
``OrionDataUpdateCoordinator.live_devices`` — the merged
``GET /v1/devices/{serial}/live`` snapshot plus WebSocket
``live_device.{snapshot,update}`` frames.

Setpoints (user intent) live at ``live["zones"][]`` as ``{id, temp, on}``.
Measured temperatures live at ``live["status"]["zones"][]`` as
``{id, temp, thermal_state}``.
"""

from __future__ import annotations


def _find_zone(zones: object, zone_id: str) -> dict | None:
    """Return the zone dict with matching ``id`` from a list, or None."""
    if not isinstance(zones, list):
        return None
    for zone in zones:
        if isinstance(zone, dict) and zone.get("id") == zone_id:
            return zone
    return None


def zone_setpoint(live: dict | None, zone_id: str) -> float | None:
    """Return the zone's target temperature (setpoint) in Celsius, or None."""
    if not isinstance(live, dict):
        return None
    zone = _find_zone(live.get("zones"), zone_id)
    if zone is None:
        return None
    temp = zone.get("temp")
    return float(temp) if isinstance(temp, (int, float)) else None


def zone_is_on(live: dict | None, zone_id: str) -> bool | None:
    """Return the zone's power state, or None if unknown."""
    if not isinstance(live, dict):
        return None
    zone = _find_zone(live.get("zones"), zone_id)
    if zone is None or "on" not in zone:
        return None
    return bool(zone.get("on"))


def zone_measured_temp(live: dict | None, zone_id: str) -> float | None:
    """Return the zone's measured current temperature in Celsius, or None."""
    if not isinstance(live, dict):
        return None
    status = live.get("status")
    if not isinstance(status, dict):
        return None
    zone = _find_zone(status.get("zones"), zone_id)
    if zone is None:
        return None
    temp = zone.get("temp")
    return float(temp) if isinstance(temp, (int, float)) else None
