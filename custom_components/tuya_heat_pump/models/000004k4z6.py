"""Model mapping for Rotenso Windmi heat pump (modelId: 000004k4z6)."""

MODEL_NAME = "Rotenso Windmi Heat Pump (000004k4z6)"
# ====================================================
# Rotenso Windmi (Midea M-Thermal OEM) @tvofi
# modelId: 000004k4z6
#
# Rotenso Windmi units are re-badged Midea M-Thermal (Arctic/Nature
# mono) heat pumps and use Midea's Tuya firmware. The very same DP set
# (dp 1..109, identical codes and Chinese names) is exposed by other
# Midea OEM brands -- e.g. the Fisher air-to-water unit documented in
# make-all/tuya-local issue #1870 (modelId 0000021k4c). Tuya's own
# Chinese DP names from that schema were used to correct several
# labels that were guessed from the English codes alone:
#
#   dp  code             Tuya name (zh)   meaning
#   --  ---------------  ---------------  ----------------------------------
#    1  switch           开关              Power
#    2  mode             模式              cool / heat / DHW / COOLDHW / HEATDHW
#    4  disinfection     杀菌模式          DHW anti-legionella (disinfect) mode
#    7  switch_microwave 水箱电加热        DHW tank electric (booster) heater
#    9  temp_set         温度设置          Heating/cooling water setpoint
#   10  temp_current     总出水温度        Total outlet water temp  (Midea T1)
#   15  instant_heating  电加热            Electric (backup) heater
#   16  timer            定时              Timer schedule (raw blob, 128 B)
#   20  fault            故障告警          Fault bitmap E0..E9, P0..P5
#   26  temp_current_f   水箱温度          DHW tank temperature (NOT °F!)
#  101  Tin              换热器进水温度    Plate HX water inlet   (Midea TW_in)
#  102  DEF              强制除霜          Forced defrost (rw)
#  104  DHWSET           生活热水设定      DHW setpoint
#  105  T4               室外环境温度      Outdoor ambient temperature
#  106  Tout             换热器出水温度    Plate HX water outlet  (Midea TW_out)
#  107  T6               线控器温度        Wired controller (room) temperature
#  108  POWER            能需              Energy demand, scale 1, no unit (see note)
#  109  WP_speed         水泵档位          Water pump gear (level, no unit)
#  110  night_mode       夜间模式          Night (silent) mode          (Rotenso extra)
#  111  T5               排气温度          Compressor discharge temperature (Rotenso extra)
#  112  TL               冷媒散热管温      Refrigerant (condenser) pipe temp (Rotenso extra)
#  113  T9               IPM模块温度       Inverter (IPM) module temperature (Rotenso extra)
#  114  Tw2              第二温区出水温度  Zone 2 outlet water temperature (Rotenso extra)
#  115  T3               管温              Coil (pipe) temperature      (Rotenso extra)
#  116  T1B              外部热源出口温度  External heat source outlet temp (Rotenso extra)
#
# The dp 110..116 names come from the device's own Tuya schema (issue #60
# dump, tuya_device_data_20260707_224248.txt). Note that Rotenso's Tuya
# firmware re-uses Midea sensor labels for other probes: "T5" here is the
# compressor discharge temperature (排气温度), not the DHW tank (which is
# dp 26), and "T9" is the inverter module temperature.
#
# The schema contains exactly these 25 data points and no installer /
# FOR SERVICEMAN parameters (backup heater, tank heater, double zone,
# curves, T4 limits ...). Those are only reachable over the indoor
# unit's Modbus port: see docs/modbus/README.md.
#
# Notes:
#   - Tw2 (dp 114) and T1B (dp 116) return a -30 sentinel when the probe
#     is not wired; they are shown as unknown in that case.
#   - Temperatures use scale=0 (device model spec, confirmed by user):
#     values are already in °C, no conversion needed.
#   - POWER (dp 108) is named 能需 ("energy demand") in the Tuya schema,
#     scale 1 (raw ÷ 10) and has no unit; its min/max are a copy of the
#     temperature template. It is a load/demand level, not a metered
#     electrical power, so it is exposed without a unit.
#   - fault (dp 20) is a 16-bit bitmap whose labels in the Tuya schema
#     are E0..E9, P0..P5. The meanings below follow Midea's M-Thermal
#     error table; check the Rotenso manual if a code looks off.
#   - timer (dp 16) is a raw DP that comes without a value field
#     (handled safely by the coordinator). Register discovery exposes
#     it as a disabled diagnostic sensor.
#   - Everything not listed here that the device reports is exposed
#     automatically by discovery.py (see "auto_discovery" option).
# ====================================================

_ON_VALUES = "value in [1, True, '1', 'true', 'on', 'yes', 'enable', 'open']"

# Midea M-Thermal fault table (Tuya bitmap bit order: E0..E9, P0..P5).
_FAULT_BITS = [
    (1 << 0, "E0 water flow failure"),
    (1 << 1, "E1 phase sequence error"),
    (1 << 2, "E2 controller / hydraulic module communication error"),
    (1 << 3, "E3 outlet water temp sensor T1 error"),
    (1 << 4, "E4 DHW tank temp sensor T5 error"),
    (1 << 5, "E5 outdoor coil temp sensor T3 error"),
    (1 << 6, "E6 outdoor ambient temp sensor T4 error"),
    (1 << 7, "E7 buffer tank sensor Tbt1 error"),
    (1 << 8, "E8 water flow failure (3x)"),
    (1 << 9, "E9 suction temp sensor Th error"),
    (1 << 10, "P0 low pressure protection"),
    (1 << 11, "P1 high pressure protection"),
    (1 << 12, "P2 protection"),
    (1 << 13, "P3 compressor over-current protection"),
    (1 << 14, "P4 discharge temperature too high"),
    (1 << 15, "P5 water inlet/outlet temperature difference too high"),
]
_FAULT_CONVERSION = (
    "', '.join(n for b, n in ["
    + ", ".join(f"({bit}, {label!r})" for bit, label in _FAULT_BITS)
    + "] if value & b) or 'OK'"
)

SENSOR_TYPES = {
    # ---- Water loop temperatures ----
    "temp_current": {
        "dp_id": 10,
        "code": "temp_current",
        "name": "Outlet Water Temperature (T1)",
        "unit": "°C",
        "icon": "mdi:thermometer-water",
        "device_class": "temperature",
        "state_class": "measurement",
    },
    "Tin": {
        "dp_id": 101,
        "code": "Tin",
        "name": "Heat Exchanger Inlet Water Temperature (Tin)",
        "unit": "°C",
        "icon": "mdi:thermometer-water",
        "device_class": "temperature",
        "state_class": "measurement",
    },
    "Tout": {
        "dp_id": 106,
        "code": "Tout",
        "name": "Heat Exchanger Outlet Water Temperature (Tout)",
        "unit": "°C",
        "icon": "mdi:thermometer-water",
        "device_class": "temperature",
        "state_class": "measurement",
    },
    "T1B": {
        # Tuya name 外部热源出口温度 = external heat source (AHS) outlet temperature
        "dp_id": 116,
        "code": "T1B",
        "name": "External Heat Source Outlet Temperature (T1B)",
        "unit": "°C",
        "icon": "mdi:thermometer-water",
        "device_class": "temperature",
        "state_class": "measurement",
        # -30 sentinel = probe not wired
        "conversion": "value if value > -30 else None",
    },
    "Tw2": {
        # Tuya name 第二温区出水温度 = zone 2 outlet water temperature
        "dp_id": 114,
        "code": "Tw2",
        "name": "Zone 2 Outlet Water Temperature (Tw2)",
        "unit": "°C",
        "icon": "mdi:thermometer-water",
        "device_class": "temperature",
        "state_class": "measurement",
        # -30 sentinel = probe not wired
        "conversion": "value if value > -30 else None",
    },
    "water_delta_t": {
        # Derived: plate heat exchanger water ΔT (outlet − inlet).
        # Positive while heating, negative while cooling.
        "name": "Heat Exchanger Water ΔT",
        "unit": "°C",
        "icon": "mdi:delta",
        "state_class": "measurement",
        "formula": "Tout - Tin",
        "precision": 1,
    },

    # ---- DHW ----
    "temp_current_f": {
        # Tuya name 水箱温度 = tank temperature. The English code suggests
        # °F but the value is the DHW tank in °C (same as T5 on dp 111).
        "dp_id": 26,
        "code": "temp_current_f",
        "name": "DHW Tank Temperature",
        "unit": "°C",
        "icon": "mdi:water-thermometer",
        "device_class": "temperature",
        "state_class": "measurement",
    },
    "T5": {
        # Tuya name 排气温度 = compressor discharge temperature (Midea Tp),
        # despite the Midea-style "T5" code.
        "dp_id": 111,
        "code": "T5",
        "name": "Compressor Discharge Temperature (T5)",
        "unit": "°C",
        "icon": "mdi:thermometer-high",
        "device_class": "temperature",
        "state_class": "measurement",
    },

    # ---- Outdoor unit / refrigerant ----
    "T4": {
        "dp_id": 105,
        "code": "T4",
        "name": "Outdoor Ambient Temperature (T4)",
        "unit": "°C",
        "icon": "mdi:sun-thermometer-outline",
        "device_class": "temperature",
        "state_class": "measurement",
    },
    "T3": {
        # Tuya name 管温 = pipe/coil temperature
        "dp_id": 115,
        "code": "T3",
        "name": "Coil Temperature (T3)",
        "unit": "°C",
        "icon": "mdi:thermometer-lines",
        "device_class": "temperature",
        "state_class": "measurement",
    },
    "TL": {
        # Tuya name 冷媒散热管温 = refrigerant heat-dissipation pipe temperature
        "dp_id": 112,
        "code": "TL",
        "name": "Refrigerant Pipe Temperature (TL)",
        "unit": "°C",
        "icon": "mdi:thermometer-lines",
        "device_class": "temperature",
        "state_class": "measurement",
    },
    "T9": {
        # Tuya name IPM模块温度 = inverter power module temperature
        "dp_id": 113,
        "code": "T9",
        "name": "Inverter Module Temperature (T9)",
        "unit": "°C",
        "icon": "mdi:chip",
        "device_class": "temperature",
        "state_class": "measurement",
    },

    # ---- Room ----
    "T6": {
        "dp_id": 107,
        "code": "T6",
        "name": "Wired Controller Temperature (T6)",
        "unit": "°C",
        "icon": "mdi:home-thermometer-outline",
        "device_class": "temperature",
        "state_class": "measurement",
    },

    # ---- Electrical & pump ----
    "POWER": {
        # 能需 = energy demand (load level), scale 1, no unit in the schema
        "dp_id": 108,
        "code": "POWER",
        "name": "Energy Demand (POWER)",
        "icon": "mdi:gauge",
        "state_class": "measurement",
        "conversion": "value / 10",
    },
    "WP_speed": {
        # 水泵档位 = water pump gear (level), no unit in the schema
        "dp_id": 109,
        "code": "WP_speed",
        "name": "Water Pump Gear",
        "icon": "mdi:water-pump",
        "state_class": "measurement",
    },

    # ---- Faults ----
    # Human-readable view of the fault bitmap (dp 20). Lists every
    # active code, "OK" when clear.
    "fault_description": {
        "dp_id": 20,
        "code": "fault",
        "name": "Fault Description",
        "icon": "mdi:alert-circle-outline",
        "conversion": _FAULT_CONVERSION,
    },

    # ---- Raw / undecoded ----
    # Timer schedule blob (dp 16, raw, up to 128 bytes, rw). Layout not
    # decoded yet: watch it change in test/raw_explorer.py while editing
    # the schedule in the Tuya app, then map fields with field_index /
    # encoding entries (see docs/MAPPING_REGISTERS.md). Shown base64,
    # disabled by default.
    "timer": {
        "dp_id": 16,
        "code": "timer",
        "name": "Timer Schedule (raw)",
        "icon": "mdi:code-brackets",
        "entity_category": "diagnostic",
        "enabled_default": False,
    },
}

# ====================================================
# BINARY SENSOR TYPES
# ====================================================
BINARY_SENSOR_TYPES = {
    "fault": {
        "dp_id": 20,
        "code": "fault",
        "name": "Fault Alarm",
        "device_class": "problem",
        "conversion": "value != 0",
    },
    "DEF": {
        "dp_id": 102,
        "code": "DEF",
        "name": "Defrosting",
        "device_class": "cold",
        "conversion": _ON_VALUES,
    },
}

# ====================================================
# SWITCH TYPES
# ====================================================
SWITCH_TYPES = {
    "switch": {
        "dp_id": 1,
        "code": "switch",
        "name": "Power",
        "icon": "mdi:power",
        "conversion": _ON_VALUES,
    },
    "disinfection": {
        "dp_id": 4,
        "code": "disinfection",
        "name": "DHW Disinfection (Anti-Legionella)",
        "icon": "mdi:shield-check",
        "conversion": _ON_VALUES,
    },
    "switch_microwave": {
        # Tuya name 水箱电加热 = DHW tank electric heater (the code name
        # "microwave" is a Tuya template artefact).
        "dp_id": 7,
        "code": "switch_microwave",
        "name": "DHW Tank Electric Heater",
        "icon": "mdi:water-boiler",
        "conversion": _ON_VALUES,
    },
    "instant_heating": {
        # Tuya name 电加热 = electric heater: manual backup heater request
        # (wired controller "BACKUP HEATER" function).
        "dp_id": 15,
        "code": "instant_heating",
        "name": "Electric Backup Heater",
        "icon": "mdi:heating-coil",
        "conversion": _ON_VALUES,
    },
    "force_defrost": {
        # Same DP as the "Defrosting" binary sensor; the Tuya schema
        # marks it rw (强制除霜 = forced defrost), so it can also be
        # triggered manually.
        "dp_id": 102,
        "code": "DEF",
        "name": "Force Defrost",
        "icon": "mdi:snowflake-melt",
        "conversion": _ON_VALUES,
        "entity_category": "config",
    },
    "night_mode": {
        "dp_id": 110,
        "code": "night_mode",
        "name": "Night Mode (Silent)",
        "icon": "mdi:weather-night",
        "conversion": _ON_VALUES,
    },
}

# ====================================================
# NUMBER TYPES
# ====================================================
NUMBER_TYPES = {
    "temp_set": {
        "dp_id": 9,
        "code": "temp_set",
        "name": "Water Temperature Setpoint",
        "icon": "mdi:thermostat",
        "unit": "°C",
        "min_value": 5.0,
        "max_value": 65.0,
        "step": 1.0,
        "api_conversion": "int(value)",
    },
    "DHWSET": {
        "dp_id": 104,
        "code": "DHWSET",
        "name": "DHW Setpoint",
        "icon": "mdi:water-thermometer",
        "unit": "°C",
        "min_value": 40.0,
        "max_value": 65.0,
        "step": 1.0,
        "api_conversion": "int(value)",
    },
}

# ====================================================
# SELECT TYPES
# ====================================================
SELECT_TYPES = {
    "mode": {
        "dp_id": 2,
        "code": "mode",
        "name": "Operation Mode",
        "icon": "mdi:hvac",
        "options": {
            "cool": "Cooling",
            "heat": "Heating",
            "DHW": "DHW (Hot Water)",
            "COOLDHW": "Cooling + DHW",
            "HEATDHW": "Heating + DHW",
        },
    },
}
