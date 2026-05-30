# Per-Side Metrics + Diagnostics + Controls — Design

**Date:** 2026-05-30
**Target release:** 1.2.0
**Status:** Approved (pre-implementation)

## Goal

Three bundled enhancements to the Orion Sleep integration, shipped together as
1.2.0 but built and verified as three independent milestones:

- **A. Per-side sleep-insight metrics** — split the device-level insight sensors
  into per-zone (Zone A / Zone B) sensors, since each insights session is
  per-zone.
- **B. Tier A diagnostics** — surface device/network/firmware health already
  present in the live payload.
- **C. Tier B controls** — LED brightness and a reboot button.

## Background

The integration already streams a rich live payload (REST `GET /v1/devices/{serial}/live`
+ WebSocket `live_device.{snapshot,update}`) and polls `/v2/insights`. Today:

- Insight sensors (HRV, heart rate, breath rate, sleep stages, movement, restless
  time, current temp offset) are **device-level** — they call
  `coordinator.get_latest_session()`, which returns the most recent session of
  *either* zone. On a two-person bed you see only one side's numbers.
- Each insights session carries a `zone_id`, so the data is genuinely per-zone.
- The live payload exposes `status.firmware`, `status.network` (rssi, name/SSID,
  ip, mac, uptime, last_seen), `status.safety` (error, error_codes,
  error_descriptions), `status.zones[].thermal_state`, and `led_brightness` —
  none of which are surfaced.
- `api.py` has `device_action(device_id, action, value)` (POST
  `/v1/devices/{deviceId}/action`, path uses the device **UUID**) supporting
  `device_led_brightness` and `device_reboot`, but no entity uses them. These
  action calls are **unverified on-wire**.

Out of scope (deferred / impossible): Quiet Mode (dropped — no state read-back),
pairing/unpairing, firmware-update trigger, schedule enable/disable, zone
split/swap, guest management, start/stop session (no API).

## Decisions (from brainstorming)

1. Bundle A + B + C into one 1.2.0 release, structured as three milestones.
2. Per-side insight sensors **replace** the device-level ones (old ones retire →
   show unavailable until the user deletes them, same pattern as the per-zone
   climate change).
3. Schedule sensors **stay device-level** — the schedule is keyed by `user_id`
   and the account owns both zones, so there is a single shared schedule.
4. Diagnostics are **curated**: useful signals as entities; low-value details
   (IP, MAC, per-sensor firmware) as attributes; dead fields (`sign_of_asleep`,
   `water_fill`) skipped.
5. Naming uses **one translation key per metric** with a `{zone}` placeholder via
   `_attr_translation_placeholders`, not 22 hand-written strings.
6. `device_action` writes implemented optimistically; add `orion_info.py` probe
   flags so the user can verify on the live bed; update `openapi.yaml` +
   `AGENTS.md`.

## Milestone A — Per-side sleep-insight metrics

### Linchpin verification (do FIRST)
Before building entities, confirm with `python orion_info.py --insights-days 3`
that insights sessions carry `zone_id` values equal to the device zone ids
(`zone_a` / `zone_b`). If `zone_id` is a user-id or other value, **pause and
revisit the mapping** with the user rather than shipping a guess.

### Pure helper (testable)
Add to `util.py`:

```python
def latest_session_for_zone(insights_data: object, zone_id: str) -> dict | None:
    """Most recent insights session whose ``zone_id`` matches, or None.

    ``insights_data`` is the coordinator's ``data["insights"]["data"]`` mapping
    of ``{date_str: {"sessions": [...]}}``. Iterates dates newest-first and,
    within a date, returns the last matching session. Returns None when there is
    no matching session.
    """
```

Unit-tested in `tests/test_util.py`: match in newest date, fall back to older
date, no match → None, malformed/empty input → None, session without `zone_id`
ignored.

### Coordinator wrapper
`get_latest_session_for_zone(zone_id) -> dict | None` delegating to the helper
with `self.data["insights"].get("data")`.

### Sensors (per zone: `zone_a`, `zone_b`)
Refactor the session-based insight sensor classes to accept a `zone_id` and read
from `get_latest_session_for_zone(zone_id)` instead of `get_latest_session()`.
`async_setup_entry` iterates `device["zones"]` and creates one of each per zone.

Per-zone metrics (12): Total Sleep Time, Deep Sleep, REM Sleep, Light Sleep,
Awake Time, Heart Rate (avg), Breath Rate, HRV, Body Movement Rate, Restless
Time, Current Temp Offset, and the **Sleep Session Active** binary sensor
(`session.is_in_progress`).

- **unique_id:** `f"{device_id}_{key}_{zone_id}"`.
- **name:** translation key per metric (e.g. `heart_rate_avg`) whose translated
  name contains `{zone}`, with `_attr_translation_placeholders={"zone": "Zone A"}`
  (or "Zone B"). One key reused for both zones.

### Sleep Score
Verify whether a per-session score exists. If `data[date].sessions[]` carries a
score, make Sleep Score per-zone too; otherwise it **stays device-level** (reads
`insights.overview[latest].score`). Decision is made from live data during
implementation; default = device-level.

### Stays device-level (unchanged)
Schedule sensors (Bedtime, Wake-up Time, Schedule Duration, Bedtime Temp, Wake-up
Temp), WS Live Connection sensor, live per-sensor vitals (Sensor 1/2 HR/BR/status).

### Migration
Old device-level insight sensors (`{device_id}_{key}`) retire and show
unavailable until deleted from the entity registry. Documented in README.

## Milestone B — Tier A diagnostics

### Pure helpers (testable, in `live_state.py`)
Reading from a live-device dict:
- `firmware(live) -> dict | None` — `status.firmware` (`{cb, ib}`).
- `network_info(live) -> dict | None` — `status.network` (name/rssi/ip/mac/uptime/last_seen).
- `wifi_rssi(live) -> int | None` — `status.network.rssi`.
- `safety_error(live) -> bool | None` — True if `status.safety.error` truthy or
  `error_codes` non-empty; None if no safety block seen.
- `led_brightness(live) -> int | None` — top-level `led_brightness`.
- `zone_thermal_state(live, zone_id) -> str | None` — `status.zones[].thermal_state`.

Coordinator wrappers delegate as usual.

### Entities (device-level, diagnostic category)
- **Firmware Version** sensor — value = control-board fw (`cb`); attributes:
  interface-board fw (`ib`), per-sensor firmware/hardware versions.
- **Wi-Fi Signal** sensor — `device_class=signal_strength`, unit dBm, value =
  rssi; attributes: SSID (`name`), IP, MAC, uptime, last_seen.
- **Problem** binary sensor — `device_class=problem`, on when `safety_error` is
  True; attributes: error_codes, error_descriptions.

### Climate enhancement (no new entity)
Add `hvac_action` to `OrionZoneClimateEntity`: map `zone_thermal_state` →
`HVACAction.HEATING` (heating-ish), `HVACAction.IDLE` (`standby`), or
`HVACAction.OFF` when the zone is off. Only `"standby"` has been observed;
unknown values fall back to IDLE when on.

## Milestone C — Tier B controls

`device_action` uses the device **UUID**. Both writes are unverified on-wire.

- **LED Brightness** number — `min=0, max=100, step=1`; value from
  `led_brightness` (real read-back); set via
  `device_action(device_id, "device_led_brightness", value=int)`; then
  `async_request_refresh()`.
- **Reboot** button — new `button.py` platform (add `Platform.BUTTON` to
  `PLATFORMS`); press calls `device_action(device_id, "device_reboot")`.

### Verification tooling
Add `orion_info.py` flags `--led-brightness N` and `--reboot` to confirm the
action payloads against the live API. Update `openapi.yaml` (mark the two actions
verified once confirmed) and `AGENTS.md`.

## Error handling

- Reads degrade to `None` (entity shows unknown) via the defensive helpers.
- Write errors (LED, Reboot) propagate to the HA UI as failed-action
  notifications — existing convention (matches the Power switch / climate).

## Testing

- Pure helpers (`latest_session_for_zone`, `firmware`, `network_info`,
  `wifi_rssi`, `safety_error`, `led_brightness`, `zone_thermal_state`) get pytest
  unit tests — they import nothing from Home Assistant.
- HA-coupled entities/platforms verified by `python3 -m py_compile` and manual
  testing in a running HA instance.
- Manual verification: per-zone sensors show distinct values per side
  (cross-check `orion_info.py --insights-days 3`); diagnostics match the live
  payload; LED/Reboot actions confirmed via the new `orion_info.py` probes.

## Documentation

Update `README.md` (entity tables, per-zone insight section, migration note for
retired device-level sensors) and `AGENTS.md` (entity table, per-device count,
new helpers, verified action endpoints, Known Issues/Limitations).

## Out of scope

- Quiet Mode, pairing/unpairing, firmware-update trigger, schedule enable/disable,
  zone split/swap, guest management (Tier C / deferred).
- Reconciling the unverified Sensor 1/2 ↔ zone side mapping (the live per-sensor
  vitals are left as-is; per-zone insights use the explicit `zone_id`).
