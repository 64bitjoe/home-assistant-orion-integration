# Partner Account Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user link a second ("partner") Orion account whose tokens are used only to fetch that account's insights, so the partner's side (e.g. Side B) populates — while all control stays on the primary account.

**Architecture:** A `CONF_PARTNER` block in `entry.data` holds the partner's tokens. The coordinator builds an optional second `OrionApiClient` used solely for `get_insights`, stored at `data["insights_partner"]`; `get_latest_session_for_zone` searches primary then partner. The Options flow gains link/remove steps reusing the existing code-login. Partner auth failures degrade quietly and raise a repair issue.

**Tech Stack:** Python 3, Home Assistant custom integration (config/options flow, issue_registry), aiohttp, pytest (only pytest installed locally; HA-coupled code verified via py_compile + manual).

---

## File Structure
- `const.py` — add `CONF_PARTNER`.
- `coordinator.py` — optional partner `OrionApiClient`, partner insights fetch (best-effort + repair issue), dual-source `get_latest_session_for_zone`.
- `config_flow.py` — Options flow menu + partner link/remove steps.
- `strings.json` + `translations/en.json` — options menu/steps + repair issue text.
- `README.md`, `AGENTS.md`, `manifest.json` — docs + version 1.4.0.

---

## Task 1: Add `CONF_PARTNER` constant

**Files:** Modify `custom_components/orion_sleep/const.py`

- [ ] **Step 1: Add the constant**

In `const.py`, after the line `CONF_EXPIRES_AT = "expires_at"  # Unix timestamp`, add:

```python
CONF_PARTNER = "partner"  # nested dict of a linked partner account's tokens
```

- [ ] **Step 2: Verify compile**

Run: `python3 -m py_compile custom_components/orion_sleep/const.py`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add custom_components/orion_sleep/const.py
git commit -m "Add CONF_PARTNER constant"
```

---

## Task 2: Coordinator — partner insights client + dual-source lookup

**Files:** Modify `custom_components/orion_sleep/coordinator.py`

No automated test (requires HA). The per-zone lookup itself is already covered by `tests/test_util.py`; this task wires the second source + best-effort fetch + repair issue.

- [ ] **Step 1: Extend imports**

In `coordinator.py`, the existing const import is:
```python
from .const import (
    CONF_INSIGHTS_DAYS,
    CONF_SCAN_INTERVAL,
    DEFAULT_INSIGHTS_DAYS,
    DEFAULT_SCAN_INTERVAL,
)
```
Replace it with:
```python
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_INSIGHTS_DAYS,
    CONF_PARTNER,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_INSIGHTS_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
```
Also add, with the other `homeassistant.helpers` imports near the top:
```python
from homeassistant.helpers import issue_registry as ir
```

- [ ] **Step 2: Build the optional partner client in `__init__`**

In `OrionDataUpdateCoordinator.__init__`, immediately after `self.api_client = api_client`, add:

```python
        # Optional second client for a linked partner account. Used ONLY to
        # fetch that account's insights (the partner's per-side sleep stats);
        # never for control. None when no partner is linked.
        self._partner_client: OrionApiClient | None = None
        partner = config_entry.data.get(CONF_PARTNER)
        if partner:
            self._partner_client = self._build_partner_client(partner)
```

- [ ] **Step 3: Add the partner-client builder + refresh callback**

Add these methods to the coordinator (place them right before `get_latest_session`):

```python
    def _build_partner_client(self, partner: dict) -> OrionApiClient:
        """Create the partner insights client from a stored partner block."""
        client = OrionApiClient(
            session=async_get_clientsession(self.hass),
            access_token=partner.get(CONF_ACCESS_TOKEN),
            refresh_token=partner.get(CONF_REFRESH_TOKEN),
            expires_at=partner.get(CONF_EXPIRES_AT, 0),
        )
        client.set_token_refresh_callback(self._on_partner_token_refresh)
        return client

    @callback
    def _on_partner_token_refresh(
        self, access_token: str, refresh_token: str, expires_at: float
    ) -> None:
        """Persist refreshed partner tokens back into entry.data[CONF_PARTNER]."""
        entry = self.config_entry
        partner = dict(entry.data.get(CONF_PARTNER) or {})
        partner.update(
            {
                CONF_ACCESS_TOKEN: access_token,
                CONF_REFRESH_TOKEN: refresh_token,
                CONF_EXPIRES_AT: expires_at,
            }
        )
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_PARTNER: partner}
        )
```

(`callback` and `async_get_clientsession` are already imported in coordinator.py.)

- [ ] **Step 4: Fetch partner insights best-effort in `_async_update_data`**

Find the primary insights fetch block (the `try:` that sets
`data["insights"] = await self.api_client.get_insights(days=insights_days)`).
Immediately AFTER that whole try/except, add:

```python
        # Partner insights — best-effort, never breaks the primary poll.
        if self._partner_client is not None:
            try:
                await self._partner_client.ensure_valid_token()
                data["insights_partner"] = await self._partner_client.get_insights(
                    days=insights_days
                )
                ir.async_delete_issue(self.hass, DOMAIN, "partner_reauth")
            except OrionAuthError:
                data["insights_partner"] = {}
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    "partner_reauth",
                    is_fixable=False,
                    severity=ir.IssueSeverity.ERROR,
                    translation_key="partner_reauth",
                )
                _LOGGER.warning(
                    "Orion partner account auth failed; re-link it from the "
                    "integration's Configure menu"
                )
            except (OrionApiError, OrionConnectionError) as err:
                _LOGGER.warning("Failed to fetch partner insights: %s", err)
                # Preserve prior partner insights rather than blanking them.
                data["insights_partner"] = (self.data or {}).get(
                    "insights_partner", {}
                )
```

Note: `insights_days` is the local already computed in the primary insights block
(`insights_days = self.config_entry.options.get(CONF_INSIGHTS_DAYS, DEFAULT_INSIGHTS_DAYS)`).
If that local is scoped inside the primary `try`, hoist its assignment to just
before the primary insights `try:` so both blocks can use it.

- [ ] **Step 5: Make `get_latest_session_for_zone` search both sources**

Replace the existing method:

```python
    def get_latest_session_for_zone(self, zone_id: str) -> dict | None:
        """Most recent insights session for one zone, or None."""
        insights = (self.data or {}).get("insights", {})
        return util.latest_session_for_zone(insights.get("data"), zone_id)
```

with:

```python
    def get_latest_session_for_zone(self, zone_id: str) -> dict | None:
        """Most recent insights session for one zone (primary, then partner)."""
        data = self.data or {}
        primary = (data.get("insights") or {}).get("data")
        session = util.latest_session_for_zone(primary, zone_id)
        if session is not None:
            return session
        partner = (data.get("insights_partner") or {}).get("data")
        return util.latest_session_for_zone(partner, zone_id)
```

- [ ] **Step 6: Verify compile**

Run: `python3 -m py_compile custom_components/orion_sleep/coordinator.py`
Expected: exit 0.
Run: `python3 -m pytest tests/ -q`
Expected: all pass (pure helpers unchanged).

- [ ] **Step 7: Commit**

```bash
git add custom_components/orion_sleep/coordinator.py
git commit -m "Fetch partner-account insights and route per-zone lookups to them"
```

---

## Task 3: Options flow — link / remove partner

**Files:** Modify `custom_components/orion_sleep/config_flow.py`

Rework `OrionSleepOptionsFlow` into a menu: settings, link partner, remove partner.
The link steps reuse the same `OrionApiClient` auth calls the config flow uses.

- [ ] **Step 1: Extend imports**

In `config_flow.py`, the const import currently ends at `DOMAIN,`. Add
`CONF_PARTNER` to it:
```python
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_AUTH_METHOD,
    CONF_AUTH_VALUE,
    CONF_EXPIRES_AT,
    CONF_INSIGHTS_DAYS,
    CONF_PARTNER,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_INSIGHTS_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
```
(Keep whatever subset already imported; ensure `CONF_PARTNER` and the token/auth
consts are present — they already are for the config flow.)

- [ ] **Step 2: Replace the whole `OrionSleepOptionsFlow` class**

Replace the entire `OrionSleepOptionsFlow` class with:

```python
class OrionSleepOptionsFlow(OptionsFlow):
    """Options flow: settings + link/remove a partner account."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self._p_method: str | None = None
        self._p_value: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Top-level menu."""
        options = ["settings", "link_partner"]
        if self._config_entry.data.get(CONF_PARTNER):
            options.append("remove_partner")
        return self.async_show_menu(step_id="init", menu_options=options)

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit poll interval + insights days (the original options form)."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        current_insights_days = self._config_entry.options.get(
            CONF_INSIGHTS_DAYS, DEFAULT_INSIGHTS_DAYS
        )
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                        vol.Coerce(int), vol.Range(min=60, max=3600)
                    ),
                    vol.Required(
                        CONF_INSIGHTS_DAYS, default=current_insights_days
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
                }
            ),
        )

    async def async_step_link_partner(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the partner's login method."""
        if user_input is not None:
            self._p_method = user_input[CONF_AUTH_METHOD]
            if self._p_method == AUTH_METHOD_EMAIL:
                return await self.async_step_partner_email()
            return await self.async_step_partner_phone()
        return self.async_show_form(
            step_id="link_partner",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTH_METHOD, default=AUTH_METHOD_EMAIL): vol.In(
                        {AUTH_METHOD_EMAIL: "Email", AUTH_METHOD_PHONE: "Phone"}
                    )
                }
            ),
        )

    async def _partner_send_code(self, value: str) -> None:
        """Send a verification code to the partner account."""
        self._p_value = value.strip()
        client = OrionApiClient(session=async_get_clientsession(self.hass))
        email = self._p_value if self._p_method == AUTH_METHOD_EMAIL else None
        phone = self._p_value if self._p_method == AUTH_METHOD_PHONE else None
        success = await client.request_auth_code(email=email, phone=phone)
        if not success:
            raise OrionConnectionError("API returned success=false")

    async def async_step_partner_email(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._partner_send_code(user_input["email"])
                return await self.async_step_partner_verify()
            except OrionConnectionError:
                errors["base"] = "cannot_connect"
            except OrionApiError:
                errors["base"] = "unknown"
        return self.async_show_form(
            step_id="partner_email",
            data_schema=vol.Schema({vol.Required("email"): str}),
            errors=errors,
        )

    async def async_step_partner_phone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        phone_default = ""
        if user_input is not None:
            raw = user_input.get("phone", "")
            phone_default = raw
            phone = _normalize_phone(raw)
            if not _PHONE_RE.match(phone):
                errors["base"] = "invalid_phone"
            else:
                try:
                    await self._partner_send_code(phone)
                    return await self.async_step_partner_verify()
                except OrionConnectionError:
                    errors["base"] = "cannot_connect"
                except OrionApiError:
                    errors["base"] = "unknown"
        return self.async_show_form(
            step_id="partner_phone",
            data_schema=vol.Schema({vol.Required("phone", default=phone_default): str}),
            errors=errors,
        )

    async def async_step_partner_verify(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = OrionApiClient(session=async_get_clientsession(self.hass))
            email = self._p_value if self._p_method == AUTH_METHOD_EMAIL else None
            phone = self._p_value if self._p_method == AUTH_METHOD_PHONE else None
            try:
                tokens = await client.verify_auth_code(
                    code=user_input["code"].strip(), email=email, phone=phone
                )
            except OrionAuthError:
                errors["base"] = "invalid_code"
            except OrionConnectionError:
                errors["base"] = "cannot_connect"
            except OrionApiError:
                errors["base"] = "unknown"
            else:
                partner = {
                    CONF_AUTH_METHOD: self._p_method,
                    CONF_AUTH_VALUE: self._p_value,
                    CONF_ACCESS_TOKEN: tokens["access_token"],
                    CONF_REFRESH_TOKEN: tokens["refresh_token"],
                    CONF_EXPIRES_AT: tokens["expires_at"],
                }
                self.hass.config_entries.async_update_entry(
                    self._config_entry,
                    data={**self._config_entry.data, CONF_PARTNER: partner},
                )
                await self.hass.config_entries.async_reload(
                    self._config_entry.entry_id
                )
                return self.async_create_entry(title="", data=dict(self._config_entry.options))
        return self.async_show_form(
            step_id="partner_verify",
            data_schema=vol.Schema({vol.Required("code"): str}),
            errors=errors,
        )

    async def async_step_remove_partner(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm + remove the linked partner account."""
        if user_input is not None:
            new_data = {
                k: v for k, v in self._config_entry.data.items() if k != CONF_PARTNER
            }
            self.hass.config_entries.async_update_entry(
                self._config_entry, data=new_data
            )
            await self.hass.config_entries.async_reload(self._config_entry.entry_id)
            return self.async_create_entry(title="", data=dict(self._config_entry.options))
        return self.async_show_form(
            step_id="remove_partner", data_schema=vol.Schema({})
        )
```

(`async_get_clientsession`, `OrionApiClient`, `OrionApiError`, `OrionAuthError`,
`OrionConnectionError`, `_normalize_phone`, `_PHONE_RE`, `AUTH_METHOD_EMAIL`,
`AUTH_METHOD_PHONE` are all already module-level in config_flow.py.)

- [ ] **Step 3: Verify compile**

Run: `python3 -m py_compile custom_components/orion_sleep/config_flow.py`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add custom_components/orion_sleep/config_flow.py
git commit -m "Add Options-flow link/remove for a partner account"
```

---

## Task 4: Translations, docs, version bump

**Files:** Modify `strings.json`, `translations/en.json`, `README.md`, `AGENTS.md`, `manifest.json`

- [ ] **Step 1: Add options + issues translations**

In BOTH `custom_components/orion_sleep/strings.json` and
`custom_components/orion_sleep/translations/en.json`, replace the existing
`"options"` object with:

```json
  "options": {
    "step": {
      "init": {
        "title": "Orion Sleep Options",
        "menu_options": {
          "settings": "Settings (polling, insights days)",
          "link_partner": "Link partner account",
          "remove_partner": "Remove partner account"
        }
      },
      "settings": {
        "title": "Orion Sleep Settings",
        "data": {
          "scan_interval": "Polling interval (seconds)",
          "insights_days": "Days of sleep insights to fetch"
        }
      },
      "link_partner": {
        "title": "Link Partner Account",
        "description": "Add a second Orion account so the other side of the bed shows its sleep stats. Control stays on your account.",
        "data": { "auth_method": "Login method" }
      },
      "partner_email": {
        "title": "Partner Email",
        "description": "Enter the partner's Orion account email. A verification code will be sent to them.",
        "data": { "email": "Email address" }
      },
      "partner_phone": {
        "title": "Partner Phone",
        "description": "Enter the partner's Orion phone number (11 digits, e.g. 15552221234). A verification code will be sent to them.",
        "data": { "phone": "Phone number" }
      },
      "partner_verify": {
        "title": "Enter Partner Verification Code",
        "description": "Enter the verification code sent to the partner account.",
        "data": { "code": "Verification code" }
      },
      "remove_partner": {
        "title": "Remove Partner Account",
        "description": "Unlink the partner account. Their side's sleep stats will stop updating."
      }
    },
    "error": {
      "cannot_connect": "Failed to connect to Orion Sleep API",
      "invalid_code": "Invalid verification code",
      "invalid_phone": "Phone number must be 11 digits including the leading 1 (e.g. 15551234567).",
      "unknown": "An unexpected error occurred"
    }
  },
  "issues": {
    "partner_reauth": {
      "title": "Orion partner account needs re-linking",
      "description": "The linked partner Orion account can no longer authenticate. Re-link it from Settings > Devices & Services > Orion Sleep > Configure > Link partner account."
    }
  },
```

(Place the `"issues"` block as a top-level sibling of `"config"`/`"options"`/`"entity"`.)

- [ ] **Step 2: Validate JSON**

Run: `python3 -m json.tool custom_components/orion_sleep/strings.json >/dev/null && python3 -m json.tool custom_components/orion_sleep/translations/en.json >/dev/null && echo OK`
Expected: `OK`

- [ ] **Step 3: README — partner subsection**

In `README.md`, under `## Configuration` (after the Options table), add:

```markdown
### Two sleepers (partner account)

Sleep metrics are per Orion account, so a second person with their **own** Orion
account only shows their sleep stats if you link that account. Go to
**Settings > Devices & Services > Orion Sleep > Configure > Link partner account**
and complete the same email/phone + code login for the partner. Their side's
sensors (HRV, heart rate, sleep stages, etc.) then populate after their next
processed sleep session.

This is **stats only** — all control (climate, power, schedule) stays on your
primary account. Remove the partner anytime via **Configure > Remove partner
account**. If the partner login expires, you'll get a repair notification to
re-link it.
```

- [ ] **Step 4: AGENTS.md — note the partner client**

In `AGENTS.md`, under Architecture, add a bullet:

```markdown
- **Partner account (optional):** `entry.data[CONF_PARTNER]` holds a second
  account's tokens. The coordinator builds a second `OrionApiClient`
  (`_partner_client`) used ONLY for `get_insights`, stored at
  `data["insights_partner"]`. `get_latest_session_for_zone` searches primary then
  partner, so each account's sessions populate their own zone. Linked/removed via
  the Options flow; auth failure raises the `partner_reauth` repair issue and
  degrades that side to unknown without disrupting the primary.
```

- [ ] **Step 5: Bump version**

In `manifest.json`, set `"version": "1.4.0"`.

- [ ] **Step 6: Full verification**

Run: `python3 -m pytest tests/ -q` → all pass.
Run: `python3 -m py_compile custom_components/orion_sleep/*.py` → exit 0.
Run: `python3 -m json.tool custom_components/orion_sleep/manifest.json >/dev/null && python3 -m json.tool custom_components/orion_sleep/strings.json >/dev/null && python3 -m json.tool custom_components/orion_sleep/translations/en.json >/dev/null && echo OK` → `OK`.

- [ ] **Step 7: Commit**

```bash
git add README.md AGENTS.md custom_components/orion_sleep/manifest.json custom_components/orion_sleep/strings.json custom_components/orion_sleep/translations/en.json
git commit -m "Docs, translations, version bump to 1.4.0 for partner account"
```

- [ ] **Step 8: Manual HA verification**

1. Configure > Link partner account → complete the partner's code login → entry
   reloads with no errors.
2. After the partner's next processed session, the partner's side (e.g. Side B)
   insight sensors populate; the primary's side is unaffected; all control still
   works through the primary.
3. Configure > Remove partner account → partner side returns to unknown, no errors.
4. (Optional) simulate partner token failure → a "partner account needs
   re-linking" repair notification appears; primary keeps working.

---

## Self-Review Notes

- **Spec coverage:** CONF_PARTNER (T1) ✓; second client insights-only + persist
  refresh (T2 steps 2-4) ✓; best-effort fetch + repair issue create/delete (T2
  step 4) ✓; dual-source `get_latest_session_for_zone` (T2 step 5) ✓; options menu
  link/remove reusing auth (T3) ✓; reload on link/remove so coordinator rebuilds
  (T3 verify/remove steps call `async_reload`) ✓; translations incl. issue text
  (T4) ✓; docs + 1.4.0 (T4) ✓; control-stays-primary (partner client only calls
  `get_insights`) ✓; single partner (one CONF_PARTNER block) ✓.
- **Placeholder scan:** no TBD/TODO; full code/JSON in every step. The one prose
  note (hoist `insights_days` if scoped inside the primary try) is a concrete
  instruction, not a placeholder.
- **Type/name consistency:** `CONF_PARTNER`, `_partner_client`,
  `_on_partner_token_refresh`, `data["insights_partner"]`, issue id
  `"partner_reauth"` used consistently across coordinator + translations;
  `OrionApiClient(session=, access_token=, refresh_token=, expires_at=)` matches
  api.py; `request_auth_code(email=, phone=)` / `verify_auth_code(code=, email=, phone=)`
  match config_flow usage; options-flow step ids match the translation step keys.
