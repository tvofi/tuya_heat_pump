"""Diagnostics support for Tuya Heat Pump.

Settings -> Devices & Services -> Tuya Heat Pump -> (⋮) -> Download
diagnostics. The JSON contains everything needed to build or improve a
model file: the device's full Tuya schema (every data point with type,
access mode, ranges and labels), the live values, which data points the
static model covers, which ones discovery added, and which are still
unmapped. Secrets (keys, tokens, IDs that identify the account) are
redacted.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_KEY,
    CONF_CACHED_ACCESS_TOKEN,
    CONF_CACHED_MODEL_SCHEMA,
    CONF_LOCAL_KEY,
    CONF_SHARING_TOKEN_INFO,
    CONF_USER_CODE,
    DOMAIN,
)
from .discovery import ENTITY_CATEGORIES, compact_schema, static_coverage

TO_REDACT = {
    CONF_ACCESS_ID,
    CONF_ACCESS_KEY,
    CONF_LOCAL_KEY,
    CONF_USER_CODE,
    CONF_SHARING_TOKEN_INFO,
    CONF_CACHED_ACCESS_TOKEN,
    "ip",
    "uid",
    "owner_id",
    "local_key",
    "access_token",
    "refresh_token",
}


def _mapping_summary(mapping: dict | None) -> dict[str, list[dict]]:
    """Compact, JSON-safe view of an entity mapping."""
    summary: dict[str, list[dict]] = {}
    for category in ENTITY_CATEGORIES:
        items = []
        for key, cfg in (mapping or {}).get(category, {}).items():
            if not isinstance(cfg, dict):
                continue
            items.append({
                "key": key,
                "code": cfg.get("code", key),
                "dp_id": cfg.get("dp_id"),
                "name": cfg.get("name"),
                "raw_source": cfg.get("raw_source"),
                "field_index": cfg.get("field_index"),
                "discovered": bool(cfg.get("discovered")),
                "conversion": cfg.get("conversion"),
                "entity_category": cfg.get("entity_category"),
            })
        summary[category] = items
    return summary


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    entry_data = dict(entry.data)
    # The cached schema is repeated below in a nicer form.
    entry_data.pop(CONF_CACHED_MODEL_SCHEMA, None)

    result: dict[str, Any] = {
        "entry": {
            "data": async_redact_data(entry_data, TO_REDACT),
            "options": dict(entry.options),
        },
    }
    if coordinator is None:
        result["coordinator"] = None
        return result

    full_mapping = coordinator.model_mapping or {}
    static_dp_ids, static_codes = static_coverage(full_mapping)
    live = coordinator.data or {}

    result["device"] = {
        "device_id": coordinator.device_id,
        "name": coordinator.device_name,
        "model_id": coordinator.model_id,
        "model_name": full_mapping.get("model_name"),
        "connection_type": coordinator.connection_type,
        "online": coordinator.is_online,
        "last_update_success": coordinator.last_update_success,
        "discovery_enabled": coordinator.discovery_enabled,
    }
    result["schema"] = compact_schema(coordinator.device_schema)
    result["live_data"] = live
    result["dp_mapping"] = {str(k): v for k, v in (coordinator.dp_mapping or {}).items()}
    result["raw_code_by_dp_id"] = {str(k): v for k, v in (coordinator.raw_code_by_dp_id or {}).items()}
    result["entities"] = _mapping_summary(full_mapping)
    result["discovered"] = _mapping_summary(coordinator.discovered_mapping)
    result["unmapped_codes"] = coordinator.unmapped_dp_codes
    result["schema_not_reported"] = sorted(
        prop["code"] for prop in coordinator.device_schema.values()
        if prop["code"] not in live and prop["dp_id"] not in static_dp_ids
    )
    return result
