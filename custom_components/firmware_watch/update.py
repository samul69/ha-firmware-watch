"""Update entity: installed version (from config) vs newest vendor version."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_VERSION,
    CONF_INSTALLED_VERSION,
    CONF_NAME,
    CONF_PROVIDER,
    DOMAIN,
    SERVICE_SET_INSTALLED_VERSION,
)
from .coordinator import FirmwareCoordinator, FirmwareWatchConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FirmwareWatchConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([FirmwareUpdateEntity(entry.runtime_data)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_INSTALLED_VERSION,
        {vol.Optional(ATTR_VERSION): cv.string},
        "async_set_installed_version",
    )


class FirmwareUpdateEntity(CoordinatorEntity[FirmwareCoordinator], UpdateEntity):
    """Shows whether the vendor published newer firmware."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    # Informational only - we never install. Must be the flag type, not int:
    # UpdateEntity checks `UpdateEntityFeature.INSTALL in supported_features`.
    _attr_supported_features = UpdateEntityFeature(0)

    def __init__(self, coordinator: FirmwareCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        conf = coordinator.conf
        provider = coordinator.provider
        self._attr_unique_id = f"{entry.entry_id}_firmware"
        manufacturer = conf.get("manufacturer") or provider.manufacturer
        model = provider.model(conf)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=conf.get(CONF_NAME) or entry.title,
            manufacturer=manufacturer,
            model=model,
            sw_version=coordinator.installed_version,
        )
        self._attr_title = " ".join(x for x in (manufacturer, model) if x) or None

    @property
    def installed_version(self) -> str | None:
        return self.coordinator.installed_version or None

    @property
    def latest_version(self) -> str | None:
        if self.coordinator.data is None:
            return None
        source = self.coordinator.data.version
        installed = self.installed_version
        # Vendor feeds can lag behind what is already installed (e.g. a BIOS
        # flashed from the support site before the update catalog caught up).
        # Never report something older than the installed version as "latest".
        if installed and self.coordinator.provider.is_newer(installed, source):
            return installed
        return source

    @property
    def release_url(self) -> str | None:
        return self.coordinator.data.release_url if self.coordinator.data else None

    @property
    def release_summary(self) -> str | None:
        return self.coordinator.data.summary if self.coordinator.data else None

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        return self.coordinator.provider.is_newer(latest_version, installed_version)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "provider": self.coordinator.conf.get(CONF_PROVIDER),
            "source_latest_version": data.version if data else None,
            "published": data.published if data else None,
            "last_check": self.coordinator.last_check,
        }

    async def async_set_installed_version(self, version: str | None = None) -> None:
        """Remember a new installed version (e.g. after a manual upgrade)."""
        version = (version or self.latest_version or "").strip()
        if not version:
            return
        entry = self.coordinator.config_entry
        self.hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_INSTALLED_VERSION: version}
        )
        dev_reg = dr.async_get(self.hass)
        if device := dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)}):
            dev_reg.async_update_device(device.id, sw_version=version)
        self.async_write_ha_state()
