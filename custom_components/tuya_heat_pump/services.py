"""Generic register (data point) services for Tuya Heat Pump.

These exist for the long tail of registers that neither the model file
nor discovery can type confidently -- for example a DP the cloud schema
marks read-only but the device actually accepts, or a raw blob you are
reverse-engineering with test/raw_explorer.py. They operate on any DP
by Tuya code or numeric id and go through exactly the same send path
the entities use (cloud command API, or local set_value with debounce).

    service: tuya_heat_pump.write_dp
    data:
      device_id: <Home Assistant device id>   # optional with one heat pump
      code: DHWSET            # or dp_id: 104
      value: 48

    service: tuya_heat_pump.refresh
    data:
      device_id: <Home Assistant device id>   # optional with one heat pump
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_WRITE_DP = "write_dp"
SERVICE_REFRESH = "refresh"

ATTR_DEVICE_ID = "device_id"
ATTR_CODE = "code"
ATTR_DP_ID = "dp_id"
ATTR_VALUE = "value"

WRITE_DP_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional(ATTR_DEVICE_ID): cv.string,
            vol.Optional(ATTR_CODE): cv.string,
            vol.Optional(ATTR_DP_ID): vol.Coerce(int),
            vol.Required(ATTR_VALUE): vol.Any(bool, int, float, str),
        }
    ),
    cv.has_at_least_one_key(ATTR_CODE, ATTR_DP_ID),
)

REFRESH_SCHEMA = vol.Schema({vol.Optional(ATTR_DEVICE_ID): cv.string})


def _coordinator_for_call(hass: HomeAssistant, call: ServiceCall):
    """Resolve the coordinator from the HA device id (or the only entry)."""
    coordinators = hass.data.get(DOMAIN, {})
    if not coordinators:
        raise HomeAssistantError("No Tuya Heat Pump is set up")
    device_id = call.data.get(ATTR_DEVICE_ID)
    if not device_id:
        if len(coordinators) == 1:
            return next(iter(coordinators.values()))
        raise HomeAssistantError(
            "Several heat pumps are configured: pass device_id"
        )
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise HomeAssistantError(f"Unknown device_id {device_id}")
    tuya_ids = {ident[1] for ident in device.identifiers if ident[0] == DOMAIN}
    for coordinator in coordinators.values():
        if coordinator.device_id in tuya_ids:
            return coordinator
    raise HomeAssistantError(f"Device {device_id} is not a Tuya Heat Pump")


def _coerce_value(value: Any, tuya_type: str | None) -> Any:
    """Turn the service's value into what the DP type expects."""
    if tuya_type == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "on", "yes", "enable", "open")
        return bool(value)
    if tuya_type == "value":
        if isinstance(value, str):
            value = float(value)
        return int(round(value)) if isinstance(value, (int, float)) else value
    if tuya_type in ("enum", "string", "raw"):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


async def _async_write_dp(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinator = _coordinator_for_call(hass, call)
    code = call.data.get(ATTR_CODE)
    dp_id = call.data.get(ATTR_DP_ID)

    schema_prop = None
    if dp_id is not None:
        schema_prop = coordinator.device_schema.get(int(dp_id))
        if code is None:
            code = coordinator.dp_mapping.get(int(dp_id)) or (schema_prop or {}).get("code")
        if code is None:
            raise HomeAssistantError(
                f"dp_id {dp_id} is not known for this device (no model file entry "
                f"and not in the cloud schema); pass code= instead"
            )
    if schema_prop is None:
        schema_prop = next(
            (p for p in coordinator.device_schema.values() if p.get("code") == code), None
        )
    tuya_type = (schema_prop or {}).get("type") or (
        coordinator.data.get(code, {}).get("type") if coordinator.data else None
    )
    value = _coerce_value(call.data[ATTR_VALUE], tuya_type)

    if schema_prop and schema_prop.get("access") == "ro":
        _LOGGER.warning(
            "write_dp: %s is marked read-only in the device schema; trying anyway", code
        )

    _LOGGER.info("write_dp: %s (dp %s, type %s) = %r", code, dp_id, tuya_type, value)
    ok = await coordinator.send_command(code, value)
    if not ok:
        raise HomeAssistantError(f"Device rejected write of {code} = {value!r}")
    await coordinator.async_request_refresh()


async def _async_refresh(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinator = _coordinator_for_call(hass, call)
    await coordinator.async_request_refresh()


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the services once (idempotent across config entries)."""
    if hass.services.has_service(DOMAIN, SERVICE_WRITE_DP):
        return

    async def write_dp(call: ServiceCall) -> None:
        await _async_write_dp(hass, call)

    async def refresh(call: ServiceCall) -> None:
        await _async_refresh(hass, call)

    hass.services.async_register(DOMAIN, SERVICE_WRITE_DP, write_dp, schema=WRITE_DP_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, refresh, schema=REFRESH_SCHEMA)


def async_unload_services(hass: HomeAssistant) -> None:
    for service in (SERVICE_WRITE_DP, SERVICE_REFRESH):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
