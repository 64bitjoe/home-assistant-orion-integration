# Orion Sleep - Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Custom [Home Assistant](https://www.home-assistant.io/) integration for the **Orion Sleep** smart mattress topper. Control bed temperature, react to occupancy in real time, monitor sleep metrics, and manage sleep schedules — all from your Home Assistant dashboard.

> **Fork:** This is a fork of [tdickman/home-assistant-orion-integration](https://github.com/tdickman/home-assistant-orion-integration), maintained at [64bitjoe/home-assistant-orion-integration](https://github.com/64bitjoe/home-assistant-orion-integration). It adds independent per-zone climate control (one climate entity per side of the bed).

## Features

- **Live WebSocket stream** — Temperature, power, and sensor readings update in realtime when the bed or the Orion app changes anything; no need to wait for the next poll.
- **Bed occupancy** — Per-topper-sensor binary sensors track who is on the bed. Latency varies; expect ~30 s to 1 minute after sitting down or leaving before the sensor flips (the topper itself is slow to decide).
- **Live heart rate and breath rate** — Per-sensor realtime readings from the topper (distinct from the post-session averages).
- **Per-zone climate control** — One climate entity per side of the bed (Zone A / Zone B). Each side's target and current temperature, and on/off, are controlled independently in real time via the live per-zone endpoint, and each reports an HVAC action (heating / idle / off).
- **Power and presence switches** — One-click power via the canonical `/v1/devices/{serial}/live` endpoint, plus an Away Mode switch that reads the authoritative presence signal from `zones[*].user`.
- **Per-zone sleep insight sensors** — HRV, heart rate, breath rate, sleep-stage durations (awake / light / deep / REM), total time asleep, restless time, body-movement rate, and current temperature offset for each zone's most recent session, plus a device-level Sleep Score.
- **Schedule sensors and sliders** — Today's bedtime, wake-up time, duration, and target temperatures, plus Number sliders for adjusting the four schedule-phase temperature offsets (-10 … +10, app-style).
- **Device controls** — LED Brightness number and a Reboot button (both via the `device_action` endpoint, currently unverified on-wire).
- **Session tracking** — Per-zone binary sensor showing whether a sleep session is currently in progress.
- **Diagnostic entities** — Live-connection state sensor (`connecting` / `connected` / `reconnecting` / `device_offline` / `auth_failed`, with seconds-since-last-frame as an attribute), plus Firmware Version, Wi-Fi Signal, and a Problem binary sensor.
- **Passwordless auth with automatic refresh** — Sign in with the same email or phone + verification code flow as the Orion app. Tokens are refreshed automatically; you are prompted to re-authenticate only if the refresh token itself is revoked.
- **Redacted diagnostics** — `Download diagnostics` produces a debug bundle with tokens, identifiers, and network PII stripped.

## Installation

### HACS (Recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance.

2. Click the button below to add this repository:

   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=64bitjoe&repository=home-assistant-orion-integration&category=integration)

   Or manually add the custom repository: go to **HACS > Integrations > three-dot menu > Custom repositories**, paste `https://github.com/64bitjoe/home-assistant-orion-integration` and select **Integration** as the category.

3. Search for "Orion Sleep" in HACS and download it.

4. Restart Home Assistant.

### Manual

1. Copy the `custom_components/orion_sleep` directory into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

## Configuration

After installation, add the integration:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=orion_sleep)

Or go to **Settings > Devices & Services > Add Integration** and search for "Orion Sleep".

### Setup steps

1. Choose whether to sign in with **email** or **phone**.
2. Enter your Orion Sleep account email or phone number. A verification code is sent the same way as it is for the Orion app.
3. Enter the verification code to complete setup.

### Options

After setup, you can configure:

| Option | Default | Description |
|---|---|---|
| Polling interval | 600 s (10 min) | How often to fetch data from the Orion REST API (60 – 3600 s). The WebSocket stream runs continuously and is independent of this interval. |
| Insights days | 7 | Number of days of sleep history to retrieve (1 – 30) |

Go to **Settings > Devices & Services > Orion Sleep > Configure** to change these.

## Real-time updates

In addition to the REST poll, the integration opens one WebSocket per device to `wss://live.api1.orionbed.com/device/<serial_number>` and merges every `live_device.snapshot` / `live_device.update` frame into the coordinator state. This means:

- The Power switch and Bed Climate reflect app-side changes in realtime.
- Per-sensor vitals (heart rate, breath rate) update continuously while occupied.
- Occupancy binary sensors follow the topper's own classification, which can take ~30 s to 1 minute to decide someone has sat down or left. The underlying vitals still update in realtime.
- The integration will gracefully reconnect with exponential backoff if the stream drops, and automatically refresh the JWT before reconnecting on 401.

The live connection is fully automatic — there is no option to disable it today. Its health is exposed by the **Live Connection** diagnostic sensor per device.

## Entities

Each paired topper is represented as three Home Assistant devices: an **Orion Hub** (whole-bed controls, schedule, diagnostics, and the live per-sensor readings) with two sub-devices, **Side A** and **Side B**, nested under it. Each Side holds that side's climate plus its per-session sleep metrics (HRV, heart rate, sleep stages, etc.). The Side names default to "Side A" / "Side B" — rename them in the HA UI (Settings > Devices & Services > device > rename) if you like. Entity names below use the integration's default translation strings.

### Upgrading to 1.2.0

The sleep-insight sensors are now **per zone**. The old device-level insight sensors (HRV, Heart Rate, Total Sleep Time, the sleep-stage durations, Body Movement Rate, Restless Time), the single Sleep Session binary sensor, and the single Current Temperature Offset sensor are **replaced** by per-zone versions (Zone A / Zone B). The retired entities will show as **unavailable** until you delete them from the entity registry (Settings > Devices & Services > Entities). Update any dashboards and automations to point at the new per-zone entities (their unique IDs carry a `_zone_a` / `_zone_b` suffix). Sleep Score and the schedule sensors stay device-level and are unaffected.

### Climate

One climate entity per bed zone. Each side is controlled independently via the live per-zone endpoint.

| Entity | Description |
|---|---|
| Bed Climate Zone A | Target = live setpoint for zone A; current = measured zone-A temperature; HVAC mode reflects whether the zone is on. Also reports an HVAC action (heating / idle / off) derived from the zone's `thermal_state`. Turning it on/off and setting a temperature take effect immediately. |
| Bed Climate Zone B | Same as Zone A, for the other zone. |

The zone → physical side (left/right) mapping is unverified, so entities are named by zone. Rename them in the HA UI if you confirm which side is which.

### Switches

| Entity | Description |
|---|---|
| Power | All zones on/off via `PUT /v1/devices/{serial}/live`. State derived from each zone's `on` field. |
| Away Mode | Marks you present/away via `POST /v1/sleep-configurations/user-away`. State derived from whether any zone carries a populated `user` object (the authoritative presence signal). |
| Sleep Schedule | Enable/disable today's bedtime action via `PUT /v1/sleep-schedules`. |

### Numbers (temperature-offset sliders)

App-style offsets (-10 to +10) that map non-linearly to Celsius using the device's `temperature_scale.relative` lookup table. Each slider writes back to today's schedule.

- Bedtime Temperature Offset
- Asleep Phase 1 Offset
- Asleep Phase 2 Offset
- Wake Up Temperature Offset

In addition to the schedule offsets:

- **LED Brightness** (0–100) — reads the live `led_brightness` state and writes via the `POST /v1/devices/{id}/action` (`device_led_brightness`) endpoint. This write path is **unverified on-wire** (the action endpoint is documented but the LED write has not been confirmed against a live device).

### Buttons

- **Reboot** — reboots the device via `POST /v1/devices/{id}/action` (`device_reboot`). This write path is **unverified on-wire** (pending live confirmation).

### Sensors — sleep insights (per zone — latest completed session)

These metrics are now reported **per zone (Zone A / Zone B)** — one entity per metric per side, named with a " Zone A" / " Zone B" suffix and sourced from each zone's latest completed session. **Sleep Score** remains device-level (a whole-bed daily score). The old device-level versions of these sensors are retired — see [Upgrading to 1.2.0](#upgrading-to-120).

| Entity | Unit | Source |
|---|---|---|
| Sleep Score | points | **Device-level.** `insights.overview[latest].score` with a `quality_rating` attribute (Excellent / Good / Fair / Poor) |
| Total Sleep Time (Zone A / Zone B) | formatted `Xh Ym` | `sleep_summary.time_asleep` |
| Deep Sleep (Zone A / Zone B) | formatted `Xh Ym` | `sleep_summary.deep_sleep` |
| REM Sleep (Zone A / Zone B) | formatted `Xh Ym` | `sleep_summary.rem_sleep` |
| Light Sleep (Zone A / Zone B) | formatted `Xh Ym` | `sleep_summary.light_sleep` |
| Awake Time (Zone A / Zone B) | formatted `Xh Ym` | `sleep_summary.awake_time` |
| Heart Rate (Zone A / Zone B) | bpm | `heart_rate.average` plus `min` / `max` / `range` attributes |
| Breath Rate (Zone A / Zone B) | breaths/min | `breath_rate.average` plus `min` / `max` / `range` attributes |
| HRV (Zone A / Zone B) | ms | `hrv.average` plus `min` / `max` attributes (often null in real data) |
| Body Movement Rate (Zone A / Zone B) | /hr | `movement.movement_rate` |
| Restless Time (Zone A / Zone B) | formatted `Xm Ys` | `movement.total_seconds` |
| Current Temperature Offset (Zone A / Zone B) | app-style -10 … +10 | Latest session temperature sample for the zone, converted via the per-device non-linear lookup table |

### Sensors — today's schedule

- Bedtime (HH:mm)
- Wake Up Time (HH:mm)
- Schedule Duration (formatted, handles overnight)
- Bedtime Temperature (°C) with phase-1 / phase-2 temp and smart-temperature attributes
- Wake Up Temperature (°C)

These schedule sensors remain device-level (one shared per-user schedule).

### Sensors — live (WebSocket-driven)

Two in-topper sensors (`sensor1`, `sensor2`) report continuously while the device is online. The mapping between these and the physical left / right side of the bed has not been verified, so entities are named per sensor.

| Entity | Unit | Source |
|---|---|---|
| Sensor 1 Heart Rate | bpm | `status.sensors.sensor1.heart_rate` |
| Sensor 2 Heart Rate | bpm | `status.sensors.sensor2.heart_rate` |
| Sensor 1 Breath Rate | br/min | `status.sensors.sensor1.breath_rate` |
| Sensor 2 Breath Rate | br/min | `status.sensors.sensor2.breath_rate` |

The raw `status_text`, `is_working`, `firmware_version`, and `hardware_version` from each sensor are exposed as extra state attributes on the heart-rate and breath-rate entities. A reading of `0` (empty bed) or `255` (no reading yet) is reported as `unknown` — both are server-side sentinels, not real vitals.

### Sensors — diagnostic

| Entity | Source |
|---|---|
| Live Connection | WebSocket state: `stopped` / `connecting` / `connected` / `reconnecting` / `device_offline` / `auth_failed`, with `seconds_since_last_message` as an attribute. |
| Firmware Version | Interface-board firmware version, with per-sensor firmware/hardware versions exposed as attributes. |
| Wi-Fi Signal | Wi-Fi signal strength in dBm, with `ssid` / IP / MAC / uptime / last-seen exposed as attributes. |
| Sensor 1 Status | Raw `status_text` from topper sensor 1 (observed values: `left_bed`, `normal`). |
| Sensor 2 Status | Raw `status_text` from topper sensor 2. |

### Binary sensors

| Entity | Device class | Description |
|---|---|---|
| Sleep Session Zone A / Zone B | — | Per-zone `session.is_in_progress`. Rendered as "Asleep" / "Not asleep". |
| Sensor 1 On Bed | Occupancy | `sensor1.status_text != "left_bed"`. Driven by the topper's own classification, which can take ~30 s to 1 minute to react to someone sitting down or leaving. |
| Sensor 2 On Bed | Occupancy | `sensor2.status_text != "left_bed"`. Same latency caveat as sensor 1. |
| Problem | Problem | Device safety/error state from `status.safety.error`, with error codes / descriptions exposed as attributes. |

## Troubleshooting

- **Re-authentication** — If both the access and refresh tokens expire or are revoked, Home Assistant will raise a re-auth flow; follow the prompts to receive and enter a new verification code.
- **Away Mode switch** — If you toggle Away Mode and the Orion app shows you in Home mode (or vice-versa), the device was probably in an already-matching state. The integration swallows the specific `400 "User has no previous device to return to"` error that the server returns on a redundant toggle and simply logs it at `debug`.
- **Live Connection stuck on `reconnecting`** — Typically indicates a network problem reaching `live.api1.orionbed.com`. The client falls back to REST polling so the rest of the integration keeps working; restart HA or check your outbound HTTPS / WSS connectivity.
- **Logs** — Go to **Settings > System > Logs** and filter for `orion_sleep`. For more detail, add this to `configuration.yaml`:

  ```yaml
  logger:
    default: warning
    logs:
      custom_components.orion_sleep: debug
  ```

- **Diagnostics** — Use **Settings > Devices & Services > Orion Sleep > three-dot menu > Download diagnostics** to generate a debug bundle. Access tokens, refresh tokens, user identifiers, names, serial numbers, IP and MAC addresses are automatically redacted.

## Notes and limitations

- Climate entities are per-zone and use the verified live endpoint `PUT /v1/devices/{serial}/live/zones/{zoneId}`. Turning a zone on/off and setting its temperature take effect immediately and independently per side. The **Power** switch still controls all zones at once.
- The Number temperature-offset sliders remain schedule-driven (`PUT /v1/sleep-schedules`); they adjust the schedule, while the climate entities set the live runtime setpoint.
- The LED Brightness number and Reboot button write via the `POST /v1/devices/{id}/action` endpoint (`device_led_brightness` / `device_reboot`). These actions are **unverified on-wire** — they are wired up but have not yet been confirmed against a live device.
- HRV values are frequently `null` in real data; the HRV sensor will then report as `unknown`.
- Starting and stopping sleep sessions is not supported by the API.
- Zone splitting / merging and guest-user management are not exposed.

## License

This project is not affiliated with or endorsed by Orion Longevity Inc.
