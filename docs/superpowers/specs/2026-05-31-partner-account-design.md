# Partner Account (per-side stats) — Design

**Date:** 2026-05-31
**Target release:** 1.4.0
**Status:** Approved (pre-implementation)

## Goal

Let the integration also surface the **partner's** per-side sleep metrics. Orion's
insights/schedule data is scoped to the authenticated user, so a single login
(the primary, e.g. Joe) only ever receives its own sessions — which populate its
zone (Side A). The partner (e.g. Cody) has a **separate Orion account**, so their
sleep data is unreachable from the primary login and their side (Side B) stays
"Unknown" forever.

This feature lets the user **link a second ("partner") account** whose tokens are
used **only** to fetch that account's insights, routed to the partner's zone. All
device control stays on the primary account.

## Background

- Auth (`config_flow.py`): pick email/phone → `request_auth_code` → enter code →
  `verify_auth_code` returns `{access_token, refresh_token, expires_at}`. Primary
  tokens live in `entry.data` (`CONF_ACCESS_TOKEN` etc.). `OrionApiClient`
  auto-refreshes and persists via a `set_token_refresh_callback`.
- The coordinator polls `/v2/insights` for the authenticated user and stores it at
  `data["insights"]`. `get_latest_session_for_zone(zone_id)` →
  `util.latest_session_for_zone(data["insights"]["data"], zone_id)`.
- Per-zone insight sensors (Side A/B) read from that. Live climate/WS data is
  device-scoped (not user-scoped), which is why both sides' *climate* already
  works.
- The config-entry update listener only reloads on **options** changes (fixed in
  1.1.1), so persisting a partner token to `entry.data` will NOT spuriously reload.

## Decisions (from brainstorming)

1. **One partner** only (a bed has two zones; primary + one partner covers it).
2. Partner tokens used **only** for insights; **all control stays on the primary**.
3. Link/remove the partner via the **Options flow** ("Configure").
4. Partner auth failure → **silent degrade** (partner sensors go "unknown") + a
   **repair issue** prompting re-link; never drag the primary into reauth.
5. **Sleep Score** stays device-level/primary (whole-bed aggregate); the partner
   gets the per-zone metrics only.

## Design

### Linking (Options flow)

Turn the single options step into a menu (`async_step_init` → `async_show_menu`):
- **Settings** — the existing `scan_interval` + `insights_days` form.
- **Link partner account** — reuses the auth steps (method → send code → verify),
  then stores the partner block and reloads the entry.
- **Remove partner account** — clears the partner block and reloads (shown only
  when a partner is linked).

The link sub-flow mirrors `OrionSleepConfigFlow`'s email/phone/verify steps
(factor the shared send-code/verify logic so it isn't copy-pasted). On successful
verify it calls:
```python
self.hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_PARTNER: {...}})
await self.hass.config_entries.async_reload(entry.entry_id)
```

**Partner block** stored at `entry.data[CONF_PARTNER]` (new const `CONF_PARTNER = "partner"`):
```python
{"auth_method": ..., "auth_value": ..., "access_token": ...,
 "refresh_token": ..., "expires_at": ...}
```

### Coordinator

- In `__init__`, if `entry.data.get(CONF_PARTNER)` exists, build a second
  `OrionApiClient` (`self._partner_client`) seeded from the partner block, with its
  own refresh callback that persists back to `entry.data[CONF_PARTNER]` (via
  `async_update_entry`, merging into existing data). If no partner block,
  `self._partner_client = None`.
- In `_async_update_data`, after fetching primary insights, if a partner client
  exists, fetch the partner's insights **best-effort** into `data["insights_partner"]`:
  - On `OrionAuthError`: set `data["insights_partner"] = {}`, create the repair
    issue (`partner_reauth`), log a warning. **Do not raise** — the primary poll
    must succeed.
  - On other API/connection errors: keep the previous partner insights, log
    warning.
  - On success: store insights and **delete** the repair issue if present.
- `get_latest_session_for_zone(zone_id)`: search primary
  `data["insights"]["data"]` first; if no match, search
  `data["insights_partner"]["data"]`. (Each account returns only its own zone's
  sessions, so there is no overlap; primary wins if there ever were.)

Repair issue uses `homeassistant.helpers.issue_registry`
(`async_create_issue`/`async_delete_issue`, issue_id `partner_reauth`,
severity ERROR, translation key for the message).

### Entities

No entity changes. The existing per-zone insight + session-active sensors for the
partner's zone simply start returning values once partner insights flow in. Side
device naming/structure (1.3.0) is unchanged.

## Error handling

- Partner insights are always best-effort; a partner failure never breaks the
  primary poll or control.
- Partner token refresh persists to `entry.data[CONF_PARTNER]`; failure → repair
  issue + degrade, not entry-wide reauth.
- Removing the partner deletes the client, clears `data["insights_partner"]`, and
  deletes any open repair issue.

## Testing

- **Pure/unit:** `util.latest_session_for_zone` already covers per-zone lookup. Add
  a tiny pure helper or test confirming the coordinator's "primary then partner"
  fallback selects the right session given two insights blocks (test the helper
  composition with fake primary/partner data — no HA needed).
- **HA-coupled (py_compile + manual):** options menu link/remove; second client
  construction + refresh persistence; repair issue create/delete; verify the
  partner's side populates while control stays on primary.
- **Manual acceptance:** link Cody's account → after Cody's next processed
  session, Side B insight sensors populate; unlink → Side B returns to unknown and
  no errors.

## Documentation

`README.md`: a "Two sleepers / partner account" subsection under Configuration —
how to link a partner via Configure, that it's stats-only, and that control stays
on the primary. `AGENTS.md`: note the optional partner client, `CONF_PARTNER`
data block, `insights_partner`, and the `get_latest_session_for_zone` dual-source
lookup.

## Out of scope

- More than one partner.
- Partner *control* (climate/switches/schedule) — primary only, by design.
- A separate partner Sleep Score (device-level aggregate stays primary).
- Partner schedule sensors / partner-specific number sliders.
