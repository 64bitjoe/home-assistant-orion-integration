# Dual Per-Zone Climate Entities — Design

**Date:** 2026-05-29
**Status:** Approved (pre-implementation)

## Goal

Expose two climate entities per Orion device — one for each side/zone of the bed
(`zone_a`, `zone_b`) — so each side's temperature and power can be controlled
independently from Home Assistant.

## Background

Today the integration exposes a single device-level `OrionClimateEntity`
(`<device_id>_climate`). It is **schedule-driven**:

- `target_temperature` ← `today_sleep_schedule.bedtime_temp` (per-user schedule)
- `current_temperature` ← latest insights session `temperature.values[-1]`
- writes go through `api_client.set_temperature()` → `PUT /v1/sleep-configurations/temperature`, which is **unverified** against the live API
- `async_turn_off` / `async_set_hvac_mode(OFF)` are **no-ops**

This cannot represent two independent sides. The account owns **both zones**, and
the sleep schedule is keyed by a single `user_id`, so there is only one schedule —
it cannot hold two different per-side targets. Independent per-side control must
therefore come from the **live per-zone primitive**, which is verified and
real-time:

- `PUT /v1/devices/{serial_number}/live/zones/{zoneId}` — body `{on?, temp?}`
  (`update_live_device_zone(serial, zone_id, on=, temp=)`), **path uses
  `serial_number`, not the UUID**
- live setpoints stream at `live.zones[].{id, temp, on}`
- measured per-zone temps stream at `live.status.zones[].{id, temp, thermal_state}`
- both are fed by the WebSocket (`live_device.{snapshot,update}`) and backstopped
  by the REST `GET /v1/devices/{serial}/live` poll

## Decisions (from brainstorming)

1. **Bed setup:** one account owns both zones.
2. **Control source:** pure live per-zone (verified, real-time). No schedule
   dependence for the climate entities.
3. **Existing entity:** replace the single device-level climate entity with the
   two per-zone entities.
4. **Naming:** "Bed Climate Zone A" / "Bed Climate Zone B" (matches the API; the
   zone→physical-side mapping is unverified, so no Left/Right labels).
5. **set_temperature on an off zone** also turns the zone on (standard HA
   expectation).

## Design

### Entity structure (`climate.py`)

Replace `OrionClimateEntity` with `OrionZoneClimateEntity`. In
`async_setup_entry`, iterate over each device's `zones` list and create one entity
per zone:

```
for device in coordinator.devices:
    device_id = device.get("id")
    serial = device.get("serial_number")
    if not device_id or not serial:
        continue
    for zone in device.get("zones") or []:
        zone_id = zone.get("id")
        if not zone_id:
            continue
        entities.append(OrionZoneClimateEntity(coordinator, device_id, serial, zone_id, device))
```

If a device has no `zones`, it gets no climate entities (do not guess zone ids).

Each entity stores:
- `device_id` (UUID) — to read coordinator live state
- `serial_number` — for the live write endpoint (NOT the UUID)
- `zone_id` — e.g. `"zone_a"`

**unique_id:** `f"{device_id}_climate_{zone_id}"`.

**translation_key:** `bed_climate_zone_a` / `bed_climate_zone_b` (derived from
`zone_id`, e.g. `f"bed_climate_{zone_id}"`).

### Naming / translations

In `strings.json` and `translations/en.json` under `entity.climate`:
- add `bed_climate_zone_a` → "Bed Climate Zone A"
- add `bed_climate_zone_b` → "Bed Climate Zone B"
- remove the now-unused `bed_climate`, `bed_climate_left`, `bed_climate_right`

### New coordinator helpers (`coordinator.py`)

Add focused pure-dict readers next to `is_device_on`, each returning `None` when
the device/zone/field is absent so the entity shows `unknown` instead of guessing:

- `zone_setpoint(device_id, zone_id) -> float | None` — `live.zones[].temp` for the
  matching `id`
- `zone_is_on(device_id, zone_id) -> bool | None` — `live.zones[].on`
- `zone_measured_temp(device_id, zone_id) -> float | None` —
  `live.status.zones[].temp`

A small private helper `_live_zone(device_id, zone_id, *, measured=False)` may be
used to locate the zone dict in either `live["zones"]` or
`live["status"]["zones"]`.

### Entity behavior

| Member | Source / action |
|---|---|
| `current_temperature` | `coordinator.zone_measured_temp(device_id, zone_id)` |
| `target_temperature` | `coordinator.zone_setpoint(device_id, zone_id)` |
| `hvac_mode` | `HEAT_COOL` if `zone_is_on` is `True`, else `OFF` (incl. `None`) |
| `min_temp` / `max_temp` / step | from `temperature_range` (min 10, max 45), step 0.5 — unchanged |
| `async_set_temperature` | `update_live_device_zone(serial, zone_id, temp=t)`; if `zone_is_on` is not `True`, also pass `on=True`; then `async_request_refresh()` |
| `async_set_hvac_mode(mode)` | `update_live_device_zone(serial, zone_id, on=(mode == HEAT_COOL))`; refresh |
| `async_turn_on` / `async_turn_off` | `update_live_device_zone(serial, zone_id, on=True/False)`; refresh |

`_attr_hvac_modes = [HEAT_COOL, OFF]`, supported features
`TARGET_TEMPERATURE | TURN_ON | TURN_OFF`, unit Celsius — same as today.

### Interaction with existing entities

- **Power switch** (all-zones on/off) and **Number offset sliders**
  (schedule-based) are unchanged and independent. The Power switch reads "any zone
  on", which now correctly reflects per-zone climate toggles. No change needed.

### Error handling

Keep the existing convention: API write errors propagate to the HA UI as
failed-action notifications (same as the Power switch). Read failures already
degrade to `None` via the coordinator helpers. No special error swallowing.

## Migration / backwards compatibility

The old `<device_id>_climate` entity is retired. After the update it will appear
as `unavailable` in HA until the user deletes it from the entity registry.
Dashboard cards / automations referencing the old `entity_id` must be repointed to
the new per-zone entities. This is called out in the README.

## Verification (manual; no unit-test harness exists)

1. Two climate entities appear per device (`…_climate_zone_a`, `…_climate_zone_b`).
2. Each shows its own measured current temperature.
3. Setting a temperature on one zone changes only that zone — cross-check with
   `python orion_info.py --websocket` to watch the per-zone `live_device.update`
   frames.
4. On/off works per side and `hvac_mode` reflects each zone's `on` state.
5. Update `AGENTS.md` (entity table, per-device entity count, climate row) and the
   README climate section.

## Out of scope

- The separate `OrionCurrentTempOffsetSensor` double-registration bug in
  `sensor.py` (tracked in AGENTS.md Known Issues).
- Verifying the zone→physical-side (left/right) mapping.
- Schedule-based temperature writes.
