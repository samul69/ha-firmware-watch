"""Coordinator that checks the vendor once per interval."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_INSTALLED_VERSION,
    CONF_PROVIDER,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
)
from .providers import PROVIDERS, Provider, ProviderError, Release

_LOGGER = logging.getLogger(__name__)

type FirmwareWatchConfigEntry = ConfigEntry[FirmwareCoordinator]


def entry_conf(entry: ConfigEntry) -> dict[str, Any]:
    """Merged configuration (options override data)."""
    return {**entry.data, **entry.options}


class FirmwareCoordinator(DataUpdateCoordinator[Release]):
    """Fetch the newest firmware for one configured device."""

    config_entry: FirmwareWatchConfigEntry

    def __init__(self, hass: HomeAssistant, entry: FirmwareWatchConfigEntry) -> None:
        conf = entry_conf(entry)
        hours = float(conf.get(CONF_SCAN_INTERVAL_HOURS) or DEFAULT_SCAN_INTERVAL_HOURS)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(hours=max(hours, 1)),
        )
        self.provider: Provider = PROVIDERS[conf[CONF_PROVIDER]]
        self.last_check = None

    @property
    def conf(self) -> dict[str, Any]:
        return entry_conf(self.config_entry)

    @property
    def installed_version(self) -> str:
        return str(self.conf.get(CONF_INSTALLED_VERSION) or "").strip()

    async def _async_update_data(self) -> Release:
        session = async_get_clientsession(self.hass)
        try:
            release = await self.provider.async_latest(session, self.conf)
        except ProviderError as err:
            raise UpdateFailed(str(err)) from err
        self.last_check = dt_util.utcnow()
        return release
