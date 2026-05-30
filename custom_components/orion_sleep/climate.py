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
