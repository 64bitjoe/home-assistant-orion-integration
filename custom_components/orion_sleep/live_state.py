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
    return float(temp) if isinstance(temp, (int, float)) and not isinstance(temp, bool) else None


def zone_is_on(live: dict | None, zone_id: str) -> bool | None:
    """Return the zone's power state, or None if unknown."""
    if not isinstance(live, dict):
        return None
    zone = _find_zone(live.get("zones"), zone_id)
    if zone is None or "on" not in zone:
        return None
    on_val = zone.get("on")
    if not isinstance(on_val, bool):
        return None
    return on_val


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
    return float(temp) if isinstance(temp, (int, float)) and not isinstance(temp, bool) else None


def _status(live: dict | None) -> dict | None:
    if not isinstance(live, dict):
        return None
    status = live.get("status")
    return status if isinstance(status, dict) else None


def firmware(live: dict | None) -> dict | None:
    """Return ``status.firmware`` (e.g. {"cb": ..., "ib": ...}) or None."""
    status = _status(live)
    if status is None:
        return None
    fw = status.get("firmware")
    return fw if isinstance(fw, dict) else None


def network_info(live: dict | None) -> dict | None:
    """Return ``status.network`` (name/rssi/ip/mac/uptime/last_seen) or None."""
    status = _status(live)
    if status is None:
        return None
    net = status.get("network")
    return net if isinstance(net, dict) else None


def wifi_rssi(live: dict | None) -> int | None:
    """Return the Wi-Fi RSSI (dBm) or None."""
    net = network_info(live)
    if net is None:
        return None
    rssi = net.get("rssi")
    if isinstance(rssi, bool) or not isinstance(rssi, (int, float)):
        return None
    return int(rssi)


def safety_error(live: dict | None) -> bool | None:
    """Return True if the device reports a safety error, False if clear, None if absent."""
    status = _status(live)
    if status is None:
        return None
    safety = status.get("safety")
    if not isinstance(safety, dict):
        return None
    if safety.get("error"):
        return True
    codes = safety.get("error_codes")
    if isinstance(codes, list) and len(codes) > 0:
        return True
    return False


def led_brightness(live: dict | None) -> int | None:
    """Return the LED brightness (0-100) or None."""
    if not isinstance(live, dict):
        return None
    val = live.get("led_brightness")
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return None
    return int(val)


def zone_thermal_state(live: dict | None, zone_id: str) -> str | None:
    """Return ``status.zones[].thermal_state`` for one zone, or None."""
    status = _status(live)
    if status is None:
        return None
    zone = _find_zone(status.get("zones"), zone_id)
    if zone is None:
        return None
    state = zone.get("thermal_state")
    return state if isinstance(state, str) else None
