"""Which config-entry changes need a reload (see async_update_options)."""
from __future__ import annotations

import json
from typing import Any

from .const import (
    CONF_CACHED_ACCESS_TOKEN,
    CONF_CACHED_MODEL_DEVICE_ID,
    CONF_CACHED_MODEL_ID,
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
    CONF_CACHED_MODEL_ID,
    CONF_CACHED_MODEL_DEVICE_ID,
    CONF_SHARING_TOKEN_INFO,
})


def _canonical(value: Any) -> str:
    # sort_keys: nested dicts compare by content, not insertion order.
    return json.dumps(value, sort_keys=True, default=str)


def config_fingerprint(entry: Any) -> tuple[str, str]:
    """Snapshot of the settings that require a reload."""
    data = getattr(entry, "data", None) or {}
    options = getattr(entry, "options", None) or {}
    return (
        _canonical({k: v for k, v in data.items() if k not in CACHE_ONLY_KEYS}),
        _canonical(dict(options)),
    )
