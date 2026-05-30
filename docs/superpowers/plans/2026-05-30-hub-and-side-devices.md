# Hub + Per-Side Devices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group entities into three HA devices per topper — an Orion Hub plus nested Side A / Side B sub-devices — without adding/removing entities or changing any unique_id.

**Architecture:** `OrionBaseEntity` gains an optional `zone_id`; when set, `device_info` returns a side `DeviceInfo` (own identifier + `via_device` → hub) instead of the hub one. A dependency-free `util.side_device_descriptor` carries the identifier/name derivation and is unit-tested. The four zone entity classes pass their `zone_id` up; everything else stays on the hub unchanged.

**Tech Stack:** Python 3, Home Assistant custom integration, pytest (only `pytest` installed locally; HA not installed — HA-coupled code verified via `py_compile` + manual).

---

## File Structure

- `custom_components/orion_sleep/util.py` — add `side_device_descriptor` (pure).
- `custom_components/orion_sleep/entity.py` — `OrionBaseEntity` accepts `zone_id`; `device_info` branches hub vs side.
- `custom_components/orion_sleep/climate.py`, `sensor.py`, `binary_sensor.py` — the four zone entity classes pass `zone_id` to the base.
- `tests/test_util.py` — tests for `side_device_descriptor`.
- `README.md`, `AGENTS.md`, `manifest.json` — docs + version 1.3.0.

---

## Task 1: `side_device_descriptor` pure helper

**Files:**
- Modify: `custom_components/orion_sleep/util.py`
- Test: `tests/test_util.py`

- [ ] **Step 1: Append failing tests to `tests/test_util.py`**

```python
def test_side_device_descriptor_zone_a():
    d = util.side_device_descriptor("dev123", "zone_a")
    assert d == {"identifier": "dev123_zone_a", "via": "dev123", "name": "Side A"}


def test_side_device_descriptor_zone_b():
    d = util.side_device_descriptor("dev123", "zone_b")
    assert d == {"identifier": "dev123_zone_b", "via": "dev123", "name": "Side B"}


def test_side_device_descriptor_unknown_zone_uses_raw_id():
    d = util.side_device_descriptor("dev123", "zone_c")
    assert d["identifier"] == "dev123_zone_c"
    assert d["via"] == "dev123"
    assert d["name"] == "Side zone_c"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_util.py -q`
Expected: FAIL (`AttributeError: module ... has no attribute 'side_device_descriptor'`).

- [ ] **Step 3: Append the implementation to `custom_components/orion_sleep/util.py`**

```python
def side_device_descriptor(device_id: str, zone_id: str) -> dict:
    """Describe the per-side sub-device for a zone.

    Returns the identifier suffix, the hub it links to via ``via_device``, and
    the display name. ``zone_a`` -> "Side A", ``zone_b`` -> "Side B"; any other
    zone id falls back to ``f"Side {zone_id}"``.
    """
    labels = {"zone_a": "A", "zone_b": "B"}
    label = labels.get(zone_id, zone_id)
    return {
        "identifier": f"{device_id}_{zone_id}",
        "via": device_id,
        "name": f"Side {label}",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_util.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/orion_sleep/util.py tests/test_util.py
git commit -m "Add side_device_descriptor helper with tests"
```

---

## Task 2: `OrionBaseEntity` zone-aware device_info

**Files:**
- Modify: `custom_components/orion_sleep/entity.py`

No automated test (requires HA). The identifier/name derivation is covered by Task 1; this task is wiring, verified by py_compile + manual.

Current `entity.py` imports: `from homeassistant.helpers.device_registry import DeviceInfo`, `from homeassistant.helpers.update_coordinator import CoordinatorEntity`, `from .const import DEFAULT_RELATIVE_TEMP_TABLE, DOMAIN`, `from .coordinator import OrionDataUpdateCoordinator`.

- [ ] **Step 1: Add the `util` import**

In `entity.py`, after `from .const import DEFAULT_RELATIVE_TEMP_TABLE, DOMAIN`, add:

```python
from . import util
```

- [ ] **Step 2: Accept `zone_id` in `__init__`**

Replace the existing `__init__`:

```python
    def __init__(
        self,
        coordinator: OrionDataUpdateCoordinator,
        device_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
```

with:

```python
    def __init__(
        self,
        coordinator: OrionDataUpdateCoordinator,
        device_id: str,
        zone_id: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        # When set, this entity belongs to a per-side sub-device that nests
        # under the hub (device_id) via via_device. When None, the entity
        # lives directly on the hub device.
        self._zone_id = zone_id
```

- [ ] **Step 3: Branch `device_info` for hub vs side**

Replace the existing `device_info` property:

```python
    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this entity."""
        device = self._get_device()
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=device.get("name", "Orion Sleep"),
            manufacturer="Orion Longevity",
            model=device.get("model", "Orion Sleep"),
            serial_number=device.get("serial_number"),
        )
```

with:

```python
    @property
    def device_info(self) -> DeviceInfo:
        """Return device info: the hub, or a per-side sub-device."""
        device = self._get_device()
        if self._zone_id is None:
            return DeviceInfo(
                identifiers={(DOMAIN, self._device_id)},
                name=device.get("name", "Orion Sleep"),
                manufacturer="Orion Longevity",
                model=device.get("model", "Orion Sleep"),
                serial_number=device.get("serial_number"),
            )
        desc = util.side_device_descriptor(self._device_id, self._zone_id)
        return DeviceInfo(
            identifiers={(DOMAIN, desc["identifier"])},
            via_device=(DOMAIN, desc["via"]),
            name=desc["name"],
            manufacturer="Orion Longevity",
            model=device.get("model", "Orion Sleep"),
        )
```

- [ ] **Step 4: Verify compile**

Run: `python3 -m py_compile custom_components/orion_sleep/entity.py`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add custom_components/orion_sleep/entity.py
git commit -m "Make OrionBaseEntity device_info zone-aware (hub vs side sub-device)"
```

---

## Task 3: Zone entities opt into their side device

**Files:**
- Modify: `custom_components/orion_sleep/climate.py`
- Modify: `custom_components/orion_sleep/sensor.py`
- Modify: `custom_components/orion_sleep/binary_sensor.py`

Each zone entity already stores a `zone_id`; pass it up to the base so its
`device_info` becomes the side sub-device. These are the ONLY four classes that
change; all other entities keep `zone_id=None` and stay on the hub.

- [ ] **Step 1: `OrionZoneClimateEntity` (climate.py)**

In `OrionZoneClimateEntity.__init__`, change:

```python
        super().__init__(coordinator, device_id)
        self._serial = serial
        self._zone_id = zone_id
```

to:

```python
        super().__init__(coordinator, device_id, zone_id=zone_id)
        self._serial = serial
        self._zone_id = zone_id
```

(Leave the rest of `__init__` unchanged. `self._zone_id` is still set locally
because the climate entity reads it elsewhere; passing it to `super()` is
additive.)

- [ ] **Step 2: `OrionZoneInsightSensor` (sensor.py)**

In `OrionZoneInsightSensor.__init__`, change:

```python
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._zone_id = zone_id
```

to:

```python
        super().__init__(coordinator, device_id, zone_id=zone_id)
        self.entity_description = description
        self._zone_id = zone_id
```

- [ ] **Step 3: `OrionCurrentTempOffsetSensor` (sensor.py)**

In `OrionCurrentTempOffsetSensor.__init__`, change:

```python
        super().__init__(coordinator, device_id)
        self._zone_id = zone_id
        self._attr_unique_id = f"{device_id}_current_temp_offset_{zone_id}"
```

to:

```python
        super().__init__(coordinator, device_id, zone_id=zone_id)
        self._zone_id = zone_id
        self._attr_unique_id = f"{device_id}_current_temp_offset_{zone_id}"
```

- [ ] **Step 4: `OrionSessionActiveBinarySensor` (binary_sensor.py)**

In `OrionSessionActiveBinarySensor.__init__`, change:

```python
        super().__init__(coordinator, device_id)
        self._zone_id = zone_id
        self._attr_unique_id = f"{device_id}_session_active_{zone_id}"
```

to:

```python
        super().__init__(coordinator, device_id, zone_id=zone_id)
        self._zone_id = zone_id
        self._attr_unique_id = f"{device_id}_session_active_{zone_id}"
```

- [ ] **Step 5: Verify compile + confirm no other class passes zone_id**

Run: `python3 -m py_compile custom_components/orion_sleep/climate.py custom_components/orion_sleep/sensor.py custom_components/orion_sleep/binary_sensor.py`
Expected: exit 0.
Run: `grep -rn "zone_id=zone_id" custom_components/orion_sleep/*.py`
Expected: exactly the four `super().__init__(... zone_id=zone_id)` lines (climate, two in sensor, one in binary_sensor) — no others.

- [ ] **Step 6: Commit**

```bash
git add custom_components/orion_sleep/climate.py custom_components/orion_sleep/sensor.py custom_components/orion_sleep/binary_sensor.py
git commit -m "Attach zone climate + per-zone sensors to their Side sub-device"
```

---

## Task 4: Docs + version bump

**Files:**
- Modify: `README.md`, `AGENTS.md`, `manifest.json`

- [ ] **Step 1: README — add a device-layout note**

In `README.md`, in the `## Entities` area (just under the "One device is created
per paired topper..." line, or replacing it), add:

```markdown
Each topper is represented as three Home Assistant devices: an **Orion Hub**
(whole-bed controls, schedule, diagnostics, and the live per-sensor readings)
with two sub-devices, **Side A** and **Side B**, nested under it. Each Side holds
that side's climate plus its per-session sleep metrics (HRV, heart rate, sleep
stages, etc.). The Side names default to "Side A" / "Side B" — rename them in the
HA UI (Settings > Devices & Services > device > rename) if you like.
```

- [ ] **Step 2: AGENTS.md — note the device structure**

In `AGENTS.md`, near the top of the Entities section, add a short paragraph:

```markdown
**Device structure:** per topper there are three devices — the hub
(`identifiers={(DOMAIN, device_id)}`) and two sub-devices Side A / Side B
(`identifiers={(DOMAIN, f"{device_id}_zone_a|zone_b")}`, `via_device` → hub).
Hub-hosted: switches, schedule sensors + offset numbers, LED brightness, reboot,
sleep score, diagnostics (live connection, firmware, wifi, problem), and the live
Sensor 1/2 vitals (their side mapping is still unverified). Side-hosted: that
zone's climate, per-zone insight sensors, current temp offset, and session-active
binary sensor. Built via the optional `zone_id` on `OrionBaseEntity` +
`util.side_device_descriptor`.
```

- [ ] **Step 3: Bump version**

In `manifest.json`, set `"version": "1.3.0"`.

- [ ] **Step 4: Full verification**

Run: `python3 -m pytest tests/ -q`
Expected: all tests PASS.
Run: `python3 -m py_compile custom_components/orion_sleep/*.py`
Expected: exit 0.
Run: `python3 -m json.tool custom_components/orion_sleep/manifest.json >/dev/null && echo OK`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add README.md AGENTS.md custom_components/orion_sleep/manifest.json
git commit -m "Docs + version bump to 1.3.0 for Hub + per-side device split"
```

- [ ] **Step 6: Manual HA verification**

1. Load the branch; restart HA; confirm no `orion_sleep` setup errors in the log.
2. Settings > Devices & Services > Orion Sleep: confirm **three** devices — Orion
   Hub with **Side A** and **Side B** nested under it (via_device).
3. Side A/B each show their climate + per-zone insight + session-active entities;
   the hub shows switches, schedule, diagnostics, LED/Reboot, and the Sensor 1/2
   live readings.
4. Confirm entity_ids are unchanged (no `_2` suffixes) and history is intact — the
   entities re-homed onto the new devices without being recreated.

---

## Self-Review Notes

- **Spec coverage:** three-device structure + via_device (Tasks 2,3) ✓; hub keeps
  existing identifier (Task 2, `zone_id is None` branch) ✓; side identifiers +
  names "Side A"/"Side B" with raw-id fallback (Task 1) ✓; only the four zone
  classes move (Task 3) ✓; live Sensor 1/2 stay on hub (untouched — they don't
  pass zone_id) ✓; pure testable helper (Task 1) ✓; unique_ids unchanged →
  migration carries over (no unique_id edits anywhere) ✓; docs + 1.3.0 (Task 4) ✓.
  Out-of-scope items (config-flow naming, moving live sensors, splitting schedule)
  correctly absent.
- **Placeholder scan:** no TBD/TODO; every code step shows full content.
- **Type/name consistency:** `side_device_descriptor(device_id, zone_id)` returns
  `{"identifier","via","name"}`, consumed identically in entity.py; the base
  `__init__` signature `(coordinator, device_id, zone_id=None)` matches all four
  `super().__init__(..., zone_id=zone_id)` call sites; existing hub entities call
  `super().__init__(coordinator, device_id)` (zone_id defaults None) and are
  unaffected.
