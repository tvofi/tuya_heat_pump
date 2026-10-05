"""Model mapping for Rotenso Windmi heat pump (modelId: 000004k4z6)."""

MODEL_NAME = "Rotenso Windmi Heat Pump (000004k4z6)"
# ====================================================
# Rotenso Windmi (GCHV / Giwee monoblock) @tvofi
# modelId: 000004k4z6
#
# Rotenso Windmi monoblocks (WIM40X1..WIM160X3) are built by GCHV
# (Guangdong Carrier Heating, Ventilation & Air Conditioning, formerly
# Chigo HVAC; brand "Giwee"), NOT by Midea, even though several of the
# Tuya codes below re-use Midea-style sensor labels (T3, T4, T5, T1B, Tw2).
# The same Tuya firmware (dp 1..109, identical codes and Chinese names)
# is also found on the Fisher air-to-water unit documented in
# make-all/tuya-local issue #1870 (modelId 0000021k4c). The Chinese DP
# names from the device's own schema (issue #60 dump) are authoritative:
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
# The schema contains exactly these 25 data points and no installer
# parameters (backup heater, tank heater, double zone, curves, ambient
# limits ...). Those are only reachable over the unit's Modbus RTU port
# (A/B/E terminals, GCHV register table in the installation manual,
# pages 122-123): see docs/modbus/README.md.
#
# Notes:
#   - Tw2 (dp 114) and T1B (dp 116) return a -30 sentinel when the probe
#     is not wired; they are shown as unknown in that case.
#   - Temperatures use scale=0 (device model spec, confirmed by user):
#     values are already in °C, no conversion needed.
#   - POWER (dp 108) is named 能需 ("energy demand") in the Tuya schema,
#     scale 1 (raw ÷ 10) and has no unit; its min/max are a copy of the
#     temperature template. It is the capacity demand in HPx10 (see the
#     GCHV controller manual), exposed in HP without a unit. The
#     "heating_output_estimate" sensor maps it to estimated thermal kW
#     and "power_estimate" to an estimated electrical draw (COP
#     modelled from T4 and leaving-water temperature), see their
#     comments.
#   - fault (dp 20) is a 16-bit bitmap whose labels in the Tuya schema
#     are E0..E9, P0..P5. The Fault Description sensor reports the codes
#     only; look them up in the Windmi user manual's error table (the
#     GCHV meanings differ from Midea's, e.g. P0 = IPM/IGBT over-current,
#     P1 = phase loss).
#   - timer (dp 16) is a raw DP that comes without a value field
#     (handled safely by the coordinator). Register discovery exposes
#     it as a disabled diagnostic sensor.
#   - Everything not listed here that the device reports is exposed
#     automatically by discovery.py (see "auto_discovery" option).
# ====================================================

_ON_VALUES = "value in [1, True, '1', 'true', 'on', 'yes', 'enable', 'open']"

# Fault bitmap bit order from the Tuya schema: E0..E9, P0..P5 (codes only;
# see the Windmi user manual for the meaning of each code).
_FAULT_BITS = [(1 << i, label) for i, label in enumerate(
    ["E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9",
     "P0", "P1", "P2", "P3", "P4", "P5"]
)]
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
    "heating_output_estimate": {
        # Derived: dp 108 能需 is the capacity demand in HPx10 — per the
        # GCHV wired-controller manual (query item 4 "Capacity of unit:
        # HPx10", item 27 "Capacity demand", no unit given there), so
        # this entity's value after the /10 conversion is demand in HP,
        # maxing at the unit's rating (5.0 on the WIM140). Thermal
        # output estimate = HP x (rated kW / rated HP): the WIM140 is
        # 5 HP / 14 kW -> factor 2.8; other Windmi sizes should use
        # rated_kW / rated_HP. In cooling mode the same factor
        # approximates the cooling capacity. During reverse-cycle
        # defrost (DEF / dp 102 true) no useful heat reaches the water,
        # so the output drops to 0 for those minutes; DEF is
        # report-on-change and can fall out of the cloud shadow when
        # stale, so it defaults to "not defrosting". Refrigerant circuit
        # only: the backup heater (dp 15), DHW tank heater (dp 7) and
        # standby (~20-50 W) are invisible to it.
        "name": "Estimated Heating Output",
        "unit": "kW",
        "icon": "mdi:radiator",
        "device_class": "power",
        "state_class": "measurement",
        "formula": "(POWER * 2.8) * (1 - DEF)",
        "formula_defaults": {"DEF": 0},
        "precision": 2,
    },
    "power_estimate": {
        # Derived: electrical power-draw estimate = heating output
        # divided by a COP modelled from live conditions:
        #   COP = 5.99 + 0.141*T4 - 0.07*Tout - 0.0016*T4*Tout
        # least-squares fitted (rms 0.18 COP) to the official WIM140X3
        # performance table's nominal-level heating grid (T4 -25..35,
        # LWT 30..63; "Tabela wydajności" WIM140X3 R14), with T4 = dp 105
        # and Tout = dp 106 standing in for the table's LWT. Clamped to
        # 1..7 against extrapolation. The fit has no EER terms, so
        # cooling (mode / dp 2 == cool) stays unknown — except during
        # defrost (DEF / dp 102), when the estimate holds at the
        # max-level input, a consistent ~1.15x the nominal PI. heat /
        # DHW / HEATDHW always estimate: the heating setpoint floor is
        # 25 °C, so Tout <= 25 is normal in those modes and is not a
        # cooling signal. COOLDHW, and a mode absent from the poll
        # (default None), keep the Tout > 25 test. DEF defaults to not
        # defrosting when that DP has left the cloud shadow. Real COP
        # also depends on part load, so expect ~10-15% scatter versus
        # a meter. Same compressor-only blind spots as
        # heating_output_estimate (dp 15 / dp 7 heaters and standby
        # are invisible).
        "name": "Estimated Power Draw",
        "unit": "kW",
        "icon": "mdi:flash",
        "device_class": "power",
        "state_class": "measurement",
        "formula": (
            "(POWER * 2.8 / max(1.0, min(7.0, "
            "5.99 + 0.141 * T4 - 0.07 * Tout - 0.0016 * T4 * Tout))"
            " * (1.15 if DEF else 1)) if ("
            "mode in ('heat', 'DHW', 'HEATDHW') or "
            "(mode == 'COOLDHW' and Tout > 25) or "
            "(mode is None and Tout > 25) or DEF) else None"
        ),
        "formula_defaults": {"DEF": 0, "mode": None},
        "precision": 2,
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
        # Tuya name 夜间模式 = night (silent) mode. The unit reports this
        # DP only on change: its shadow entry was last refreshed
        # 2026-06-20 and by Oct 2026 it had fallen out of the cloud
        # shadow entirely — the toggle vanished from the Tuya app panel
        # and the switch went unavailable in HA. The DP is rw in the
        # thing model, so writing it once (this switch, or the write_dp
        # service) makes the device report it again. Entities for DPs
        # the schema knows stay available (state "unknown") while their
        # value is missing from the poll data, so this recovery works
        # from HA (see coordinator.dp_known).
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
        # Heating water: the unit refuses anything under 25 °C in heating
        # (it keeps the old value, @tvofi). The 5 °C floor is for cooling.
        "min_value_by_mode": {"heat": 25.0, "HEATDHW": 25.0, "DHW": 25.0},
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
