# Per-Side Metrics + Diagnostics + Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 1.2.0: per-zone (Zone A / Zone B) sleep-insight sensors, curated device diagnostics (firmware, Wi-Fi, Problem, HVAC action), and LED-brightness + Reboot controls.

**Architecture:** Pure dependency-free extractors (`util.py`, `live_state.py`) carry the bug-prone parsing and get unit tests; thin coordinator wrappers expose them; HA entities read from the coordinator and (for controls) write via `api_client`. Built as three independent milestones (A, B, C) under one release.

**Tech Stack:** Python 3, Home Assistant custom integration, aiohttp, pytest (only `pytest` is installed locally; `homeassistant`/`aiohttp` are not — so automated tests cover only the dependency-free modules, and HA-coupled code is verified by `py_compile` + manual testing).

---

## File Structure

- `custom_components/orion_sleep/util.py` — add `latest_session_for_zone` (pure).
- `custom_components/orion_sleep/live_state.py` — add diagnostic extractors (pure).
- `custom_components/orion_sleep/coordinator.py` — add `get_latest_session_for_zone` + diagnostic wrappers.
- `custom_components/orion_sleep/sensor.py` — per-zone insight sensors + split sleep_score out + diagnostic sensors.
- `custom_components/orion_sleep/binary_sensor.py` — per-zone session-active + Problem sensor.
- `custom_components/orion_sleep/climate.py` — add `hvac_action`.
- `custom_components/orion_sleep/number.py` — LED Brightness number.
- `custom_components/orion_sleep/button.py` — NEW: Reboot button.
- `custom_components/orion_sleep/__init__.py` — add `Platform.BUTTON`.
- `custom_components/orion_sleep/strings.json` + `translations/en.json` — name changes + new keys.
- `custom_components/orion_sleep/manifest.json` — version 1.2.0.
- `tests/test_util.py`, `tests/test_live_state.py` — new unit tests.
- `orion_info.py`, `openapi.yaml`, `AGENTS.md`, `README.md` — verification tooling + docs.

---

# MILESTONE A — Per-side sleep-insight metrics

## Task A0: Verify the zone_id mapping (GATE — do this first)

**Files:** none (manual verification).

- [ ] **Step 1: Inspect live insights**

Run: `python orion_info.py --insights-days 3`
Look at the printed insights sessions. Confirm each session object has a
`zone_id` whose value is one of the device zone ids (`zone_a` / `zone_b` — the
same ids shown under each device's `zones`).

- [ ] **Step 2: Decision gate**

- If `zone_id` values are `zone_a` / `zone_b` → proceed with the rest of Milestone A.
- If `zone_id` is a user-id, null, or anything else → **STOP and report to the
  human.** Do not build per-zone sensors on a wrong mapping. The mapping
  assumption underpins every task below.

## Task A1: `latest_session_for_zone` pure helper

**Files:**
- Modify: `custom_components/orion_sleep/util.py`
- Test: `tests/test_util.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_util.py`:

```python
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
    # zone_b only has a session on the older date
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_util.py -q`
Expected: FAIL (`AttributeError: module ... has no attribute 'latest_session_for_zone'`).

- [ ] **Step 3: Implement**

Append to `custom_components/orion_sleep/util.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_util.py -q`
Expected: PASS (all util tests green).

- [ ] **Step 5: Commit**

```bash
git add custom_components/orion_sleep/util.py tests/test_util.py
git commit -m "Add latest_session_for_zone helper with tests"
```

## Task A2: Coordinator per-zone session accessor

**Files:**
- Modify: `custom_components/orion_sleep/coordinator.py`

No automated test (requires HA to instantiate). Logic is covered by Task A1.

- [ ] **Step 1: Add the method**

In `coordinator.py`, find the existing `get_latest_session` method (ends with
`return None`). Immediately after it, add:

```python
    def get_latest_session_for_zone(self, zone_id: str) -> dict | None:
        """Most recent insights session for one zone, or None."""
        insights = (self.data or {}).get("insights", {})
        return util.latest_session_for_zone(insights.get("data"), zone_id)
```

(`util` is already imported in coordinator.py.)

- [ ] **Step 2: Verify compile**

Run: `python3 -m py_compile custom_components/orion_sleep/coordinator.py`
Expected: exit 0, no output.

- [ ] **Step 3: Commit**

```bash
git add custom_components/orion_sleep/coordinator.py
git commit -m "Add coordinator get_latest_session_for_zone"
```

## Task A3: Make insight sensors per-zone; split out Sleep Score

**Files:**
- Modify: `custom_components/orion_sleep/sensor.py`

No automated test (HA-coupled). Verify by py_compile + manual.

Background: `INSIGHT_SENSOR_DESCRIPTIONS` currently includes `sleep_score`, which
is special-cased in `OrionSensorEntity`. Sleep Score stays device-level; the
other 10 session metrics + current temp offset become per-zone.

- [ ] **Step 1: Remove sleep_score from the per-zone descriptions**

In `sensor.py`, delete the `sleep_score` `OrionSensorEntityDescription` block
(the first entry in `INSIGHT_SENSOR_DESCRIPTIONS`, lines beginning
`key="sleep_score",` through its closing `),`). The tuple should now start with
the `total_sleep_time` entry.

- [ ] **Step 2: Make `OrionSensorEntity` per-zone**

Replace the entire `OrionSensorEntity` class with:

```python
class OrionZoneInsightSensor(OrionBaseEntity, SensorEntity):
    """Per-zone sleep-insight sensor (reads that zone's latest session)."""

    entity_description: OrionSensorEntityDescription

    def __init__(
        self,
        coordinator: OrionDataUpdateCoordinator,
        device_id: str,
        zone_id: str,
        zone_label: str,
        description: OrionSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._zone_id = zone_id
        self._attr_unique_id = f"{device_id}_{description.key}_{zone_id}"
        self._attr_translation_placeholders = {"zone": zone_label}

    @property
    def native_value(self) -> Any:
        session = self.coordinator.get_latest_session_for_zone(self._zone_id)
        return self.entity_description.value_fn(session)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.extra_attrs_fn is None:
            return None
        session = self.coordinator.get_latest_session_for_zone(self._zone_id)
        attrs = self.entity_description.extra_attrs_fn(session)
        return {k: v for k, v in attrs.items() if v is not None} or None
```

- [ ] **Step 3: Add a device-level Sleep Score sensor**

In `sensor.py`, immediately after the `OrionZoneInsightSensor` class, add:

```python
class OrionSleepScoreSensor(OrionBaseEntity, SensorEntity):
    """Device-level sleep score from the insights overview (daily aggregate)."""

    _attr_translation_key = "sleep_score"
    _attr_native_unit_of_measurement = "points"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:medal-outline"

    def __init__(
        self,
        coordinator: OrionDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_sleep_score"

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        return _get_score(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        quality = _score_quality(_get_score(self.coordinator.data))
        return {"quality_rating": quality} if quality else None
```

- [ ] **Step 4: Make `OrionCurrentTempOffsetSensor` per-zone**

Replace the `OrionCurrentTempOffsetSensor.__init__` and `native_value` with:

```python
    def __init__(
        self,
        coordinator: OrionDataUpdateCoordinator,
        device_id: str,
        zone_id: str,
        zone_label: str,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._zone_id = zone_id
        self._attr_unique_id = f"{device_id}_current_temp_offset_{zone_id}"
        self._attr_translation_placeholders = {"zone": zone_label}

    @property
    def native_value(self) -> float | None:
        """Return the current measured temperature offset for this zone."""
        session = self.coordinator.get_latest_session_for_zone(self._zone_id)
        if not session:
            return None
        temp_data = session.get("temperature", {})
        values = temp_data.get("values", [])
        if values:
            return self._celsius_to_offset(values[-1])
        return None
```

- [ ] **Step 5: Rewrite `async_setup_entry`**

Replace the body of `async_setup_entry` in `sensor.py` with:

```python
    coordinator: OrionDataUpdateCoordinator = entry.runtime_data
    entities: list[SensorEntity] = []

    zone_labels = {"zone_a": "Zone A", "zone_b": "Zone B"}

    for device in coordinator.devices:
        device_id = device.get("id")
        if not device_id:
            continue

        # Device-level: sleep score, schedule, WS state, live per-sensor.
        entities.append(OrionSleepScoreSensor(coordinator, device_id))
        for description in SCHEDULE_SENSOR_DESCRIPTIONS:
            entities.append(
                OrionScheduleSensorEntity(coordinator, device_id, description)
            )
        entities.append(OrionWebSocketStateSensor(coordinator, device_id))
        for sensor_name in _TOPPER_SENSORS:
            entities.append(
                OrionLiveHeartRateSensor(coordinator, device_id, sensor_name)
            )
            entities.append(
                OrionLiveBreathRateSensor(coordinator, device_id, sensor_name)
            )
            entities.append(
                OrionSensorStatusTextSensor(coordinator, device_id, sensor_name)
            )

        # Per-zone: insight metrics + current temp offset.
        for zone in device.get("zones") or []:
            zone_id = zone.get("id")
            if not zone_id:
                continue
            zone_label = zone_labels.get(zone_id, zone_id)
            for description in INSIGHT_SENSOR_DESCRIPTIONS:
                entities.append(
                    OrionZoneInsightSensor(
                        coordinator, device_id, zone_id, zone_label, description
                    )
                )
            entities.append(
                OrionCurrentTempOffsetSensor(
                    coordinator, device_id, zone_id, zone_label
                )
            )

    async_add_entities(entities)
```

- [ ] **Step 6: Verify compile and no stale references**

Run: `python3 -m py_compile custom_components/orion_sleep/sensor.py`
Expected: exit 0.
Run: `grep -n "OrionSensorEntity\b\|get_latest_session(" custom_components/orion_sleep/sensor.py`
Expected: no matches (the old class name and the device-level session getter are gone from sensor.py).

- [ ] **Step 7: Commit**

```bash
git add custom_components/orion_sleep/sensor.py
git commit -m "Make insight + current-temp-offset sensors per-zone; split out Sleep Score"
```

## Task A4: Per-zone Sleep Session Active binary sensor

**Files:**
- Modify: `custom_components/orion_sleep/binary_sensor.py`

- [ ] **Step 1: Make the session-active sensor per-zone**

Replace `OrionSessionActiveBinarySensor.__init__` and `is_on` with:

```python
    def __init__(
        self,
        coordinator: OrionDataUpdateCoordinator,
        device_id: str,
        zone_id: str,
        zone_label: str,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._zone_id = zone_id
        self._attr_unique_id = f"{device_id}_session_active_{zone_id}"
        self._attr_translation_placeholders = {"zone": zone_label}

    @property
    def is_on(self) -> bool | None:
        """Return True if this zone's sleep session is currently active."""
        session = self.coordinator.get_latest_session_for_zone(self._zone_id)
        if not session:
            return False
        return session.get("is_in_progress", False)
```

- [ ] **Step 2: Update `async_setup_entry` to create one per zone**

Replace the `for device in coordinator.devices:` loop body in
`binary_sensor.py`'s `async_setup_entry` with:

```python
    zone_labels = {"zone_a": "Zone A", "zone_b": "Zone B"}
    for device in coordinator.devices:
        device_id = device.get("id")
        if not device_id:
            continue
        for zone in device.get("zones") or []:
            zone_id = zone.get("id")
            if not zone_id:
                continue
            entities.append(
                OrionSessionActiveBinarySensor(
                    coordinator, device_id, zone_id, zone_labels.get(zone_id, zone_id)
                )
            )
        for sensor_name in _TOPPER_SENSORS:
            entities.append(
                OrionSensorOnBedBinarySensor(coordinator, device_id, sensor_name)
            )
```

- [ ] **Step 3: Verify compile**

Run: `python3 -m py_compile custom_components/orion_sleep/binary_sensor.py`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add custom_components/orion_sleep/binary_sensor.py
git commit -m "Make Sleep Session Active binary sensor per-zone"
```

## Task A5: Translations for per-zone names

**Files:**
- Modify: `custom_components/orion_sleep/strings.json`
- Modify: `custom_components/orion_sleep/translations/en.json`

Per-zone entities render their name from a single translation key plus the
`{zone}` placeholder. Append `" {zone}"` to the names of the metrics that became
per-zone. Leave `sleep_score` and the schedule sensors unchanged.

- [ ] **Step 1: Update the sensor names in `strings.json`**

In `strings.json`, change these `"name"` values under `entity.sensor` (append
` {zone}`):

```json
      "total_sleep_time": { "name": "Total Sleep Time {zone}" },
      "deep_sleep_time": { "name": "Deep Sleep {zone}" },
      "rem_sleep_time": { "name": "REM Sleep {zone}" },
      "light_sleep_time": { "name": "Light Sleep {zone}" },
      "awake_time": { "name": "Awake Time {zone}" },
      "heart_rate_avg": { "name": "Heart Rate {zone}" },
      "breath_rate": { "name": "Breath Rate {zone}" },
      "hrv": { "name": "HRV {zone}" },
      "body_movement_rate": { "name": "Body Movement Rate {zone}" },
      "restless_time": { "name": "Restless Time {zone}" },
      "current_temp_offset": { "name": "Current Temperature Offset {zone}" },
```

- [ ] **Step 2: Update the binary_sensor name in `strings.json`**

Change the `sleep_session_active` block under `entity.binary_sensor` to:

```json
      "sleep_session_active": {
        "name": "Sleep Session {zone}",
        "state": {
          "on": "Asleep",
          "off": "Not asleep"
        }
      },
```

- [ ] **Step 3: Apply the identical changes in `translations/en.json`**

Make the same 11 sensor name changes and the `sleep_session_active` change in
`custom_components/orion_sleep/translations/en.json`.

- [ ] **Step 4: Validate JSON**

Run: `python3 -m json.tool custom_components/orion_sleep/strings.json >/dev/null && python3 -m json.tool custom_components/orion_sleep/translations/en.json >/dev/null && echo OK`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add custom_components/orion_sleep/strings.json custom_components/orion_sleep/translations/en.json
git commit -m "Add {zone} placeholders to per-zone insight names"
```

---

# MILESTONE B — Tier A diagnostics

## Task B1: Diagnostic extractors in `live_state.py`

**Files:**
- Modify: `custom_components/orion_sleep/live_state.py`
- Test: `tests/test_live_state.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_live_state.py`:

```python
DIAG = {
    "led_brightness": 60,
    "status": {
        "firmware": {"cb": "1.2.3", "ib": "4.5.6"},
        "network": {"name": "MyWifi", "rssi": -55, "ip": "192.168.1.9",
                    "mac": "aa:bb", "uptime": 100, "last_seen": 5},
        "safety": {"error": False, "error_codes": [], "error_descriptions": []},
        "zones": [{"id": "zone_a", "temp": 20.0, "thermal_state": "standby"}],
    },
}


def test_firmware():
    assert live_state.firmware(DIAG) == {"cb": "1.2.3", "ib": "4.5.6"}
    assert live_state.firmware(None) is None
    assert live_state.firmware({}) is None


def test_network_info_and_rssi():
    assert live_state.network_info(DIAG)["name"] == "MyWifi"
    assert live_state.wifi_rssi(DIAG) == -55
    assert live_state.wifi_rssi({}) is None
    assert live_state.wifi_rssi({"status": {"network": {"rssi": "x"}}}) is None


def test_safety_error_false_when_no_error():
    assert live_state.safety_error(DIAG) is False


def test_safety_error_true_on_flag_or_codes():
    assert live_state.safety_error({"status": {"safety": {"error": True}}}) is True
    assert live_state.safety_error(
        {"status": {"safety": {"error": False, "error_codes": ["E1"]}}}
    ) is True


def test_safety_error_none_when_absent():
    assert live_state.safety_error({"status": {}}) is None
    assert live_state.safety_error(None) is None


def test_led_brightness():
    assert live_state.led_brightness(DIAG) == 60
    assert live_state.led_brightness({}) is None
    assert live_state.led_brightness({"led_brightness": "x"}) is None


def test_zone_thermal_state():
    assert live_state.zone_thermal_state(DIAG, "zone_a") == "standby"
    assert live_state.zone_thermal_state(DIAG, "zone_b") is None
    assert live_state.zone_thermal_state(None, "zone_a") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_live_state.py -q`
Expected: FAIL (attributes don't exist yet).

- [ ] **Step 3: Implement**

Append to `custom_components/orion_sleep/live_state.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_live_state.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/orion_sleep/live_state.py tests/test_live_state.py
git commit -m "Add diagnostic extractors to live_state with tests"
```

## Task B2: Coordinator diagnostic wrappers

**Files:**
- Modify: `custom_components/orion_sleep/coordinator.py`

- [ ] **Step 1: Add wrapper methods**

In `coordinator.py`, immediately before `is_device_on`, add:

```python
    def firmware(self, device_id: str) -> dict | None:
        """Device firmware versions ({cb, ib}), or None."""
        return live_state.firmware(self.live_devices.get(device_id))

    def network_info(self, device_id: str) -> dict | None:
        """Device network block (name/rssi/ip/mac/...), or None."""
        return live_state.network_info(self.live_devices.get(device_id))

    def wifi_rssi(self, device_id: str) -> int | None:
        """Wi-Fi RSSI in dBm, or None."""
        return live_state.wifi_rssi(self.live_devices.get(device_id))

    def safety_error(self, device_id: str) -> bool | None:
        """True if the device reports a safety error, else False/None."""
        return live_state.safety_error(self.live_devices.get(device_id))

    def led_brightness(self, device_id: str) -> int | None:
        """LED brightness (0-100), or None."""
        return live_state.led_brightness(self.live_devices.get(device_id))

    def zone_thermal_state(self, device_id: str, zone_id: str) -> str | None:
        """Zone thermal state (e.g. 'standby'), or None."""
        return live_state.zone_thermal_state(self.live_devices.get(device_id), zone_id)
```

- [ ] **Step 2: Verify compile**

Run: `python3 -m py_compile custom_components/orion_sleep/coordinator.py`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add custom_components/orion_sleep/coordinator.py
git commit -m "Add coordinator diagnostic accessors"
```

## Task B3: Firmware + Wi-Fi diagnostic sensors and Problem binary sensor

**Files:**
- Modify: `custom_components/orion_sleep/sensor.py`
- Modify: `custom_components/orion_sleep/binary_sensor.py`
- Modify: `custom_components/orion_sleep/strings.json`, `translations/en.json`

- [ ] **Step 1: Add the two diagnostic sensors**

In `sensor.py`, add imports if missing (`SensorDeviceClass`) by changing the
sensor import block to:

```python
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
```

Then append these classes at the end of `sensor.py`:

```python
class OrionFirmwareSensor(OrionBaseEntity, SensorEntity):
    """Diagnostic: control-board firmware version (interface board + per-sensor as attrs)."""

    _attr_translation_key = "firmware_version"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chip"

    def __init__(self, coordinator: OrionDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_firmware_version"

    @property
    def native_value(self) -> str | None:
        fw = self.coordinator.firmware(self._device_id)
        return fw.get("cb") if fw else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs: dict[str, Any] = {}
        fw = self.coordinator.firmware(self._device_id)
        if fw and fw.get("ib") is not None:
            attrs["interface_board"] = fw["ib"]
        for name in _TOPPER_SENSORS:
            block = self.coordinator._sensor_block(self._device_id, name)  # noqa: SLF001
            if block:
                if block.get("firmware_version") is not None:
                    attrs[f"{name}_firmware"] = block["firmware_version"]
                if block.get("hardware_version") is not None:
                    attrs[f"{name}_hardware"] = block["hardware_version"]
        return attrs or None


class OrionWifiSignalSensor(OrionBaseEntity, SensorEntity):
    """Diagnostic: Wi-Fi signal strength (SSID/IP/MAC/uptime as attributes)."""

    _attr_translation_key = "wifi_signal"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = "dBm"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: OrionDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_wifi_signal"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.wifi_rssi(self._device_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        net = self.coordinator.network_info(self._device_id)
        if not net:
            return None
        attrs = {
            "ssid": net.get("name"),
            "ip": net.get("ip"),
            "mac": net.get("mac"),
            "uptime": net.get("uptime"),
            "last_seen": net.get("last_seen"),
        }
        return {k: v for k, v in attrs.items() if v is not None} or None
```

- [ ] **Step 2: Register the two sensors in `sensor.py` `async_setup_entry`**

In the device loop in `sensor.py` `async_setup_entry`, in the device-level
section (right after the `OrionWebSocketStateSensor` append), add:

```python
        entities.append(OrionFirmwareSensor(coordinator, device_id))
        entities.append(OrionWifiSignalSensor(coordinator, device_id))
```

- [ ] **Step 3: Add the Problem binary sensor**

In `binary_sensor.py`, append:

```python
class OrionProblemBinarySensor(OrionBaseEntity, BinarySensorEntity):
    """Diagnostic: device safety/error state from the live payload."""

    _attr_translation_key = "device_problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: OrionDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_problem"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.safety_error(self._device_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        live = self.coordinator.live_devices.get(self._device_id) or {}
        safety = (live.get("status") or {}).get("safety") or {}
        attrs = {
            "error_codes": safety.get("error_codes"),
            "error_descriptions": safety.get("error_descriptions"),
        }
        return {k: v for k, v in attrs.items() if v} or None
```

Add the required imports to `binary_sensor.py` (top of file): change the imports
to include `EntityCategory` and `Any`:

```python
from typing import Any

from homeassistant.helpers.entity import EntityCategory
```

- [ ] **Step 4: Register the Problem sensor**

In `binary_sensor.py` `async_setup_entry`, inside the device loop (after the
`for sensor_name in _TOPPER_SENSORS:` block), add:

```python
        entities.append(OrionProblemBinarySensor(coordinator, device_id))
```

- [ ] **Step 5: Add translation keys**

In both `strings.json` and `translations/en.json`, add under `entity.sensor`:

```json
      "firmware_version": { "name": "Firmware Version" },
      "wifi_signal": { "name": "Wi-Fi Signal" },
```

and under `entity.binary_sensor`:

```json
      "device_problem": { "name": "Problem" },
```

- [ ] **Step 6: Verify compile + JSON**

Run: `python3 -m py_compile custom_components/orion_sleep/sensor.py custom_components/orion_sleep/binary_sensor.py && python3 -m json.tool custom_components/orion_sleep/strings.json >/dev/null && python3 -m json.tool custom_components/orion_sleep/translations/en.json >/dev/null && echo OK`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add custom_components/orion_sleep/sensor.py custom_components/orion_sleep/binary_sensor.py custom_components/orion_sleep/strings.json custom_components/orion_sleep/translations/en.json
git commit -m "Add firmware, Wi-Fi signal, and Problem diagnostic entities"
```

## Task B4: HVAC action on the per-zone climate

**Files:**
- Modify: `custom_components/orion_sleep/climate.py`

- [ ] **Step 1: Import `HVACAction`**

In `climate.py`, change the climate import block to add `HVACAction`:

```python
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
```

- [ ] **Step 2: Add the `hvac_action` property**

In `OrionZoneClimateEntity`, immediately after the `hvac_mode` property, add:

```python
    @property
    def hvac_action(self) -> HVACAction | None:
        """Heating/idle/off from the zone's measured thermal state."""
        if self.coordinator.zone_is_on(self._device_id, self._zone_id) is not True:
            return HVACAction.OFF
        state = self.coordinator.zone_thermal_state(self._device_id, self._zone_id)
        if state is None:
            return None
        if "heat" in state.lower():
            return HVACAction.HEATING
        # Only "standby" has been observed; treat anything else (when on) as idle.
        return HVACAction.IDLE
```

- [ ] **Step 3: Verify compile**

Run: `python3 -m py_compile custom_components/orion_sleep/climate.py`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add custom_components/orion_sleep/climate.py
git commit -m "Add HVAC action to per-zone climate from thermal_state"
```

---

# MILESTONE C — Tier B controls

## Task C1: LED Brightness number

**Files:**
- Modify: `custom_components/orion_sleep/number.py`
- Modify: `custom_components/orion_sleep/strings.json`, `translations/en.json`

`device_action` uses the device **UUID** (`self._device_id`), unlike the live
zone endpoint. The action is unverified on-wire — Task C3 adds a probe.

- [ ] **Step 1: Append the LED number class**

Append to `custom_components/orion_sleep/number.py`:

```python
class OrionLedBrightnessNumber(OrionBaseEntity, NumberEntity):
    """LED brightness (0-100). Reads live state; writes via device_action."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_translation_key = "led_brightness"
    _attr_icon = "mdi:brightness-6"

    def __init__(
        self,
        coordinator: OrionDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_led_brightness"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.led_brightness(self._device_id)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.api_client.device_action(
            self._device_id, "device_led_brightness", value=int(value)
        )
        await self.coordinator.async_request_refresh()
```

- [ ] **Step 2: Register it in `number.py` `async_setup_entry`**

In the device loop in `number.py` `async_setup_entry`, after the
`for key, trans_key, icon, field in OFFSET_NUMBER_DEFS:` block, add:

```python
        entities.append(OrionLedBrightnessNumber(coordinator, device_id))
```

Also widen the list type hint at the top of `async_setup_entry`:

```python
    entities: list[NumberEntity] = []
```

- [ ] **Step 3: Add translation key**

In both `strings.json` and `translations/en.json`, add under `entity.number`:

```json
      "led_brightness": { "name": "LED Brightness" },
```

- [ ] **Step 4: Verify compile + JSON**

Run: `python3 -m py_compile custom_components/orion_sleep/number.py && python3 -m json.tool custom_components/orion_sleep/strings.json >/dev/null && python3 -m json.tool custom_components/orion_sleep/translations/en.json >/dev/null && echo OK`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add custom_components/orion_sleep/number.py custom_components/orion_sleep/strings.json custom_components/orion_sleep/translations/en.json
git commit -m "Add LED Brightness number control"
```

## Task C2: Reboot button (new platform)

**Files:**
- Create: `custom_components/orion_sleep/button.py`
- Modify: `custom_components/orion_sleep/__init__.py`
- Modify: `custom_components/orion_sleep/strings.json`, `translations/en.json`

- [ ] **Step 1: Create `button.py`**

```python
"""Button platform for Orion Sleep."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import OrionDataUpdateCoordinator
from .entity import OrionBaseEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Orion Sleep button entities."""
    coordinator: OrionDataUpdateCoordinator = entry.runtime_data
    entities: list[ButtonEntity] = []
    for device in coordinator.devices:
        device_id = device.get("id")
        if not device_id:
            continue
        entities.append(OrionRebootButton(coordinator, device_id))
    async_add_entities(entities)


class OrionRebootButton(OrionBaseEntity, ButtonEntity):
    """Reboot the topper via device_action."""

    _attr_translation_key = "reboot"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:restart"

    def __init__(
        self,
        coordinator: OrionDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_reboot"

    async def async_press(self) -> None:
        await self.coordinator.api_client.device_action(
            self._device_id, "device_reboot"
        )
```

- [ ] **Step 2: Register the BUTTON platform**

In `__init__.py`, change the `PLATFORMS` list to include `Platform.BUTTON`:

```python
PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
]
```

- [ ] **Step 3: Add translation key**

In both `strings.json` and `translations/en.json`, add a new top-level
`entity` sub-object for buttons (place it after the `binary_sensor` block):

```json
    "button": {
      "reboot": { "name": "Reboot" }
    },
```

- [ ] **Step 4: Verify compile + JSON**

Run: `python3 -m py_compile custom_components/orion_sleep/button.py custom_components/orion_sleep/__init__.py && python3 -m json.tool custom_components/orion_sleep/strings.json >/dev/null && python3 -m json.tool custom_components/orion_sleep/translations/en.json >/dev/null && echo OK`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add custom_components/orion_sleep/button.py custom_components/orion_sleep/__init__.py custom_components/orion_sleep/strings.json custom_components/orion_sleep/translations/en.json
git commit -m "Add Reboot button (new button platform)"
```

## Task C3: Verification tooling + API docs

**Files:**
- Modify: `orion_info.py`
- Modify: `openapi.yaml`, `AGENTS.md`

This task confirms the two unverified `device_action` writes on the live API and
records the result, per the repo's source-of-truth policy.

- [ ] **Step 1: Read the CLI structure**

Read `orion_info.py` and locate (a) the `argparse` argument definitions and
(b) the main flow where existing action flags like `--power-on` / `--power-off`
are handled. The new flags follow the same pattern.

- [ ] **Step 2: Add probe flags**

Add two argparse arguments alongside the existing action flags:

```python
    parser.add_argument(
        "--led-brightness", type=int, metavar="N",
        help="Probe device_led_brightness (0-100) on the first device",
    )
    parser.add_argument(
        "--reboot", action="store_true",
        help="Probe device_reboot on the first device",
    )
```

In the main flow, after devices are fetched, add handling that posts the action
via the same request helper the script already uses for
`POST /v1/devices/{deviceId}/action` (use the device UUID `id`), printing the
HTTP status and response body:

```python
    if args.led_brightness is not None:
        dev_id = devices[0]["id"]
        resp = client.post(f"/v1/devices/{dev_id}/action",
                           {"action": "device_led_brightness", "value": args.led_brightness})
        print("led_brightness ->", resp)
    if args.reboot:
        dev_id = devices[0]["id"]
        resp = client.post(f"/v1/devices/{dev_id}/action",
                           {"action": "device_reboot"})
        print("reboot ->", resp)
```

Adapt the exact client/post call to match the helper names already in
`orion_info.py` (read them in Step 1; do not invent a new HTTP client).

- [ ] **Step 3: Probe against the live device**

Run: `python orion_info.py --led-brightness 40`
Then: `python orion_info.py --reboot` (only if you're willing to reboot the topper)
Record whether each returns success and whether the LED visibly changes.

- [ ] **Step 4: Update docs with the result**

In `AGENTS.md`, update the `device_action` row / notes to mark
`device_led_brightness` and `device_reboot` as **verified** (or note the exact
failure if they don't work). In `openapi.yaml`, annotate the
`/v1/devices/{deviceId}/action` action enum accordingly.

- [ ] **Step 5: Commit**

```bash
git add orion_info.py openapi.yaml AGENTS.md
git commit -m "Add orion_info probes for LED/reboot actions; record verification"
```

---

# WRAP-UP

## Task W1: Docs, version bump, full verification

**Files:**
- Modify: `README.md`, `AGENTS.md`, `manifest.json`

- [ ] **Step 1: Update `README.md`**

In the Entities section: replace the single device-level insight sensor rows with
per-zone equivalents (note "Zone A / Zone B"); add a Diagnostics subsection
(Firmware Version, Wi-Fi Signal, Problem); add LED Brightness to Numbers; add a
Buttons subsection (Reboot); note climate now reports an HVAC action. Add a
migration note: the old device-level insight sensors (`*_heart_rate`, `*_hrv`,
etc. without a zone suffix) and the single `*_session_active` retire and show
unavailable until deleted.

- [ ] **Step 2: Update `AGENTS.md`**

Update the Entities table (per-zone insight rows with `_{key}_{zone_id}` unique
ids; new diagnostic sensors; LED number; reboot button; HVAC action), the
per-device entity count, the helper inventory (`latest_session_for_zone`,
diagnostic extractors + coordinator wrappers), and remove the
`current_temp_offset`-registered-twice Known Issue (fixed in 1.1.1).

- [ ] **Step 3: Bump version**

In `manifest.json`, set `"version": "1.2.0"`.

- [ ] **Step 4: Full verification**

Run: `python3 -m pytest tests/ -q`
Expected: all tests PASS.
Run: `python3 -m py_compile custom_components/orion_sleep/*.py`
Expected: exit 0.
Run: `python3 -m json.tool custom_components/orion_sleep/manifest.json >/dev/null && python3 -m json.tool custom_components/orion_sleep/strings.json >/dev/null && python3 -m json.tool custom_components/orion_sleep/translations/en.json >/dev/null && echo OK`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add README.md AGENTS.md custom_components/orion_sleep/manifest.json
git commit -m "Docs + version bump to 1.2.0 for per-zone metrics, diagnostics, controls"
```

- [ ] **Step 6: Manual HA verification (in a running Home Assistant)**

1. Load the branch; confirm no setup errors in the log (`orion_sleep`).
2. Per-zone insight sensors appear for Zone A and Zone B; values differ per side
   (cross-check `python orion_info.py --insights-days 3`).
3. Old device-level insight sensors show unavailable → delete them.
4. Firmware Version, Wi-Fi Signal (with SSID attribute), and Problem appear under
   diagnostics and match the live payload.
5. Climate cards show an HVAC action (idle/heating/off).
6. LED Brightness number reflects and changes the device LED; Reboot button works
   (only test reboot if convenient).

---

## Self-Review Notes

- **Spec coverage:** A (A0 gate, A1–A5: helper, wrapper, per-zone sensors, Sleep
  Score split, session-active, translations) ✓; B (B1–B4: extractors, wrappers,
  firmware/wifi/problem entities, hvac_action) ✓; C (C1–C3: LED number, reboot
  button + platform, verification tooling) ✓; wrap-up docs + 1.2.0 ✓; Quiet Mode
  excluded ✓; schedule sensors left device-level ✓; sleep-score-per-zone default
  = device-level ✓; translation_placeholders approach ✓.
- **Placeholder scan:** no TBD/TODO; every code/JSON step shows full content. The
  one read-then-adapt step (orion_info.py C3) is dev tooling whose exact HTTP
  helper must match the existing file — flagged explicitly, not a silent gap.
- **Type/name consistency:** `latest_session_for_zone` / `get_latest_session_for_zone`
  consistent across util/coordinator/sensor/binary_sensor; diagnostic helper
  names (`firmware`, `network_info`, `wifi_rssi`, `safety_error`,
  `led_brightness`, `zone_thermal_state`) consistent across live_state ↔
  coordinator ↔ entities; `device_action(device_id, action, value=)` matches
  `api.py`; translation keys match the `_attr_translation_key` values.
