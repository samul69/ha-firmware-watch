"""Config flow: one config entry = one device to watch."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_INSTALLED_VERSION,
    CONF_NAME,
    CONF_PROVIDER,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
)
from .providers import PROVIDERS, Field, ProviderError

INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=1, max=24 * 14, step=1, mode=NumberSelectorMode.BOX,
                         unit_of_measurement="h")
)


def _selector(f: Field):
    if f.kind == "bool":
        return BooleanSelector()
    if f.kind == "select":
        return SelectSelector(
            SelectSelectorConfig(options=f.options, translation_key=f.key,
                                 mode=SelectSelectorMode.DROPDOWN)
        )
    return TextSelector()


def _field_schema(fields: list[Field], current: dict[str, Any]) -> dict:
    schema: dict = {}
    for f in fields:
        value = current.get(f.key, f.default)
        if f.required:
            key = vol.Required(f.key, default=value) if value not in (None, "") else vol.Required(f.key)
        elif value not in (None, ""):
            key = vol.Optional(f.key, description={"suggested_value": value})
        else:
            key = vol.Optional(f.key)
        schema[key] = _selector(f)
    return schema


async def _validate(hass, conf: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Try to fetch the latest version. Returns (errors, placeholders)."""
    provider = PROVIDERS[conf[CONF_PROVIDER]]
    try:
        release = await provider.async_latest(async_get_clientsession(hass), conf)
    except ProviderError as err:
        return {"base": "cannot_fetch"}, {"error": str(err)}
    except Exception as err:  # noqa: BLE001 - surface anything to the user
        return {"base": "cannot_fetch"}, {"error": repr(err)}
    return {}, {"latest": release.version}


class FirmwareWatchConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a device to watch."""

    VERSION = 1

    def __init__(self) -> None:
        self._provider: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._provider = user_input[CONF_PROVIDER]
            return await self._device_step(None)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_PROVIDER): SelectSelector(
                    SelectSelectorConfig(options=list(PROVIDERS), translation_key="provider",
                                         mode=SelectSelectorMode.LIST)
                )
            }),
        )

    async def _device_step(self, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        assert self._provider
        provider = PROVIDERS[self._provider]
        errors: dict[str, str] = {}
        placeholders = {"error": ""}
        current = user_input or {}

        if user_input is not None:
            conf = {CONF_PROVIDER: self._provider, **user_input}
            errors, placeholders = await _validate(self.hass, conf)
            placeholders.setdefault("error", "")
            if not errors:
                options = {
                    CONF_INSTALLED_VERSION: user_input.pop(CONF_INSTALLED_VERSION).strip(),
                    CONF_SCAN_INTERVAL_HOURS: user_input.pop(
                        CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
                    ),
                }
                data = {CONF_PROVIDER: self._provider, **user_input}
                uid = "|".join(
                    [self._provider, data[CONF_NAME].strip().lower()]
                    + [str(data.get(f.key, "")).strip().lower() for f in provider.fields]
                )
                await self.async_set_unique_id(uid)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=data[CONF_NAME], data=data, options=options)

        schema = {
            vol.Required(CONF_NAME, default=current.get(CONF_NAME, "")): TextSelector(),
            vol.Required(CONF_INSTALLED_VERSION,
                         default=current.get(CONF_INSTALLED_VERSION, "")): TextSelector(),
            **_field_schema(provider.fields, current),
            vol.Optional(CONF_SCAN_INTERVAL_HOURS,
                         default=current.get(CONF_SCAN_INTERVAL_HOURS,
                                             DEFAULT_SCAN_INTERVAL_HOURS)): INTERVAL_SELECTOR,
        }
        return self.async_show_form(
            step_id=self._provider,
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders=placeholders,
        )

    # One step per provider (step_id == provider key).
    async def async_step_synology(self, user_input=None):
        return await self._device_step(user_input)

    async def async_step_omada(self, user_input=None):
        return await self._device_step(user_input)

    async def async_step_tplink(self, user_input=None):
        return await self._device_step(user_input)

    async def async_step_mikrotik(self, user_input=None):
        return await self._device_step(user_input)

    async def async_step_avm(self, user_input=None):
        return await self._device_step(user_input)

    async def async_step_reolink(self, user_input=None):
        return await self._device_step(user_input)

    async def async_step_unifi(self, user_input=None):
        return await self._device_step(user_input)

    async def async_step_openwrt(self, user_input=None):
        return await self._device_step(user_input)

    async def async_step_apple(self, user_input=None):
        return await self._device_step(user_input)

    async def async_step_asus(self, user_input=None):
        return await self._device_step(user_input)

    async def async_step_dell(self, user_input=None):
        return await self._device_step(user_input)

    async def async_step_lenovo(self, user_input=None):
        return await self._device_step(user_input)

    async def async_step_samsung(self, user_input=None):
        return await self._device_step(user_input)

    async def async_step_github(self, user_input=None):
        return await self._device_step(user_input)

    async def async_step_web_regex(self, user_input=None):
        return await self._device_step(user_input)

    async def async_step_json(self, user_input=None):
        return await self._device_step(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> FirmwareWatchOptionsFlow:
        return FirmwareWatchOptionsFlow()


class FirmwareWatchOptionsFlow(OptionsFlowWithReload):
    """Change installed version, interval or source settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        current = {**entry.data, **entry.options}
        provider = PROVIDERS[current[CONF_PROVIDER]]
        errors: dict[str, str] = {}
        placeholders = {"error": ""}

        if user_input is not None:
            # Optional fields left empty must clear previous values.
            for f in provider.fields:
                user_input.setdefault(f.key, "" if f.kind != "bool" else False)
            conf = {**current, **user_input}
            errors, placeholders = await _validate(self.hass, conf)
            placeholders.setdefault("error", "")
            if not errors:
                user_input[CONF_INSTALLED_VERSION] = user_input[CONF_INSTALLED_VERSION].strip()
                return self.async_create_entry(data={**entry.options, **user_input})
            current = conf

        schema = {
            vol.Required(CONF_INSTALLED_VERSION,
                         default=current.get(CONF_INSTALLED_VERSION, "")): TextSelector(),
            **_field_schema(provider.fields, current),
            vol.Optional(CONF_SCAN_INTERVAL_HOURS,
                         default=current.get(CONF_SCAN_INTERVAL_HOURS,
                                             DEFAULT_SCAN_INTERVAL_HOURS)): INTERVAL_SELECTOR,
        }
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(schema),
            errors=errors, description_placeholders=placeholders,
        )
