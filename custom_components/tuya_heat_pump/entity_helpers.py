"""Small helpers shared by every entity platform.

Model files (and discovery.py) may carry a few optional presentation keys
that are not tied to a particular platform:

- ``entity_category``: ``"config"`` or ``"diagnostic"`` (HA EntityCategory).
- ``enabled_default``: ``False`` to create the entity disabled in the
  registry (the user can enable it from the device page).
- ``tuya_name`` / ``tuya_type`` / ``tuya_access`` / ``discovered``:
  informational, surfaced as state attributes so a discovered register
  shows where it came from and what Tuya calls it.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.helpers.entity import EntityCategory

_LOGGER = logging.getLogger(__name__)

_CATEGORY_BY_NAME = {
    "config": EntityCategory.CONFIG,
    "diagnostic": EntityCategory.DIAGNOSTIC,
}


def apply_common_entity_attrs(entity: Any, config: dict) -> None:
    """Apply entity_category / enabled_default from a model config."""
    category = config.get("entity_category")
    if category:
        resolved = _CATEGORY_BY_NAME.get(str(category).lower())
        if resolved is None:
            _LOGGER.debug("Unknown entity_category %r ignored", category)
        else:
            entity._attr_entity_category = resolved
    if "enabled_default" in config:
        entity._attr_entity_registry_enabled_default = bool(config["enabled_default"])


def common_extra_attrs(config: dict) -> dict[str, Any]:
    """Provenance attributes for discovered / annotated registers."""
    attrs: dict[str, Any] = {}
    for key in ("tuya_name", "tuya_type", "tuya_access"):
        if config.get(key):
            attrs[key] = config[key]
    if config.get("discovered"):
        attrs["discovered"] = True
    return attrs
