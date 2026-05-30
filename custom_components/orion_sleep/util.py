"""Small dependency-free helpers.

This module imports nothing from Home Assistant so it can be unit-tested
standalone.
"""

from __future__ import annotations


def dedupe_devices_by_id(devices: object) -> list[dict]:
    """Return the device list with duplicate ``id`` entries removed.

    The Orion ``GET /v1/devices`` response has occasionally been observed
    to list the same device twice in a single response, which makes every
    per-device platform create each entity twice and triggers Home
    Assistant's "does not generate unique IDs" errors. De-duping by ``id``
    (keeping the first occurrence, preserving order) makes entity setup
    robust against that.

    Non-dict entries are skipped. Devices without an ``id`` are always
    kept (there is no key to de-dupe them on).
    """
    if not isinstance(devices, list):
        return []
    seen: set = set()
    result: list[dict] = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        dev_id = device.get("id")
        if dev_id is not None:
            if dev_id in seen:
                continue
            seen.add(dev_id)
        result.append(device)
    return result


def latest_session_for_zone(insights_data: object, zone_id: str) -> dict | None:
    """Most recent insights session whose ``zone_id`` matches, or None.

    ``insights_data`` is the coordinator's ``data["insights"]["data"]`` mapping
    of ``{date_str: {"sessions": [...]}}``. Dates are iterated newest-first;
    within a date the last matching session wins. Defensive against missing /
    malformed structures so a partial API response can't raise.
    """
    if not isinstance(insights_data, dict):
        return None
    for date_key in sorted(insights_data.keys(), reverse=True):
        day = insights_data.get(date_key)
        if not isinstance(day, dict):
            continue
        sessions = day.get("sessions")
        if not isinstance(sessions, list):
            continue
        match = None
        for session in sessions:
            if isinstance(session, dict) and session.get("zone_id") == zone_id:
                match = session
        if match is not None:
            return match
    return None
