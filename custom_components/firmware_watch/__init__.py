"""Firmware Watch - one place to track firmware updates for any device.

The integration never logs in to the devices. The installed version is part of
the configuration; the newest version is read from the vendor's website/API.
"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import FirmwareCoordinator, FirmwareWatchConfigEntry

PLATFORMS = [Platform.UPDATE]


async def async_setup_entry(hass: HomeAssistant, entry: FirmwareWatchConfigEntry) -> bool:
    coordinator = FirmwareCoordinator(hass, entry)
    # A vendor site being down must not block startup - entity becomes
    # unavailable and the next scheduled refresh retries.
    await coordinator.async_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FirmwareWatchConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
