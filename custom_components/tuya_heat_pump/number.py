"""Number platform for Tuya Heatpump."""
from __future__ import annotations
import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .conversion import Conversion
from .coordinator import TuyaScaleDataUpdateCoordinator
from .raw_codec import decode_raw_field, resolve_raw_source, watch_pending_raw_entities
from .entity_helpers import apply_common_entity_attrs, common_extra_attrs

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tuya Heatpump numbers from a config entry."""
    coordinator: TuyaScaleDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    
    numbers = []
    pending = []
    
    number_configs = coordinator.model_mapping.get("numbers", {})
    
    for number_code, number_config in number_configs.items():
        # Raw-field number: value comes from decoding a raw payload DP.
        if "field_index" in number_config:
            raw_source = resolve_raw_source(coordinator, number_config)
            if raw_source and coordinator.data and raw_source in coordinator.data:
                number_config = {**number_config, "raw_source": raw_source}
                numbers.append(TuyaHeatpumpNumber(coordinator, number_code, number_config))
                _LOGGER.info(
                    "Adding raw-field number: %s (from %s[%s])",
                    number_config.get('name', number_code),
                    raw_source,
                    number_config.get('field_index'),
                )
            else:
                # Not in the first poll yet — common on local/LAN
                # connections for large raw DPs. Keep retrying on future
                # updates instead of skipping this entity forever.
                pending.append((number_code, number_config))
                _LOGGER.debug(
                    "Raw source for dp %s (number %s) not resolvable yet, will retry",
                    number_config.get('dp_id'), number_code,
                )
            continue

        numbers.append(
            TuyaHeatpumpNumber(coordinator, number_code, number_config)
        )
        _LOGGER.info(
            "Adding number: %s (%s)",
            number_config.get('name', number_code),
            number_code
        )

    # Temperature sensor calibration offsets: a local (HA-side) Number
    # entity per temperature sensor so the user can nudge a probe that
    # reads a little high or low. Unlike TuyaHeatpumpNumber these write
    # nothing to the device — they only adjust the sensor's reported
    # value on the Home Assistant side.
    for sensor_code, sensor_config in coordinator.model_mapping.get("sensors", {}).items():
        if sensor_config.get("device_class") != "temperature":
            continue
        numbers.append(
            TuyaHeatpumpCalibrationNumber(coordinator, sensor_code, sensor_config)
        )
        _LOGGER.info(
            "Adding temperature calibration offset: %s (%s)",
            sensor_config.get('name', sensor_code),
            sensor_code,
        )

    async_add_entities(numbers)
    watch_pending_raw_entities(
        config_entry, coordinator, async_add_entities,
        pending, TuyaHeatpumpNumber, _LOGGER,
    )


class TuyaHeatpumpNumber(NumberEntity):
    """Representation of a Tuya Heatpump Number."""

    def __init__(
        self,
        coordinator: TuyaScaleDataUpdateCoordinator,
        number_code: str,
        config: dict
    ) -> None:
        """Initialize the number."""
        self.coordinator = coordinator
        self._number_code = number_code
        self._config = config
        
        # Device name ile unique_id oluştur
        device_name_slug = coordinator.device_name.lower().replace(" ", "_").replace("-", "_")
        self._attr_unique_id = f"{device_name_slug}_{number_code}"
        
        self._attr_name = config.get('name', number_code)
        self._attr_icon = config.get('icon')
        self._attr_native_unit_of_measurement = config.get('unit')
        self._attr_native_min_value = config.get('min_value', 0.0)
        self._attr_native_max_value = config.get('max_value', 100.0)
        self._attr_native_step = config.get('step', 1.0)
        self._attr_has_entity_name = True
        self._attr_mode = NumberMode.BOX
        apply_common_entity_attrs(self, config)
        # Real Tuya code used for data lookups and writes (normally the
        # dict key; discovery may have to use a different key).
        self._lookup_code = config.get("code", number_code)

        # Device info
        self._attr_device_info = coordinator.device_info

    @property
    def device_info(self):
        """Return device info."""
        return self.coordinator.device_info

    @property
    def native_min_value(self) -> float:
        """The minimum, per operating mode where the model gives one.

        ``min_value_by_mode`` maps a raw ``mode`` value to the minimum the
        device accepts in that mode: a water set-point that cools down to
        a few degrees may still refuse anything under 25 °C while heating.
        """
        by_mode = self._config.get("min_value_by_mode")
        if by_mode and self.coordinator.data:
            mode = (self.coordinator.data.get("mode") or {}).get("value")
            if mode in by_mode:
                return float(by_mode[mode])
        return self._attr_native_min_value

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if "field_index" in self._config:
            raw_source = resolve_raw_source(self.coordinator, self._config)
            if raw_source is None or not self.coordinator.data or raw_source not in self.coordinator.data:
                return None
            b64_value = self.coordinator.data[raw_source].get('value')
            raw_value = decode_raw_field(
                b64_value,
                self._config['field_index'],
                self._config.get('encoding', 'int32_be'),
            )
            if raw_value is None:
                return None
            conversion = Conversion(self._config.get('conversion', 'value'))
            try:
                result = conversion.convert(raw_value)
                return float(result) if isinstance(result, (int, float)) else result
            except Exception as err:
                _LOGGER.warning("Conversion failed for raw %s: %s", self._number_code, err)
                return raw_value

        if not self.coordinator.data or self._lookup_code not in self.coordinator.data:
            return None
            
        raw_value = self.coordinator.data[self._lookup_code]['value']

        conversion = Conversion(self._config.get('conversion', 'value'))
        try:
            result = conversion.convert(raw_value)
            return float(result) if isinstance(result, (int, float)) else result
        except Exception as err:
            _LOGGER.warning("Conversion failed for %s: %s", self._number_code, err)
            return raw_value

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        _LOGGER.info("Attempting to set %s to %s %s", 
                    self._number_code, value, self._attr_native_unit_of_measurement)
        
        api_value = value
        if (api_conversion := self._config.get('api_conversion')) is not None:
            conversion = Conversion(api_conversion)
            try:
                api_value = conversion.convert(value)
                _LOGGER.debug("Converted HA value %s → API value %s", value, api_value)
            except Exception as err:
                _LOGGER.warning("API conversion failed: %s", err)

        if "field_index" in self._config:
            raw_source = resolve_raw_source(self.coordinator, self._config)
            if raw_source is None:
                raise HomeAssistantError(
                    f"{self._config.get('name', self._number_code)}: raw source not resolved yet"
                )
            success = await self.coordinator.send_raw_field_command(
                raw_source,
                self._config['field_index'],
                self._config.get('encoding', 'int32_be'),
                api_value,
            )
        else:
            success = await self.coordinator.send_command(self._lookup_code, api_value)
        
        if success:
            _LOGGER.info("✅ Successfully set %s to %s", self._number_code, value)
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.warning("❌ Failed to set %s to %s", self._number_code, value)
            
            raise HomeAssistantError(
                f"{self._config.get('name', self._number_code)} Cannot change value of. "
                f"Your device does not allow changing this setting. "
                f"Please change the setting on the device."
            )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Tuya DP ID ve Code bilgilerini attributes'a ekle."""
        attrs: dict[str, Any] = {}

        if "field_index" in self._config:
            raw_source = resolve_raw_source(self.coordinator, self._config)
            attrs["tuya_code"] = raw_source or "<unknown>"
            attrs["tuya_dp_id"] = self._config.get("dp_id")
            attrs["raw_field_index"] = self._config.get("field_index")
            attrs["raw_encoding"] = self._config.get("encoding", "int32_be")
        else:
            dp_info = self.coordinator.get_tuya_dp_info(self._lookup_code)
            attrs["tuya_code"] = dp_info["code"]
            attrs["tuya_dp_id"] = dp_info["dp_id"]

        if self.coordinator.model_id:
            attrs["tuya_model_id"] = self.coordinator.model_id

        if self._config and isinstance(self._config, dict):
            if "values" in self._config:
                attrs["tuya_values"] = self._config["values"]

        attrs.update(common_extra_attrs(self._config))
        return attrs

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if "field_index" in self._config:
            raw_source = resolve_raw_source(self.coordinator, self._config)
            return (
                self.coordinator.last_update_success and
                self.coordinator.data is not None and
                raw_source is not None and
                raw_source in self.coordinator.data
            )

        return (
            self.coordinator.last_update_success and 
            self.coordinator.data is not None and
            self._lookup_code in self.coordinator.data
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )


class TuyaHeatpumpCalibrationNumber(NumberEntity, RestoreEntity):
    """Local calibration offset for a temperature sensor.

    Adjusts what the corresponding temperature sensor reports on the
    Home Assistant side only; nothing is written to the device. The value
    is persisted through RestoreEntity, so it survives HA restarts and
    integration reloads (on setup the restored value is re-published to
    the coordinator, which the sensor reads).
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:thermometer-chevron-up"

    def __init__(
        self,
        coordinator: TuyaScaleDataUpdateCoordinator,
        sensor_code: str,
        sensor_config: dict,
    ) -> None:
        """Initialize the calibration offset number."""
        self.coordinator = coordinator
        self._sensor_code = sensor_code
        self._sensor_config = sensor_config
        self._offset = 0.0

        device_name_slug = coordinator.device_name.lower().replace(" ", "_").replace("-", "_")
        self._attr_unique_id = f"{device_name_slug}_{sensor_code}_calibration_offset"
        self._attr_name = f"{sensor_config.get('name', sensor_code)} Calibration Offset"
        self._attr_native_unit_of_measurement = sensor_config.get('unit', '°C')
        self._attr_native_min_value = -10.0
        self._attr_native_max_value = 10.0
        self._attr_native_step = 0.1
        self._attr_device_info = coordinator.device_info
        # A sensor the model file marks disabled-by-default should not
        # ship an enabled calibration offset next to it.
        apply_common_entity_attrs(self, sensor_config)

    @property
    def device_info(self):
        """Return device info."""
        return self.coordinator.device_info

    @property
    def native_value(self) -> float:
        """Return the current calibration offset."""
        return self._offset

    async def async_set_native_value(self, value: float) -> None:
        """Set the calibration offset and re-render the sensor."""
        self._offset = float(value)
        self.coordinator.set_sensor_offset(self._sensor_code, self._offset)

    async def async_added_to_hass(self) -> None:
        """Restore the offset from the previous session, if any."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._offset = float(last_state.state)
            except (ValueError, TypeError):
                self._offset = 0.0
        self.coordinator.set_sensor_offset(self._sensor_code, self._offset)
