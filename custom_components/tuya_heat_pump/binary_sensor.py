"""Binary sensor platform for Tuya Heatpump."""
from __future__ import annotations
import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .conversion import Conversion
from .coordinator import TuyaScaleDataUpdateCoordinator
from .entity_helpers import apply_common_entity_attrs, common_extra_attrs
from .raw_codec import decode_raw_field, resolve_raw_source, watch_pending_raw_entities

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tuya Heatpump binary sensors from a config entry."""
    coordinator: TuyaScaleDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    
    binary_sensors = []
    pending = []
    
    # Online status binary sensor - HER ZAMAN EKLE
    binary_sensors.append(TuyaHeatpumpOnlineSensor(coordinator))
    _LOGGER.info("Adding online status binary sensor")
    
    # Model mapping'den binary sensörleri al
    binary_sensor_configs = coordinator.model_mapping.get("binary_sensors", {})
    
    for sensor_code, sensor_config in binary_sensor_configs.items():
        # Raw-field binary sensor: value is one field of a raw payload DP.
        if "field_index" in sensor_config or "byte_offset" in sensor_config:
            raw_source = resolve_raw_source(coordinator, sensor_config)
            if raw_source and coordinator.data and raw_source in coordinator.data:
                binary_sensors.append(TuyaHeatpumpBinarySensor(
                    coordinator, sensor_code, {**sensor_config, "raw_source": raw_source}))
            else:
                pending.append((sensor_code, sensor_config))
            continue
        lookup_code = sensor_config.get("code", sensor_code)
        if (
            (coordinator.data and lookup_code in coordinator.data)
            or coordinator.dp_known(sensor_config)
        ):
            # A DP the device's schema knows is created even when the
            # first poll lacks it: the cloud shadow drops DPs the device
            # has not re-reported lately (see coordinator.dp_known) and
            # skipping the entity here would make it vanish for good on
            # the next restart. It shows "unknown" until a value arrives.
            binary_sensors.append(TuyaHeatpumpBinarySensor(coordinator, sensor_code, sensor_config))
            _LOGGER.info("Adding binary sensor: %s (%s)", sensor_config.get('name', sensor_code), sensor_code)
        else:
            _LOGGER.warning("Binary sensor %s not found in device data, skipping", sensor_code)
    
    if coordinator.defrost_supported:
        _migrate_defrost_unique_id(hass, coordinator, binary_sensor_configs)
        binary_sensors.append(TuyaHeatpumpDefrostSensor(coordinator))
        _LOGGER.info("Adding defrost binary sensor (source: %s)", coordinator.defrost_source)

    async_add_entities(binary_sensors)
    watch_pending_raw_entities(
        config_entry, coordinator, async_add_entities,
        pending, TuyaHeatpumpBinarySensor, _LOGGER,
    )


def _device_slug(coordinator) -> str:
    return coordinator.device_name.lower().replace(" ", "_").replace("-", "_")


DEFROST_UNIQUE_KEY = "defrost"


def _migrate_defrost_unique_id(hass, coordinator, binary_sensor_configs: dict) -> None:
    """Hand a model's retired defrost binary sensor over to this one.

    A model file whose old "Defrosting" entity read the wrong DP drops it
    and lists its key in DEFROST_DETECTION["replaces"] (Rotenso Windmi:
    "DEF", the forced-defrost command flag). The registry entry is moved
    to the new unique id, so the entity id, its history and automations
    that use it now follow the real defrost state instead of going
    orphaned. Skipped when the old key is still mapped or the new entity
    already exists."""
    detection = coordinator.model_mapping.get("defrost_detection") or {}
    old_key = detection.get("replaces")
    if not old_key or old_key in binary_sensor_configs:
        return
    try:
        registry = er.async_get(hass)
    except Exception as err:  # no registry (offline tools)
        _LOGGER.debug("Entity registry unavailable: %s", err)
        return
    slug = _device_slug(coordinator)
    old_entity = registry.async_get_entity_id("binary_sensor", DOMAIN, f"{slug}_{old_key}")
    if old_entity is None:
        return
    if registry.async_get_entity_id("binary_sensor", DOMAIN, f"{slug}_{DEFROST_UNIQUE_KEY}"):
        return
    registry.async_update_entity(old_entity, new_unique_id=f"{slug}_{DEFROST_UNIQUE_KEY}")
    _LOGGER.info("Migrated %s to the defrost state sensor", old_entity)


class TuyaHeatpumpDefrostSensor(BinarySensorEntity):
    """Whether the unit is defrosting.

    Source: the binary_sensor chosen in the options (e.g. a Modbus
    running-mode sensor), else the model's heuristic (defrost.py). The
    heuristic infers the state, hence the name "Defrost (suspected)"."""

    _attr_has_entity_name = True
    _attr_device_class = "cold"
    _attr_icon = "mdi:snowflake-melt"

    def __init__(self, coordinator: TuyaScaleDataUpdateCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{_device_slug(coordinator)}_{DEFROST_UNIQUE_KEY}"
        self._attr_name = (
            "Defrost" if coordinator.defrost_source == "entity" else "Defrost (suspected)"
        )
        self._attr_device_info = coordinator.device_info

    @property
    def device_info(self):
        return self.coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.defrost_active

    @property
    def available(self) -> bool:
        if self.coordinator.defrost_source == "entity":
            return self.coordinator.defrost_active is not None
        return bool(self.coordinator.last_update_success and self.coordinator.data is not None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"source": self.coordinator.defrost_source}
        if self.coordinator.defrost_source == "entity":
            attrs["source_entity"] = self.coordinator.defrost_entity_id
        else:
            attrs["confirmed"] = self.coordinator.defrost_confirmed
        return attrs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )


class TuyaHeatpumpOnlineSensor(BinarySensorEntity):
    """Representation of a Tuya Heatpump Online Status Binary Sensor."""

    def __init__(
        self,
        coordinator: TuyaScaleDataUpdateCoordinator,
    ) -> None:
        """Initialize the online status binary sensor."""
        self.coordinator = coordinator
        
        # Device name ile unique_id oluştur
        device_name_slug = coordinator.device_name.lower().replace(" ", "_").replace("-", "_")
        self._attr_unique_id = f"{device_name_slug}_online_status"
        
        self._attr_name = "Online Status"
        self._attr_device_class = "connectivity"
        self._attr_has_entity_name = True
        
        # Device info
        self._attr_device_info = coordinator.device_info

    @property
    def device_info(self):
        """Return device info."""
        return self.coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        """Return true if the device is online."""
        return self.coordinator.is_online

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Online sensörü her zaman available olmalı
        return True

    @property
    def icon(self) -> str:
        """Return the icon to use in the frontend."""
        return "mdi:lan-connect" if self.is_on else "mdi:lan-disconnect"

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )


class TuyaHeatpumpBinarySensor(BinarySensorEntity):
    """Representation of a Tuya Heatpump Binary Sensor."""

    def __init__(
        self,
        coordinator: TuyaScaleDataUpdateCoordinator,
        sensor_code: str,
        config: dict
    ) -> None:
        """Initialize the binary sensor."""
        self.coordinator = coordinator
        self._sensor_code = sensor_code
        self._config = config
        
        # Device name ile unique_id oluştur
        device_name_slug = coordinator.device_name.lower().replace(" ", "_").replace("-", "_")
        self._attr_unique_id = f"{device_name_slug}_{sensor_code}"
        
        self._attr_name = config.get('name', sensor_code)
        self._attr_device_class = config.get('device_class')
        self._attr_has_entity_name = True
        apply_common_entity_attrs(self, config)

        # Device info
        self._attr_device_info = coordinator.device_info

    def _lookup_code(self) -> str:
        """The real Tuya DP code to use for coordinator.data lookups.
        Normally identical to the dict key (sensor_code), but a model
        file can set an explicit "code" to decouple the two — needed
        when several entities read the same DP (e.g. multiple per-bit
        fault binary sensors all sharing one "fault" bitmap DP): each
        needs its own dict key for identity/uniqueness, but they all
        point "code" at the same real Tuya DP."""
        return self._config.get("code", self._sensor_code)

    @property
    def device_info(self):
        """Return device info."""
        return self.coordinator.device_info

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if "field_index" in self._config or "byte_offset" in self._config:
            raw_source = resolve_raw_source(self.coordinator, self._config)
            if raw_source is None or not self.coordinator.data or raw_source not in self.coordinator.data:
                return None
            raw_value = decode_raw_field(
                self.coordinator.data[raw_source].get('value'),
                self._config.get('field_index', 0),
                self._config.get('encoding', 'int32_be'),
                byte_offset=self._config.get('byte_offset'),
            )
            if raw_value is None:
                return None
        else:
            lookup_code = self._lookup_code()
            if not self.coordinator.data or lookup_code not in self.coordinator.data:
                return None
            raw_value = self.coordinator.data[lookup_code]['value']

        conversion = Conversion(self._config.get('conversion', 'bool(value)'))
        try:
            result = conversion.convert(raw_value)
            return bool(result)
        except Exception as err:
            _LOGGER.warning("Conversion failed for %s: %s", self._sensor_code, err)
            
            # Fallback conversion
            if isinstance(raw_value, bool):
                return raw_value
            elif isinstance(raw_value, (int, float)):
                return bool(raw_value)
            elif isinstance(raw_value, str):
                return raw_value.lower() in ['true', '1', 'on', 'yes', 'enable', 'open']
            
            return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Tuya DP ID ve Code bilgilerini attributes'a ekle."""
        attrs: dict[str, Any] = {}
        
        attrs["tuya_code"] = self._config.get("raw_source") or self._lookup_code()
        attrs["tuya_dp_id"] = self._config.get("dp_id")

        if self.coordinator.model_id:
            attrs["tuya_model_id"] = self.coordinator.model_id

        attrs.update(common_extra_attrs(self._config))
        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not (
            self.coordinator.last_update_success and
            self.coordinator.data is not None
        ):
            return False
        if "field_index" in self._config or "byte_offset" in self._config:
            raw_source = resolve_raw_source(self.coordinator, self._config)
            return raw_source is not None and raw_source in self.coordinator.data
        if self._lookup_code() in self.coordinator.data:
            return True
        # DP the schema knows but the poll data currently lacks → keep
        # the entity available with an unknown state (coordinator.dp_known).
        return self.coordinator.dp_known(self._config)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
