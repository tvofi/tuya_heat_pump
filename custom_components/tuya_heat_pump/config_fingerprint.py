"""Which config-entry changes need a reload (see async_update_options)."""
from __future__ import annotations

from typing import Any

from .const import (
    CONF_CACHED_ACCESS_TOKEN,
    CONF_CACHED_MODEL_SCHEMA,
    CONF_CACHED_TOKEN_EXPIRES_AT,
    CONF_SHARING_TOKEN_INFO,
)

# entry.data keys the integration writes itself as caches. Changing them
# never needs a reload: the token cache and the MQTT token are refreshed
# in place, the model cache only matters on the next start.
CACHE_ONLY_KEYS = frozenset({
    CONF_CACHED_ACCESS_TOKEN,
    CONF_CACHED_TOKEN_EXPIRES_AT,
    CONF_CACHED_MODEL_SCHEMA,
    CONF_SHARING_TOKEN_INFO,
    "cached_model_id",
    "cached_model_device_id",
})


def config_fingerprint(entry: Any) -> tuple:
    """Hashable snapshot of the settings that require a reload."""
    data = getattr(entry, "data", None) or {}
    options = getattr(entry, "options", None) or {}
    return (
        repr(sorted((k, v) for k, v in data.items() if k not in CACHE_ONLY_KEYS)),
        repr(sorted(options.items())),
    )
