# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A HACS-compatible Home Assistant custom integration (`custom_components/orion_sleep`) for the Orion Sleep smart mattress topper. It talks to a cloud REST API (`https://api1.orionbed.com`) for polled data and one WebSocket per device (`wss://live.api1.orionbed.com/device/<serial_number>`) for live state. There is no local/LAN path — `iot_class` is `cloud_polling`.

## Read AGENTS.md first

`AGENTS.md` is the detailed, authoritative reference: full REST endpoint table (working / non-working / unverified), real response shapes, the WebSocket event taxonomy and payload shape, the per-entity data-source map, API client method inventory, and the current Known Issues / Limitations list. Consult it before changing API calls or entity behavior, and **keep it updated** when you change those things. Don't duplicate its tables here.

## Commands

There is a small `pytest` suite covering the dependency-free helper modules (`custom_components/orion_sleep/live_state.py`, `util.py`) — run it with `python3 -m pytest tests/ -q`. These modules import nothing from Home Assistant (which isn't installed locally), so they're the only unit-testable surface; the HA-coupled code is verified by `py_compile` and manual testing. There is no linter config or build step.

The rest of verification is done against a live account using the CLI tool:

```bash
python orion_info.py --email user@example.com   # or --phone 15132015808
python orion_info.py --relogin                  # force fresh auth (tokens cache to ~/.orion_tokens.json)
python orion_info.py --websocket --ws-duration 60   # log raw WS frames
python orion_info.py --ws-scenario              # drive scripted REST edits while logging WS frames
```

`orion_info.py` and `openapi.yaml` are dual source-of-truth for the (reverse-engineered) API. When you discover or change API behavior, update **both** of them and the relevant tables in `AGENTS.md`. When the two disagree, re-verify against the live server rather than trusting one.

To run the integration itself, copy `custom_components/orion_sleep` into a Home Assistant `config/custom_components/` directory and restart HA. Only stdlib + HA-bundled deps are used (`aiohttp`); `manifest.json` lists no extra `requirements`.

## Architecture

`OrionDataUpdateCoordinator` (`coordinator.py`) is the hub. Every platform entity reads from it; it is the only thing that talks to `OrionApiClient` (`api.py`) and `OrionWebSocketManager` (`websocket.py`).

- **One-time setup** (`_async_setup`): fetch user profile + device list.
- **Poll loop** (`_async_update_data`, default 600s): refresh token if needed → list devices (drives away/present state) → sync WS connections to current serials → fetch live device snapshot per device (skipped if a fresh WS frame already exists) → fetch sleep schedules → fetch insights. **Each polled endpoint has its own try/except** so one failure doesn't blank the others.
- **Live path**: each device's WebSocket pushes `live_device.snapshot` then `live_device.update` frames. `_handle_ws_message` merges the payload into `live_devices` and calls `async_set_updated_data()` so entities refresh immediately, independent of the poll interval.
- **Auth**: three-step config flow (method → email/phone → verification code) in `config_flow.py`, plus re-auth. `OrionAuthError` from any call raises `ConfigEntryAuthFailed` to trigger the re-auth flow. A token-refresh callback writes refreshed tokens back into `config_entry.data` so they survive restarts.

Entities subclass `OrionBaseEntity` (`entity.py`), which supplies `DeviceInfo` and the `_celsius_to_offset()` / `_offset_to_celsius()` helpers. Platforms: `climate.py`, `sensor.py`, `binary_sensor.py`, `switch.py`, `number.py`, `diagnostics.py`.

## Gotchas worth front-loading

These bite repeatedly; the full list is in AGENTS.md:

- Live device endpoints (`/v1/devices/{...}/live[...]`) take the device **`serial_number`**, NOT the UUID `id` (UUID returns 403/404). The WS path also uses `serial_number`.
- The canonical power primitive is `PUT /v1/devices/{serial}/live` (zones with `on`/`temp`). `device_action` has no power action. `set_user_away` is a separate *presence* override, not power.
- Temperatures are **Celsius** everywhere. App-style offsets (-10…+10) map **non-linearly** to Celsius via the per-device `temperature_scale.relative` lookup table.
- Token fields are snake_case (`access_token`); expiry uses the `expires_at` Unix timestamp, not JWT parsing. The refresh response may be nested (`response.session`) or flat — handle both.
- Most endpoints wrap data in `{"response": {...}, "success": true}`; `/v2/insights` does **not** wrap.
- WebSocket: Cloudflare defaults to HTTP/2 which breaks the upgrade — the SSL context must force ALPN to `http/1.1`. User-Agent `okhttp/4.12.0` works.
- Sensor vitals `0` (empty bed) and `255` (no reading yet) are server sentinels mapped to `unknown`, not real readings.
