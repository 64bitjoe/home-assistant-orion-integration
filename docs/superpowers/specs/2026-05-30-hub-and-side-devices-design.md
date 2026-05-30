# Hub + Per-Side Devices — Design

**Date:** 2026-05-30
**Target release:** 1.3.0
**Status:** Approved (pre-implementation)

## Goal

Restructure the integration's Home Assistant **device** layout so each topper is
represented as a small hierarchy:

- **Orion Hub** — whole-bed / account-level entities.
- **Side A** — zone_a's climate + per-zone sleep metrics.
- **Side B** — zone_b's climate + per-zone sleep metrics.

Side A and Side B are nested under the Hub via `via_device`. This is a
device-grouping change only — no entity is added or removed, and unique_ids /
entity_ids do not change, so history and automations carry over.

## Background

Today every entity attaches to a single device. `OrionBaseEntity.device_info`
(`entity.py`) returns one `DeviceInfo` keyed by `identifiers={(DOMAIN, device_id)}`
for all entities. As of 1.2.0 there are per-zone climate + per-zone insight
sensors, but they all still live on the one device, so a two-person bed is one
flat list.

Home Assistant supports multiple devices per config entry and a `via_device`
parent link, which renders sub-devices nested under a hub.

## Decisions (from brainstorming)

1. Three devices: **Orion Hub** (keeps the existing identifier) + **Side A** +
   **Side B** (new identifiers, `via_device` → Hub).
2. Side device names default to **"Side A" / "Side B"**; the user renames them in
   the HA UI if desired (no config-flow naming field).
3. The **live Sensor 1 / Sensor 2** readings (real-time HR/breath/on-bed) stay on
   the **Hub** for now — the sensor→side mapping is unverified. They move to the
   side devices later once confirmed.
4. The per-zone **climate** entities move onto the Side devices (each Side device
   is then self-contained).

## Device assignment

**Orion Hub** (`identifiers={(DOMAIN, device_id)}` — unchanged):
- Switches: Power, Away Mode, Sleep Schedule
- Diagnostics: Live Connection, Firmware Version, Wi-Fi Signal, Problem
- Sleep Score (device-level)
- Schedule sensors: Bedtime, Wake Up Time, Schedule Duration, Bedtime Temp,
  Wake Up Temp
- Numbers: the 4 schedule offset sliders + LED Brightness
- Reboot button
- Live per-sensor entities: Sensor 1/2 Heart Rate, Sensor 1/2 Breath Rate,
  Sensor 1/2 Status, Sensor 1/2 On Bed

**Side A** (`identifiers={(DOMAIN, f"{device_id}_zone_a")}`, `via_device=(DOMAIN, device_id)`)
and **Side B** (`..._zone_b`):
- Bed Climate (that zone)
- Per-zone insight sensors: Total/Deep/REM/Light/Awake sleep, Heart Rate,
  Breath Rate, HRV, Body Movement Rate, Restless Time, Current Temp Offset
- Sleep Session Active (that zone)

## Architecture

`OrionBaseEntity.__init__` gains an optional `zone_id: str | None = None`
parameter (default None → hub behavior). A pure helper builds the right
`DeviceInfo`:

- `zone_id is None` → hub `DeviceInfo` (current behavior: `identifiers={(DOMAIN, device_id)}`,
  name/manufacturer/model/serial from the device dict).
- `zone_id` set → side `DeviceInfo`: `identifiers={(DOMAIN, f"{device_id}_{zone_id}")}`,
  `via_device=(DOMAIN, device_id)`, `manufacturer="Orion Longevity"`,
  `name=f"Side {zone_label}"` where the label is "A"/"B" derived from the zone id
  (`zone_a`→"A", `zone_b`→"B", else the raw zone id).

`device_info` becomes:
```python
@property
def device_info(self) -> DeviceInfo:
    return build_device_info(self._get_device(), self._device_id, self._zone_id)
```

The zone entity classes already store a `zone_id`; they pass it up to
`super().__init__(coordinator, device_id, zone_id=zone_id)`. The classes that
become side-hosted: `OrionZoneClimateEntity` (climate.py), `OrionZoneInsightSensor`
+ `OrionCurrentTempOffsetSensor` (sensor.py), `OrionSessionActiveBinarySensor`
(binary_sensor.py). Every other entity is unchanged and stays on the hub.

### Pure helper (testable)

`build_device_info(device: dict, device_id: str, zone_id: str | None)` is a thin
wrapper, but the **identifier + via_device + name derivation** is the bug-prone
part. Extract a dependency-free helper for that piece so it can be unit-tested
without Home Assistant:

`util.side_device_descriptor(device_id, zone_id) -> dict` returning
`{"identifier": f"{device_id}_{zone_id}", "via": device_id, "name": "Side A"|"Side B"|f"Side {zone_id}"}`.
`build_device_info` (in entity.py, HA-coupled) consumes it. Unit tests cover the
zone_a/zone_b/other label mapping.

## Migration

On upgrade, HA re-homes the zone entities onto the two new sub-devices
automatically (entities are matched by unique_id, which is unchanged). The Hub
device retains its identity and history. No entity becomes unavailable. Device-
based dashboard cards re-arrange (entity-based cards are unaffected). Documented
in README.

## Error handling

Pure display/grouping change; no new I/O. `build_device_info` is defensive about a
missing device dict (falls back to sensible defaults, as today).

## Testing

- `util.side_device_descriptor` gets pytest unit tests (label mapping + identifier
  + via).
- HA-coupled `device_info` wiring is py_compile + manual: confirm three devices
  appear with Side A/B nested under the Hub, and each entity lands on the correct
  device.

## Documentation

Update `README.md` (note the Hub + Side A/B device layout and that sides can be
renamed in the UI) and `AGENTS.md` (device-structure note in the entity section).

## Out of scope

- Moving the live Sensor 1/2 entities onto the sides (blocked on verifying the
  sensor→side mapping).
- Any config-flow field for naming the sides (HA UI rename is sufficient).
- Splitting the schedule (shared per-user; stays on the Hub).
