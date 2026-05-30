# Dual Per-Zone Climate Entities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single device-level Bed Climate entity with two independent per-zone climate entities (`zone_a`, `zone_b`) driven by the verified live per-zone endpoint.

**Architecture:** Extract the zone-state reading logic into a dependency-free `live_state.py` module (unit-testable without Home Assistant), have the coordinator expose thin wrapper methods over it, and build one `OrionZoneClimateEntity` per zone that reads measured/setpoint/on state from the coordinator and writes via `update_live_device_zone(serial, zone_id, ...)`.

**Tech Stack:** Python 3, Home Assistant custom integration, aiohttp API client, pytest (only `pytest` is installed locally — `homeassistant`/`aiohttp` are not, so automated tests cover only the dependency-free `live_state` module; HA-coupled code is verified manually).

---

## File Structure

- **Create** `custom_components/orion_sleep/live_state.py` — pure functions that read per-zone setpoint / on / measured-temp out of a live-device dict. Imports nothing from Home Assistant so it is unit-testable standalone.
- **Create** `tests/test_live_state.py` — pytest tests for `live_state.py`, importing the module by file path to avoid triggering the package `__init__.py` (which imports HA).
- **Modify** `custom_components/orion_sleep/coordinator.py` — add `zone_setpoint`, `zone_is_on`, `zone_measured_temp` wrapper methods that delegate to `live_state`.
- **Modify** `custom_components/orion_sleep/climate.py` — replace `OrionClimateEntity` with `OrionZoneClimateEntity`; create one per zone.
- **Modify** `custom_components/orion_sleep/strings.json` and `custom_components/orion_sleep/translations/en.json` — add `bed_climate_zone_a` / `bed_climate_zone_b`, remove `bed_climate` / `bed_climate_left` / `bed_climate_right`.
- **Modify** `AGENTS.md` and `README.md` — update entity tables, per-device entity count, and the climate section.

---

## Task 1: Pure zone-state module (`live_state.py`) with tests

**Files:**
- Create: `custom_components/orion_sleep/live_state.py`
- Test: `tests/test_live_state.py`

The live-device dict (one entry of `coordinator.live_devices`) has this shape (see `openapi.yaml` / AGENTS.md WebSocket payload):

```python
{
    "zones": [{"id": "zone_a", "temp": 21.0, "on": True}, ...],   # setpoints (user intent)
    "status": {
        "zones": [{"id": "zone_a", "temp": 20.4, "thermal_state": "standby"}, ...],  # measured
    },
}
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_live_state.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_live_state.py -v`
Expected: FAIL — `FileNotFoundError` / module load error because `live_state.py` does not exist yet.

- [ ] **Step 3: Write the implementation**

Create `custom_components/orion_sleep/live_state.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_live_state.py -v`
Expected: PASS — all 7 tests green.

- [ ] **Step 5: Commit**

```bash
git add custom_components/orion_sleep/live_state.py tests/test_live_state.py
git commit -m "Add dependency-free per-zone live-state helpers with tests"
```

---

## Task 2: Coordinator wrapper methods

**Files:**
- Modify: `custom_components/orion_sleep/coordinator.py`

No automated test: instantiating `OrionDataUpdateCoordinator` requires Home Assistant, which is not installed locally. The logic these wrap is already covered by Task 1's tests. Verify by import-compile and manual review.

- [ ] **Step 1: Add the `live_state` import**

In `coordinator.py`, find the existing relative imports near the top:

```python
from .api import OrionApiClient, OrionApiError, OrionAuthError, OrionConnectionError
```

Add immediately after it:

```python
from . import live_state
```

- [ ] **Step 2: Add the three wrapper methods**

In `coordinator.py`, locate `is_device_on` (currently the last method in the class, ending around line 419). Add these three methods immediately **before** `is_device_on`:

```python
    def zone_setpoint(self, device_id: str, zone_id: str) -> float | None:
        """Target temperature (setpoint, °C) for one zone, or None.

        Reads the live per-zone setpoint fed by the WebSocket stream and
        backstopped by ``GET /v1/devices/{serial}/live``.
        """
        return live_state.zone_setpoint(self.live_devices.get(device_id), zone_id)

    def zone_is_on(self, device_id: str, zone_id: str) -> bool | None:
        """Power state for one zone, or None if no live state yet."""
        return live_state.zone_is_on(self.live_devices.get(device_id), zone_id)

    def zone_measured_temp(self, device_id: str, zone_id: str) -> float | None:
        """Measured current temperature (°C) for one zone, or None.

        From ``live.status.zones[].temp`` — the real per-zone reading,
        distinct from the setpoint at ``live.zones[].temp``.
        """
        return live_state.zone_measured_temp(
            self.live_devices.get(device_id), zone_id
        )
```

- [ ] **Step 3: Verify the module compiles**

Run: `python3 -m py_compile custom_components/orion_sleep/coordinator.py custom_components/orion_sleep/live_state.py`
Expected: no output, exit code 0.

- [ ] **Step 4: Commit**

```bash
git add custom_components/orion_sleep/coordinator.py
git commit -m "Add per-zone coordinator accessors delegating to live_state"
```

---

## Task 3: Per-zone climate entity

**Files:**
- Modify: `custom_components/orion_sleep/climate.py` (full replacement of the file body)

No automated test (requires HA). Verified by compile + manual HA run in Task 6.

- [ ] **Step 1: Replace `climate.py` entirely**

Overwrite `custom_components/orion_sleep/climate.py` with:

```python
"""Climate platform for Orion Sleep.

One climate entity per device *zone* (zone_a, zone_b). Each entity reads
and writes the verified live per-zone primitive
(``PUT /v1/devices/{serial_number}/live/zones/{zoneId}``):

* current temperature  <- live measured temp (status.zones[].temp)
* target temperature   <- live setpoint (zones[].temp)
* hvac mode            <- live zone ``on`` flag
* set temperature / turn on / turn off  -> live per-zone write

The live endpoint path uses the device ``serial_number``, NOT its UUID.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import OrionDataUpdateCoordinator
from .entity import OrionBaseEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one climate entity per device zone (zone_a, zone_b)."""
    coordinator: OrionDataUpdateCoordinator = entry.runtime_data
    entities: list[OrionZoneClimateEntity] = []

    for device in coordinator.devices:
        device_id = device.get("id")
        serial = device.get("serial_number")
        if not device_id or not serial:
            continue
        for zone in device.get("zones") or []:
            zone_id = zone.get("id")
            if not zone_id:
                continue
            entities.append(
                OrionZoneClimateEntity(coordinator, device_id, serial, zone_id, device)
            )

    async_add_entities(entities)


class OrionZoneClimateEntity(OrionBaseEntity, ClimateEntity):
    """Climate entity for a single Orion bed zone.

    All state is read from the live per-zone snapshot and all writes go
    through the live per-zone endpoint, so the two sides are fully
    independent. The entity works in absolute Celsius so HA's C->F unit
    conversion applies.
    """

    _attr_hvac_modes = [HVACMode.HEAT_COOL, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _enable_turn_on_off_backwards_compat = False

    def __init__(
        self,
        coordinator: OrionDataUpdateCoordinator,
        device_id: str,
        serial: str,
        zone_id: str,
        device: dict,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._serial = serial
        self._zone_id = zone_id
        self._attr_unique_id = f"{device_id}_climate_{zone_id}"
        self._attr_translation_key = f"bed_climate_{zone_id}"

        temp_range = device.get("temperature_range", {})
        self._attr_min_temp = float(temp_range.get("min", 10))
        self._attr_max_temp = float(temp_range.get("max", 45))
        self._attr_target_temperature_step = 0.5

    @property
    def current_temperature(self) -> float | None:
        """Measured temperature for this zone from the live snapshot."""
        return self.coordinator.zone_measured_temp(self._device_id, self._zone_id)

    @property
    def target_temperature(self) -> float | None:
        """Setpoint temperature for this zone from the live snapshot."""
        return self.coordinator.zone_setpoint(self._device_id, self._zone_id)

    @property
    def hvac_mode(self) -> HVACMode:
        """HEAT_COOL when the zone is on, otherwise OFF."""
        if self.coordinator.zone_is_on(self._device_id, self._zone_id) is True:
            return HVACMode.HEAT_COOL
        return HVACMode.OFF

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set this zone's target temperature.

        If the zone is currently off, also turn it on so the setpoint
        takes effect (standard HA expectation).
        """
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        turn_on = self.coordinator.zone_is_on(self._device_id, self._zone_id) is not True
        await self.coordinator.api_client.update_live_device_zone(
            self._serial,
            self._zone_id,
            on=True if turn_on else None,
            temp=temp,
        )
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Turn the zone on (HEAT_COOL) or off (OFF)."""
        await self.coordinator.api_client.update_live_device_zone(
            self._serial,
            self._zone_id,
            on=(hvac_mode == HVACMode.HEAT_COOL),
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        """Turn this zone on."""
        await self.coordinator.api_client.update_live_device_zone(
            self._serial, self._zone_id, on=True
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn this zone off."""
        await self.coordinator.api_client.update_live_device_zone(
            self._serial, self._zone_id, on=False
        )
        await self.coordinator.async_request_refresh()
```

- [ ] **Step 2: Verify the module compiles**

Run: `python3 -m py_compile custom_components/orion_sleep/climate.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Confirm `set_temperature` is no longer referenced by climate**

Run: `grep -n "set_temperature" custom_components/orion_sleep/climate.py`
Expected: only the `async_set_temperature` HA method definition appears — no call to `api_client.set_temperature(`. (The unverified `api_client.set_temperature` stays in `api.py` but is now unused by climate.)

- [ ] **Step 4: Commit**

```bash
git add custom_components/orion_sleep/climate.py
git commit -m "Replace device-level climate with per-zone climate entities"
```

---

## Task 4: Translation strings

**Files:**
- Modify: `custom_components/orion_sleep/strings.json`
- Modify: `custom_components/orion_sleep/translations/en.json`

- [ ] **Step 1: Update `strings.json`**

In `custom_components/orion_sleep/strings.json`, replace the `climate` block:

```json
    "climate": {
      "bed_climate": {
        "name": "Bed Climate"
      },
      "bed_climate_left": {
        "name": "Bed Climate Left"
      },
      "bed_climate_right": {
        "name": "Bed Climate Right"
      }
    },
```

with:

```json
    "climate": {
      "bed_climate_zone_a": {
        "name": "Bed Climate Zone A"
      },
      "bed_climate_zone_b": {
        "name": "Bed Climate Zone B"
      }
    },
```

- [ ] **Step 2: Update `translations/en.json`**

Apply the identical replacement in `custom_components/orion_sleep/translations/en.json` (same old block, same new block).

- [ ] **Step 3: Verify both files are valid JSON**

Run: `python3 -m json.tool custom_components/orion_sleep/strings.json > /dev/null && python3 -m json.tool custom_components/orion_sleep/translations/en.json > /dev/null && echo OK`
Expected: `OK`

- [ ] **Step 4: Confirm the zone keys match the translation_key derivation**

Run: `grep -n "bed_climate_zone_" custom_components/orion_sleep/strings.json custom_components/orion_sleep/translations/en.json`
Expected: `bed_climate_zone_a` and `bed_climate_zone_b` in both files. These must match `f"bed_climate_{zone_id}"` from Task 3 (`zone_id` values `zone_a` / `zone_b`).

- [ ] **Step 5: Commit**

```bash
git add custom_components/orion_sleep/strings.json custom_components/orion_sleep/translations/en.json
git commit -m "Add per-zone climate translation strings"
```

---

## Task 5: Documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`

- [ ] **Step 1: Update `AGENTS.md` climate entity row**

In `AGENTS.md`, in the Entities table, replace the existing climate row:

```
| Climate | Bed Climate | `_climate` | Target temp from `today_sleep_schedule.bedtime_temp`, current from latest session `temperature.values[-1]` |
```

with:

```
| Climate | Bed Climate Zone A/B | `_climate_zone_a` / `_climate_zone_b` | One entity per zone. Target temp from live setpoint `zones[].temp`, current from measured `status.zones[].temp`, HVAC mode from `zones[].on`. Writes via `PUT /v1/devices/{serial}/live/zones/{zoneId}`. |
```

- [ ] **Step 2: Update the per-device entity count line in `AGENTS.md`**

Find:

```
**Per device: 1 climate + 4 number + 24 sensors + 3 binary sensors + 3 switches = 35 entities**
```

Replace with:

```
**Per device: 2 climate (one per zone) + 4 number + 24 sensors + 3 binary sensors + 3 switches = 36 entities**
```

- [ ] **Step 3: Update the climate description in `AGENTS.md` setup comment / known issues**

In `AGENTS.md`, find the climate no-op limitation:

```
- `async_set_hvac_mode(OFF)` and `async_turn_off()` on climate entity are no-ops (schedule-based control only)
```

Replace with:

```
- Climate is now per-zone and live-driven: `async_turn_on` / `async_turn_off` / `async_set_hvac_mode` write the zone `on` flag via `PUT /v1/devices/{serial}/live/zones/{zoneId}` and take effect immediately (no longer no-ops).
```

Also update the "Unused translations" Known Issue:

```
- **Unused translations**: `bed_climate_left` and `bed_climate_right` defined in strings.json but no entities use them
```

Replace with:

```
- **Unused translations**: none for climate — `bed_climate_zone_a` / `bed_climate_zone_b` are both in use.
```

- [ ] **Step 4: Update `README.md` climate section**

In `README.md`, replace the Climate table:

```
### Climate

| Entity | Description |
|---|---|
| Bed Climate | Target temperature read from today's schedule, current temperature from the latest session's most-recent sample. HVAC mode reflects whether a session is in progress. |
```

with:

```
### Climate

One climate entity per bed zone. Each side is controlled independently via the live per-zone endpoint.

| Entity | Description |
|---|---|
| Bed Climate Zone A | Target = live setpoint for zone A; current = measured zone-A temperature; HVAC mode reflects whether the zone is on. Turning it on/off and setting a temperature take effect immediately. |
| Bed Climate Zone B | Same as Zone A, for the other zone. |

The zone → physical side (left/right) mapping is unverified, so entities are named by zone. Rename them in the HA UI if you confirm which side is which.
```

- [ ] **Step 5: Update the `README.md` climate notes/limitations**

In `README.md` under "Notes and limitations", replace:

```
- Writing to `PUT /v1/sleep-configurations/temperature` has not been verified against the live API; climate `set_temperature` and the Number sliders use `PUT /v1/sleep-schedules` instead, which is confirmed.
- Home Assistant's climate `async_turn_off` / `async_set_hvac_mode(OFF)` are no-ops for Bed Climate — the underlying system is schedule-driven. Use the **Power** switch to actually turn the device off.
```

with:

```
- Climate entities are per-zone and use the verified live endpoint `PUT /v1/devices/{serial}/live/zones/{zoneId}`. Turning a zone on/off and setting its temperature take effect immediately and independently per side. The **Power** switch still controls all zones at once.
- The Number temperature-offset sliders remain schedule-driven (`PUT /v1/sleep-schedules`); they adjust the schedule, while the climate entities set the live runtime setpoint.
```

- [ ] **Step 6: Commit**

```bash
git add AGENTS.md README.md
git commit -m "Document per-zone climate entities"
```

---

## Task 6: Manual end-to-end verification

**Files:** none (verification only)

No automated path exists for the HA-coupled behavior (HA is not installed locally), so this is manual against a running Home Assistant with the integration loaded.

- [ ] **Step 1: Confirm all automated tests still pass**

Run: `python3 -m pytest tests/ -v`
Expected: all `tests/test_live_state.py` tests PASS.

- [ ] **Step 2: Load the integration in Home Assistant**

Copy `custom_components/orion_sleep` into the HA `config/custom_components/` directory (or restart HA if developing in place). Restart Home Assistant. Confirm the integration loads with no errors in **Settings > System > Logs** filtered for `orion_sleep`.

- [ ] **Step 3: Confirm two climate entities exist per device**

In **Settings > Devices & Services > Orion Sleep > <device>**, confirm two climate entities appear: "Bed Climate Zone A" and "Bed Climate Zone B" (entity_ids ending `_climate_zone_a` / `_climate_zone_b`). Confirm the old `climate.*_climate` entity now shows as **unavailable**; delete it from the entity registry.

- [ ] **Step 4: Confirm per-zone readings are independent**

Each climate card should show its own current temperature. Compare against a live capture:

Run: `python3 orion_info.py --websocket --ws-duration 30`
Expected: the per-zone `status.zones[].temp` values in the frames match what each climate entity shows as current temperature.

- [ ] **Step 5: Confirm per-zone control affects only that zone**

Set Zone A to a distinct temperature in the HA UI while watching:

Run: `python3 orion_info.py --websocket --ws-duration 30`
Expected: a `live_device.update` frame shows `zones[zone_a].temp` changed to the new value and `zones[zone_b]` unchanged. Repeat turning Zone A off — expect `zones[zone_a].on=false` only, and the Zone A card's HVAC mode shows OFF while Zone B stays as-is.

- [ ] **Step 6: Final commit if any doc tweaks were needed during verification**

```bash
git add -A
git commit -m "Tidy per-zone climate verification notes" || echo "nothing to commit"
```

---

## Self-Review Notes

- **Spec coverage:** entity structure (Task 3), unique_id `_climate_{zone_id}` (Task 3), naming + translations (Task 4), coordinator helpers (Tasks 1–2), entity behavior table incl. set-temp-turns-on (Task 3), Power-switch independence (documented Task 5), error handling = propagate (no swallowing added, Task 3), manual verification (Task 6), docs (Task 5), out-of-scope items left untouched. All covered.
- **Placeholder scan:** no TBD/TODO; every code/JSON/doc step shows full content.
- **Type consistency:** `zone_setpoint` / `zone_is_on` / `zone_measured_temp` names identical across `live_state.py`, coordinator wrappers, and entity calls; `update_live_device_zone(serial, zone_id, on=, temp=)` matches `api.py`; translation_key `f"bed_climate_{zone_id}"` matches the `bed_climate_zone_a/b` JSON keys.
