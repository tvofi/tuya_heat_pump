#!/usr/bin/env python3
"""Generate a Home Assistant package exposing the Midea M-Thermal Modbus
register map (installer / "FOR SERVICEMAN" parameters included).

Why this exists
---------------
Rotenso Windmi, Kaisai, Fisher, Airwell, Ferroli, Inventor ... are Midea
M-Thermal OEMs. Their Tuya Wi-Fi module only exposes ~25 data points
(mode, setpoints, a handful of temperatures). The installer parameters --
backup-heater enable/thresholds, DHW tank heater, double zone, weather
curves, T4 limits, disinfection, holiday, pump delays -- are NOT in the
Tuya schema. They ARE available on the indoor unit's Modbus RTU port
(H1/H2 on the wired controller), which is what this package uses.

The register map is derived from the community ESPHome project
https://github.com/Mosibi/Midea-heat-pump-ESPHome (Apache-2.0), cross-
checked against the Warm-Energy Heat-Pump-Modbus-Database and the Midea
wired-controller manual (FOR SERVICEMAN menu). Registers 0..272 apply to
R32 units; 148..199 and 273..288 are R290-generation additions and are
emitted only with --r290.

Usage
-----
    python tools/gen_modbus_package.py            > docs/modbus/midea_mthermal_r32.yaml
    python tools/gen_modbus_package.py --r290     > docs/modbus/midea_mthermal_r290.yaml

Copy the file into <config>/packages/ (enable `homeassistant: packages:
!include_dir_named packages`), adjust the `modbus:` hub (serial port or
TCP gateway) and restart. Only the standard `modbus` and `template`
integrations are used; no custom component is required.

Design
------
* Every register is polled by a `modbus` sensor. Plain read-only values
  get their final name/unit directly. Writable, packed (two values per
  register) and bitmap registers are read as raw sensors named
  "HP MB R<addr>" and turned into friendly entities with templates.
* Writes go through `modbus.write_register`; packed/bit registers are
  read-modify-written from the raw sensor and guarded so that nothing is
  written while the raw value is unknown. After a write the raw sensor
  is refreshed immediately with `homeassistant.update_entity`.
* Only YAML keys accepted by Home Assistant 2024.3+ are used (`service:`
  instead of `action:`, legacy `switch: platform: template`).
"""
from __future__ import annotations

import argparse
import re
import sys

import yaml

HUB = "heatpump"
SLAVE = 1
PREFIX = "HP"                 # entity name prefix
SCAN_STATUS = 30              # s, live values
SCAN_CONFIG = 120             # s, settings that rarely change
SCAN_RAW = 30                 # s, bitmaps used by switches (need fresh state)


def slug(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def raw_name(addr: int) -> str:
    return f"{PREFIX} MB R{addr}"


def raw_entity(addr: int) -> str:
    return "sensor." + slug(raw_name(addr))


def nice(name: str) -> str:
    return f"{PREFIX} {name}"


# ---------------------------------------------------------------------------
# Register tables
# ---------------------------------------------------------------------------

# Read-only value registers exposed directly as modbus sensors.
# (addr, name, data_type, unit, device_class, state_class, scale, precision, scan, r290_only)
VALUE_SENSORS = [
    (10,  "t_SG_MAX (smart grid max run time)", "uint16", "h", None, None, 1, 0, SCAN_CONFIG, False),
    (100, "Compressor frequency", "uint16", "Hz", "frequency", "measurement", 1, 0, SCAN_STATUS, False),
    (102, "Fan speed", "uint16", "rpm", None, "measurement", 1, 0, SCAN_STATUS, False),
    (103, "Expansion valve opening (PMV)", "uint16", "steps", None, "measurement", 1, 0, SCAN_STATUS, False),
    (104, "Water inlet temperature Tw_in", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (105, "Water outlet temperature Tw_out", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (106, "Outdoor coil temperature T3", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (107, "Outdoor ambient temperature T4", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (108, "Compressor discharge temperature Tp", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (109, "Compressor suction temperature Th", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (110, "Total outlet water temperature T1", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (111, "Outlet water after backup heater T1B", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (112, "Refrigerant liquid temperature T2", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (113, "Refrigerant gas temperature T2B", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (114, "Room temperature Ta", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (115, "DHW tank temperature T5", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (116, "High pressure", "uint16", "kPa", "pressure", "measurement", 1, 0, SCAN_STATUS, False),
    (117, "Low pressure", "uint16", "kPa", "pressure", "measurement", 1, 0, SCAN_STATUS, False),
    (118, "Outdoor unit current", "uint16", "A", "current", "measurement", 1, 0, SCAN_STATUS, False),
    (119, "Outdoor unit voltage", "uint16", "V", "voltage", "measurement", 1, 0, SCAN_STATUS, False),
    (120, "Buffer tank upper temperature Tbt1", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (121, "Buffer tank lower temperature Tbt2", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (122, "Compressor operating hours", "uint16", "h", "duration", "total_increasing", 1, 0, SCAN_CONFIG, False),
    (123, "Unit capacity code", "uint16", None, None, None, 1, 0, SCAN_CONFIG, False),
    (130, "Hydraulic module software version", "uint16", None, None, None, 1, 0, SCAN_CONFIG, False),
    (131, "Wired controller software version", "uint16", None, None, None, 1, 0, SCAN_CONFIG, False),
    (132, "Compressor target frequency", "uint16", "Hz", "frequency", "measurement", 1, 0, SCAN_STATUS, False),
    (133, "DC bus current", "uint16", "A", "current", "measurement", 1, 0, SCAN_STATUS, False),
    (134, "DC bus voltage", "uint16", "V", "voltage", "measurement", 10, 0, SCAN_STATUS, False),
    (135, "Inverter module temperature TF", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (136, "Weather curve target T1S zone 1", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (137, "Weather curve target T1S zone 2", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (138, "Water flow", "uint16", "m³/h", None, "measurement", 0.01, 2, SCAN_STATUS, False),
    (139, "Outdoor unit current limit scheme", "uint16", None, None, None, 1, 0, SCAN_CONFIG, False),
    (140, "Hydraulic module capacity", "uint16", "kW", "power", "measurement", 0.01, 2, SCAN_STATUS, False),
    (141, "Solar temperature Tsolar", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, False),
    (143, "Electricity consumption (counter)", "uint32", "kWh", "energy", "total_increasing", 1, 0, SCAN_CONFIG, False),
    (145, "Heat output (counter)", "uint32", "kWh", "energy", "total_increasing", 1, 0, SCAN_CONFIG, False),
    # R290 energy metering block
    (148, "Real-time heating capacity", "uint16", "kW", "power", "measurement", 0.01, 2, SCAN_STATUS, True),
    (149, "Real-time renewable heating capacity", "uint16", "kW", "power", "measurement", 0.01, 2, SCAN_STATUS, True),
    (150, "Real-time heating power consumption", "uint16", "kW", "power", "measurement", 0.01, 2, SCAN_STATUS, True),
    (151, "Real-time heating COP", "uint16", None, None, "measurement", 0.01, 2, SCAN_STATUS, True),
    (152, "Total heating energy produced (system)", "uint32", "kWh", "energy", "total_increasing", 0.01, 2, SCAN_CONFIG, True),
    (154, "Total heating renewable energy (system)", "uint32", "kWh", "energy", "total_increasing", 0.01, 2, SCAN_CONFIG, True),
    (156, "Total heating energy consumed (system)", "uint32", "kWh", "energy", "total_increasing", 0.01, 2, SCAN_CONFIG, True),
    (158, "Total heating energy produced (master)", "uint32", "kWh", "energy", "total_increasing", 0.01, 2, SCAN_CONFIG, True),
    (160, "Total heating renewable energy (master)", "uint32", "kWh", "energy", "total_increasing", 0.01, 2, SCAN_CONFIG, True),
    (162, "Total heating energy consumed (master)", "uint32", "kWh", "energy", "total_increasing", 0.01, 2, SCAN_CONFIG, True),
    (164, "Total heating COP (master)", "uint16", None, None, "measurement", 0.01, 2, SCAN_CONFIG, True),
    (165, "Total cooling energy produced (master)", "uint32", "kWh", "energy", "total_increasing", 0.01, 2, SCAN_CONFIG, True),
    (167, "Total cooling renewable energy (master)", "uint32", "kWh", "energy", "total_increasing", 0.01, 2, SCAN_CONFIG, True),
    (169, "Total cooling energy consumed (master)", "uint32", "kWh", "energy", "total_increasing", 0.01, 2, SCAN_CONFIG, True),
    (171, "Total cooling EER (master)", "uint16", None, None, "measurement", 0.01, 2, SCAN_CONFIG, True),
    (172, "Total DHW energy produced (master)", "uint32", "kWh", "energy", "total_increasing", 0.01, 2, SCAN_CONFIG, True),
    (174, "Total DHW renewable energy (master)", "uint32", "kWh", "energy", "total_increasing", 0.01, 2, SCAN_CONFIG, True),
    (176, "Total DHW energy consumed (master)", "uint32", "kWh", "energy", "total_increasing", 0.01, 2, SCAN_CONFIG, True),
    (178, "Total DHW COP (master)", "uint16", None, None, "measurement", 0.01, 2, SCAN_CONFIG, True),
    (179, "Real-time renewable cooling capacity", "uint16", "kW", "power", "measurement", 0.01, 2, SCAN_STATUS, True),
    (180, "Real-time cooling capacity", "uint16", "kW", "power", "measurement", 0.01, 2, SCAN_STATUS, True),
    (181, "Real-time cooling power consumption", "uint16", "kW", "power", "measurement", 0.01, 2, SCAN_STATUS, True),
    (182, "Real-time cooling EER", "uint16", None, None, "measurement", 0.01, 2, SCAN_STATUS, True),
    (183, "Real-time DHW heating capacity", "uint16", "kW", "power", "measurement", 0.01, 2, SCAN_STATUS, True),
    (184, "Real-time renewable DHW capacity", "uint16", "kW", "power", "measurement", 0.01, 2, SCAN_STATUS, True),
    (185, "Real-time DHW power consumption", "uint16", "kW", "power", "measurement", 0.01, 2, SCAN_STATUS, True),
    (186, "Real-time DHW COP", "uint16", None, None, "measurement", 0.01, 2, SCAN_STATUS, True),
    (191, "Outdoor refrigerant pipe temperature TL", "int16", "°C", "temperature", "measurement", 1, 0, SCAN_STATUS, True),
    (192, "Internal pump PWM", "uint16", "%", None, "measurement", 0.1, 1, SCAN_STATUS, True),
    (193, "Second plate HX inlet temperature T9i", "int16", "°C", "temperature", "measurement", 0.1, 1, SCAN_STATUS, True),
    (194, "Second plate HX outlet temperature T9o", "int16", "°C", "temperature", "measurement", 0.1, 1, SCAN_STATUS, True),
    (195, "Expansion valve 2 opening", "uint16", "steps", None, "measurement", 1, 0, SCAN_STATUS, True),
    (196, "Expansion valve 3 opening", "uint16", "steps", None, "measurement", 1, 0, SCAN_STATUS, True),
    (197, "Fan 2 speed", "uint16", "rpm", None, "measurement", 1, 0, SCAN_STATUS, True),
    (205, "Room setpoint Ts upper limit", "uint16", "°C", "temperature", None, 0.5, 1, SCAN_CONFIG, False),
    (206, "Room setpoint Ts lower limit", "uint16", "°C", "temperature", None, 0.5, 1, SCAN_CONFIG, False),
    (207, "DHW setpoint upper limit", "uint16", "°C", "temperature", None, 1, 0, SCAN_CONFIG, False),
    (208, "DHW setpoint lower limit", "uint16", "°C", "temperature", None, 1, 0, SCAN_CONFIG, False),
]

# Raw registers (read as-is; consumed by template entities below).
# (addr, data_type, scan, r290_only)
RAW_REGISTERS = [
    (0, "uint16", SCAN_RAW, False),      # power / control bits
    (1, "uint16", SCAN_RAW, False),      # operating mode set
    (2, "uint16", SCAN_RAW, False),      # T1S zone1 (low) / zone2 (high)
    (3, "uint16", SCAN_RAW, False),      # Ts * 2
    (4, "uint16", SCAN_RAW, False),      # T5S
    (5, "uint16", SCAN_RAW, False),      # function bits
    (6, "uint16", SCAN_RAW, False),      # curve zone1 (low) / zone2 (high)
    (7, "uint16", SCAN_RAW, False),      # forced DHW heating (1 on / 2 off)
    (8, "uint16", SCAN_RAW, False),      # forced TBH (1 on / 2 off)
    (9, "uint16", SCAN_RAW, False),      # forced IBH1 (1 on / 2 off)
    (101, "uint16", SCAN_STATUS, False), # actual operating mode
    (124, "uint16", SCAN_STATUS, False), # current fault
    (125, "uint16", SCAN_CONFIG, False), # fault history 1
    (126, "uint16", SCAN_CONFIG, False), # fault history 2
    (127, "uint16", SCAN_CONFIG, False), # fault history 3
    (128, "uint16", SCAN_STATUS, False), # status bits 1
    (129, "uint16", SCAN_STATUS, False), # load outputs
    (142, "uint16", SCAN_CONFIG, False), # cascade slave online bits
    (187, "uint16", SCAN_CONFIG, True),  # machine type
    (190, "uint16", SCAN_CONFIG, True),  # hydraulic module sub model
    (198, "uint16", SCAN_STATUS, True),  # status bits (IBH/TBH/AHS enabled ...)
    (199, "uint16", SCAN_STATUS, True),  # operation mode
    (201, "uint16", SCAN_CONFIG, False), # T1S cooling upper limit z1 (low) / z2 (high)
    (202, "uint16", SCAN_CONFIG, False), # T1S cooling lower limit
    (203, "uint16", SCAN_CONFIG, False), # T1S heating upper limit
    (204, "uint16", SCAN_CONFIG, False), # T1S heating lower limit
    (210, "uint16", SCAN_RAW, False),    # parameter settings 1 (bits)
    (211, "uint16", SCAN_RAW, False),    # parameter settings 2 (bits)
    (269, "uint16", SCAN_CONFIG, False), # power input limitation
    (270, "uint16", SCAN_CONFIG, False), # t_T4_FRESH_H (low) / _C (high), 0.5 h units
    (272, "uint16", SCAN_CONFIG, False), # emission types, 4 nibbles
    (273, "uint16", SCAN_CONFIG, True),  # solar mode (low) / DELTATSOL (high)
    (274, "uint16", SCAN_CONFIG, True),  # bit0 EnSwitchPDC
    (277, "uint16", SCAN_CONFIG, True),  # SETHEATER max (high) / min (low)
    (278, "uint16", SCAN_CONFIG, True),  # SIGHEATER max (high) / min (low)
]

# Writable whole-register numbers.
# (addr, name, min, max, step, scale, signed, r290_only)   value = raw * scale
NUMBERS = [
    (4,   "DHW setpoint T5S (°C)", 20, 65, 1, 1, False, False),
    (209, "DHW pump run time (min)", 5, 120, 1, 1, False, False),
    (212, "dT5_ON DHW restart delta (°C)", 1, 30, 1, 1, False, False),
    (213, "dT1S5 outlet vs tank delta (°C)", 5, 40, 1, 1, False, False),
    (214, "t_INTERVAL_DHW compressor restart interval DHW (min)", 5, 30, 1, 1, False, False),
    (215, "T4DHWMAX ambient max for DHW (°C)", 35, 43, 1, 1, False, False),
    (216, "T4DHWMIN ambient min for DHW (°C)", -25, 5, 1, 1, True, False),
    (217, "t_TBH_DELAY tank heater delay (min)", 0, 240, 5, 1, False, False),
    (218, "dT5_TBH_OFF tank heater off delta (°C)", 0, 10, 1, 1, False, False),
    (219, "T4_TBH_ON ambient for tank heater (°C)", -5, 20, 1, 1, True, False),
    (220, "T5S_DI disinfection temperature (°C)", 60, 70, 1, 1, False, False),
    (221, "t_DI_MAX disinfection max duration (min)", 90, 300, 1, 1, False, False),
    (222, "t_DI_HIGHTEMP disinfection hold time (min)", 5, 60, 1, 1, False, False),
    (223, "t_INTERVAL_C compressor restart interval cooling (min)", 5, 30, 1, 1, False, False),
    (224, "dT1SC cooling water delta (°C)", 2, 10, 1, 1, False, False),
    (225, "dTSC cooling room delta (°C)", 1, 10, 1, 1, False, False),
    (226, "T4CMAX ambient max for cooling (°C)", 35, 46, 1, 1, False, False),
    (227, "T4CMIN ambient min for cooling (°C)", -5, 25, 1, 1, True, False),
    (228, "t_INTERVAL_H compressor restart interval heating (min)", 5, 60, 1, 1, False, False),
    (229, "dT1SH heating water delta (°C)", 2, 10, 1, 1, False, False),
    (230, "dTSH heating room delta (°C)", 1, 10, 1, 1, False, False),
    (231, "T4HMAX ambient max for heating (°C)", 20, 35, 1, 1, False, False),
    (232, "T4HMIN ambient min for heating (°C)", -25, 5, 1, 1, True, False),
    (233, "T4_IBH_ON ambient for backup heater IBH (°C)", -15, 10, 1, 1, True, False),
    (234, "dT1_IBH_ON backup heater IBH on delta (°C)", 1, 7, 1, 1, False, False),
    (235, "t_IBH_DELAY backup heater IBH delay (min)", 15, 120, 1, 1, False, False),
    (237, "T4_AHS_ON ambient for additional heat source (°C)", -15, 10, 1, 1, True, False),
    (238, "dT1_AHS_ON additional heat source on delta (°C)", 1, 7, 1, 1, False, False),
    (240, "t_AHS_DELAY additional heat source delay (min)", 5, 120, 1, 1, False, False),
    (241, "t_DHWHP_MAX DHW heat pump max run time (min)", 10, 600, 1, 1, False, False),
    (242, "t_DHWHP_RESTRICT DHW heat pump restrict time (min)", 10, 600, 1, 1, False, False),
    (243, "T4AUTOCMIN auto mode cooling ambient min (°C)", 20, 29, 1, 1, False, False),
    (244, "T4AUTOHMAX auto mode heating ambient max (°C)", 10, 17, 1, 1, False, False),
    (245, "T1S_H.A._H holiday heating water setpoint (°C)", 20, 29, 1, 1, False, False),
    (246, "T5S_H.A._DHW holiday DHW setpoint (°C)", 20, 25, 1, 1, False, False),
    (247, "PER_START cascade start ratio (%)", 10, 100, 10, 1, False, False),
    (248, "TIME_ADJUST cascade time adjust (min)", 1, 60, 1, 1, False, False),
    (249, "dTbt2 buffer tank delta (°C)", 0, 50, 1, 1, False, False),
    (250, "P_IBH1 backup heater 1 power (kW)", 0, 20, 0.1, 0.1, False, False),
    (251, "P_IBH2 backup heater 2 power (kW)", 0, 20, 0.1, 0.1, False, False),
    (252, "P_TBH tank heater power (kW)", 0, 20, 0.1, 0.1, False, False),
    (255, "Floor drying: temperature rise days", 4, 15, 1, 1, False, False),
    (256, "Floor drying: drying days", 3, 7, 1, 1, False, False),
    (257, "Floor drying: temperature drop days", 4, 15, 1, 1, False, False),
    (258, "Floor drying: highest temperature (°C)", 30, 55, 1, 1, False, False),
    (259, "Floor pre-heating: run time (h)", 48, 96, 1, 1, False, False),
    (260, "Floor pre-heating: T1S (°C)", 25, 35, 1, 1, False, False),
    (261, "T1SetC1 cooling curve point 1 (°C)", 5, 25, 1, 1, False, False),
    (262, "T1SetC2 cooling curve point 2 (°C)", 5, 25, 1, 1, False, False),
    (263, "T4C1 cooling curve ambient 1 (°C)", -5, 46, 1, 1, True, False),
    (264, "T4C2 cooling curve ambient 2 (°C)", -5, 46, 1, 1, True, False),
    (265, "T1SetH1 heating curve point 1 (°C)", 25, 65, 1, 1, False, False),
    (266, "T1SetH2 heating curve point 2 (°C)", 25, 65, 1, 1, False, False),
    (267, "T4H1 heating curve ambient 1 (°C)", -25, 30, 1, 1, True, False),
    (268, "T4H2 heating curve ambient 2 (°C)", -25, 30, 1, 1, True, False),
    (271, "t_DELAY_PUMP built-in pump delay (min)", 2, 20, 0.5, 0.5, False, False),
    (275, "Gas price", 0, 5, 0.01, 0.01, False, True),
    (276, "Electricity price (per kWh)", 0, 5, 0.01, 0.01, False, True),
    (279, "Valve anti-lock run time (s)", 0, 120, 1, 1, False, True),
    (280, "Zone 2 T1SetC1 cooling curve point 1 (°C)", 5, 25, 1, 1, True, True),
    (281, "Zone 2 T1SetC2 cooling curve point 2 (°C)", 5, 25, 1, 1, True, True),
    (282, "Zone 2 T4C1 cooling curve ambient 1 (°C)", -5, 46, 1, 1, True, True),
    (283, "Zone 2 T4C2 cooling curve ambient 2 (°C)", -5, 46, 1, 1, True, True),
    (284, "Zone 2 T1SetH1 heating curve point 1 (°C)", 25, 80, 1, 1, True, True),
    (285, "Zone 2 T1SetH2 heating curve point 2 (°C)", 25, 80, 1, 1, True, True),
    (286, "Zone 2 T4H1 heating curve ambient 1 (°C)", -25, 35, 1, 1, True, True),
    (287, "Zone 2 T4H2 heating curve ambient 2 (°C)", -25, 35, 1, 1, True, True),
    (288, "Ta room sensor adjustment (°C)", -5, 5, 1, 1, True, True),
]

# Numbers packed two per register (one byte each).
# (addr, byte("low"/"high"), name, min, max, step, scale, r290_only)
PACKED_NUMBERS = [
    (2, "low",  "Water setpoint T1S zone 1 (°C)", 5, 65, 1, 1, False),
    (2, "high", "Water setpoint T1S zone 2 (°C)", 5, 65, 1, 1, False),
    (6, "low",  "Weather curve zone 1 (1-8, 9=custom)", 1, 9, 1, 1, False),
    (6, "high", "Weather curve zone 2 (1-8, 9=custom)", 1, 9, 1, 1, False),
    (270, "low",  "t_T4_FRESH_H heating T4 refresh time (h)", 0.5, 6, 0.5, 0.5, False),
    (270, "high", "t_T4_FRESH_C cooling T4 refresh time (h)", 0.5, 6, 0.5, 0.5, False),
    (273, "high", "DELTATSOL solar temperature difference (°C)", 5, 20, 1, 1, True),
    (277, "high", "SETHEATER max temperature (°C)", 0, 80, 1, 1, True),
    (277, "low",  "SETHEATER min temperature (°C)", 0, 80, 1, 1, True),
    (278, "high", "SIGHEATER max voltage (V)", 0, 10, 1, 1, True),
    (278, "low",  "SIGHEATER min voltage (V)", 0, 10, 1, 1, True),
]

# Room setpoint Ts is stored as Ts*2 in register 3.
TS_NUMBER = (3, "Room setpoint Ts (°C)", 17, 30, 0.5, 0.5)

# Bit switches: (addr, bit, name, r290_only)
BIT_SWITCHES = [
    (0, 0, "Room temperature control (Ts)", False),
    (0, 1, "Zone 1 water temperature control", False),
    (0, 2, "DHW on", False),
    (0, 3, "Zone 2 water temperature control", False),
    (5, 4, "Disinfect", False),
    (5, 6, "Silent mode", False),
    (5, 8, "Holiday home", False),
    (5, 10, "ECO mode", False),
    (5, 11, "DHW pump recirculation", False),
    (5, 12, "Weather compensation zone 1", False),
    (5, 13, "Weather compensation zone 2", False),
    (210, 0, "DHW priority (heating/cooling first when off)", False),
    (210, 1, "Dual room thermostat", False),
    (210, 2, "Room thermostat mode", False),
    (210, 3, "Room thermostat installed", False),
    (210, 4, "Room temperature sensor Ta installed", False),
    (210, 5, "PUMP_I silent mode", False),
    (210, 7, "Heating mode enabled", False),
    (210, 9, "Cooling mode enabled", False),
    (210, 10, "DHW pump pipe disinfect", False),
    (210, 12, "DHW pump installed", False),
    (210, 13, "Disinfection enabled", False),
    (210, 15, "DHW mode enabled", False),
    (211, 0, "IBH/AHS location (IBH LOCATE)", False),
    (211, 1, "Buffer tank sensor Tbt1 enabled", False),
    (211, 2, "Ta sensor position", False),
    (211, 3, "Double zone", False),
    (211, 4, "Heating T1S high/low temperature setting", False),
    (211, 5, "Cooling T1S high/low temperature setting", False),
    (211, 6, "T1B / Tw2 zone 2 sensor enabled", False),
    (211, 7, "Smart grid", False),
    (211, 8, "M1M2 port definition (ON/OFF input)", False),
    (211, 9, "Solar kit enabled", False),
    (211, 10, "Solar input port", False),
    (211, 11, "Piping length selection", False),
    (211, 12, "Buffer tank sensor Tbt2 enabled", False),
    (211, 13, "Temperature collection kit (RT/Ta_PCB)", False),
    (211, 14, "M1M2 used for AHS control", False),
    (274, 0, "EnSwitchPDC", True),
]

# Read-only bits: (addr, bit, name, device_class, r290_only)
BIT_SENSORS = [
    (5, 5, "Holiday away", None, False),
    (128, 1, "Defrosting", "cold", False),
    (128, 2, "Anti-freeze active", "cold", False),
    (128, 3, "Oil return", None, False),
    (128, 4, "Remote on/off input", None, False),
    (128, 5, "Outdoor unit test mode", None, False),
    (128, 6, "Heating requested by room thermostat", "heat", False),
    (128, 7, "Cooling requested by room thermostat", None, False),
    (128, 8, "Solar signal input", None, False),
    (128, 9, "Tank anti-freeze active", "cold", False),
    (128, 10, "Smart grid signal", None, False),
    (128, 11, "EVU signal", None, False),
    (129, 0, "Backup heater IBH1 running", "heat", False),
    (129, 1, "Backup heater IBH2 running", "heat", False),
    (129, 2, "Tank heater TBH running", "heat", False),
    (129, 3, "Internal pump PUMP_I running", "running", False),
    (129, 4, "Valve SV1", None, False),
    (129, 5, "Valve SV2", None, False),
    (129, 6, "External pump PUMP_O running", "running", False),
    (129, 7, "DHW return pump PUMP_D running", "running", False),
    (129, 8, "Mixing pump PUMP_C running", "running", False),
    (129, 9, "Valve SV3", None, False),
    (129, 10, "HEAT4 output", "heat", False),
    (129, 11, "Solar pump PUMP_S running", "running", False),
    (129, 12, "Alarm output", "problem", False),
    (129, 13, "Run output", "running", False),
    (129, 14, "Additional heat source AHS running", "heat", False),
    (129, 15, "Defrost output", "cold", False),
    (210, 6, "T1S heating high/low temperature supported", None, False),
    (210, 8, "T1S cooling high/low temperature supported", None, False),
    (210, 14, "Tank heater TBH supported", None, False),
    (198, 15, "TBH enabled", None, True),
    (198, 14, "AHS enabled", None, True),
    (198, 12, "T1B enabled", None, True),
    (198, 11, "AHS mode", None, True),
    (198, 10, "IBH enabled", None, True),
    (198, 9, "T1 enabled", None, True),
    (198, 8, "Energy metering enabled", None, True),
    (198, 5, "DHW operation", "running", True),
    (198, 4, "Heating operation", "running", True),
    (198, 3, "Cooling operation", "running", True),
]
BIT_SENSORS += [(142, i, f"Cascade slave unit {i} online", "connectivity", False) for i in range(1, 16)]

# Forced-output switches writing 1 = on, 2 = off.
FORCED_SWITCHES = [
    (7, "Force DHW heating"),
    (8, "Force tank heater TBH"),
    (9, "Force backup heater IBH1"),
]

# Selects on whole registers: (addr, name, {label: value}, r290_only)
SELECTS = [
    (1, "Operating mode", {"Auto": 1, "Cool": 2, "Heat": 3}, False),
    (269, "Power input limitation", {"None": 0, **{str(i): i for i in range(1, 9)}}, False),
]
# Selects on a nibble/byte of a register: (addr, shift, width_bits, name, {label: value}, r290_only)
EMISSION = {"Fan coil unit": 0, "Radiator": 1, "Underfloor heating": 2}
PACKED_SELECTS = [
    (272, 0, 4, "Zone 1 heating emitter type", EMISSION, False),
    (272, 4, 4, "Zone 2 heating emitter type", EMISSION, False),
    (272, 8, 4, "Zone 1 cooling emitter type", EMISSION, False),
    (272, 12, 4, "Zone 2 cooling emitter type", EMISSION, False),
    (5, 7, 1, "Silent mode level", {"Level 1": 0, "Level 2": 1}, False),
    (273, 0, 8, "Solar function", {"No function": 0, "Solar + heat pump": 1, "Only solar": 2}, True),
]

OP_MODE_101 = {0: "Off", 2: "Cooling", 3: "Heating", 5: "DHW"}
OP_MODE_199 = {0: "Off", 2: "Cooling", 3: "Heating", 5: "DHW"}
SUB_MODEL_190 = {0: "R32-P", 1: "Aqua", 2: "C-R32-P", 3: "R290-A", 4: "R290-N", 5: "C-R290-A",
                 6: "C-R290-N", 7: "R32-A", 8: "C-R32-A", 9: "R290-M", 10: "R32-H"}

FAULT_CODES = {
    0: ("OK", "No fault"),
    1: ("E0", "Water flow fault (E8 displayed 3 times)"),
    2: ("E1", "Phase loss / L-N reversed (three phase units)"),
    3: ("E2", "Communication fault controller - hydraulic module"),
    4: ("E3", "Final outlet water temperature sensor T1 fault"),
    5: ("E4", "Water tank temperature sensor T5 fault"),
    6: ("E5", "Condenser outlet refrigerant temperature sensor T3 fault"),
    7: ("E6", "Ambient temperature sensor T4 fault"),
    8: ("E7", "Buffer tank upper temperature sensor Tbt1 fault"),
    9: ("E8", "Water flow failure"),
    10: ("E9", "Suction temperature sensor Th fault"),
    11: ("EA", "Discharge temperature sensor Tp fault"),
    12: ("Eb", "Solar temperature sensor Tsolar fault"),
    13: ("Ec", "Buffer tank lower temperature sensor Tbt2 fault"),
    14: ("Ed", "Inlet water temperature sensor Tw_in fault"),
    15: ("EE", "Hydraulic module EEPROM failure"),
    20: ("P0", "Low pressure switch protection"),
    21: ("P1", "High pressure switch protection"),
    23: ("P3", "Compressor overcurrent protection"),
    24: ("P4", "High discharge temperature protection"),
    25: ("P5", "|Tw_out - Tw_in| too big protection"),
    26: ("P6", "Inverter module protection"),
    31: ("Pb", "Anti-freeze mode"),
    33: ("Pd", "High condenser refrigerant outlet temperature protection"),
    38: ("PP", "Tw_out - Tw_in unusual protection"),
    39: ("H0", "Communication fault main board PCB B - hydraulic module"),
    40: ("H1", "Communication fault inverter module PCB A - main board PCB B"),
    41: ("H2", "Refrigerant liquid temperature sensor T2 fault"),
    42: ("H3", "Refrigerant gas temperature sensor T2B fault"),
    43: ("H4", "Three times P6 (L0/L1) protection"),
    44: ("H5", "Room temperature sensor Ta fault"),
    45: ("H6", "DC fan motor fault"),
    46: ("H7", "Voltage protection"),
    47: ("H8", "Pressure sensor fault"),
    48: ("H9", "Zone 2 outlet water temperature sensor Tw2 fault"),
    49: ("HA", "Outlet water temperature sensor Tw_out fault"),
    50: ("Hb", "3 times PP protection and Tw_out < 7 °C"),
    52: ("Hd", "Communication fault between parallel hydraulic modules"),
    53: ("HE", "Communication error main board - thermostat transfer board"),
    54: ("HF", "Inverter module board EEPROM fault"),
    55: ("HH", "H6 displayed 10 times in 2 hours"),
    57: ("HP", "Low pressure protection (Pe < 0.6) 3 times in 1 hour"),
    65: ("C7", "Inverter module temperature too high protection"),
    112: ("bH", "PED PCB fault"),
    116: ("F1", "Low DC bus voltage protection"),
    134: ("-", "Module protection"),
    135: ("-", "DC bus low voltage protection"),
    136: ("-", "DC bus high voltage protection"),
    138: ("-", "MCE fault"),
    139: ("-", "Zero speed protection"),
    141: ("-", "Phase sequence fault"),
    142: ("-", "Speed difference > 15 Hz between front and back clock"),
    143: ("-", "Speed difference > 15 Hz between real and set speed"),
}


# ---------------------------------------------------------------------------
# Emitters
# ---------------------------------------------------------------------------


def write_actions(addr: int, value_template: str, refresh: int | None = None) -> list[dict]:
    actions = [{
        "service": "modbus.write_register",
        "data": {"hub": HUB, "slave": SLAVE, "address": addr, "value": value_template},
    }]
    if refresh is not None:
        actions.append({"service": "homeassistant.update_entity",
                        "target": {"entity_id": raw_entity(refresh)}})
    return actions


def guard(addr: int) -> dict:
    """Only write when the raw register value is known (never clobber bits with 0)."""
    return {"condition": "template", "value_template": f"{{{{ is_number(states('{raw_entity(addr)}')) }}}}"}


def raw_int(addr: int) -> str:
    return f"(states('{raw_entity(addr)}') | int(0))"


def modbus_sensor(addr: int, name: str, data_type: str, scan: int, **extra) -> dict:
    d = {
        "name": name,
        "unique_id": slug(name),
        "slave": SLAVE,
        "address": addr,
        "input_type": "holding",
        "data_type": data_type,
        "scan_interval": scan,
    }
    d.update({k: v for k, v in extra.items() if v is not None})
    return d


def build(r290: bool) -> dict:
    sensors = []
    for addr, name, dtype, unit, dc, sc, scale, prec, scan, only290 in VALUE_SENSORS:
        if only290 and not r290:
            continue
        sensors.append(modbus_sensor(
            addr, nice(name), dtype, scan,
            unit_of_measurement=unit, device_class=dc, state_class=sc,
            scale=scale if scale != 1 else None, precision=prec if prec else None,
        ))
    raw_defined: set[int] = set()
    for addr, dtype, scan, only290 in RAW_REGISTERS:
        if only290 and not r290:
            continue
        sensors.append(modbus_sensor(addr, raw_name(addr), dtype, scan))
        raw_defined.add(addr)
    # Every writable whole-register number needs a raw sensor too (signed
    # ones are read as int16 so negative thresholds display correctly).
    for addr, _name, _mn, _mx, _step, _scale, signed, only290 in NUMBERS:
        if (only290 and not r290) or addr in raw_defined:
            continue
        sensors.append(modbus_sensor(addr, raw_name(addr), "int16" if signed else "uint16",
                                     SCAN_RAW if addr < 100 else SCAN_CONFIG))
        raw_defined.add(addr)

    t_sensors, t_binary, t_numbers, t_selects = [], [], [], []
    l_switches: dict[str, dict] = {}

    # --- template sensors: decoded status --------------------------------
    def map_sensor(addr, name, mapping):
        items = ", ".join(f"{k}: '{v}'" for k, v in mapping.items())
        state = (f"{{% set v = {raw_int(addr)} %}}{{% set m = {{{items}}} %}}"
                 f"{{{{ m[v] if v in m else 'Unknown ' ~ v }}}}")
        t_sensors.append({"name": nice(name), "unique_id": slug(nice(name)), "state": state,
                          "availability": f"{{{{ is_number(states('{raw_entity(addr)}')) }}}}"})

    map_sensor(101, "Operating mode (actual)", OP_MODE_101)
    codes = ", ".join(f"{k}: '{v[0]}'" for k, v in FAULT_CODES.items())
    descs = ", ".join(f"{k}: '{v[1]}'" for k, v in FAULT_CODES.items())
    for addr, label in ((124, "Current fault"), (125, "Fault history 1"), (126, "Fault history 2"), (127, "Fault history 3")):
        t_sensors.append({
            "name": nice(f"{label} code"), "unique_id": slug(nice(f"{label} code")),
            "availability": f"{{{{ is_number(states('{raw_entity(addr)}')) }}}}",
            "state": f"{{% set v = {raw_int(addr)} %}}{{% set m = {{{codes}}} %}}{{{{ m[v] if v in m else v }}}}",
        })
        t_sensors.append({
            "name": nice(f"{label} description"), "unique_id": slug(nice(f"{label} description")),
            "availability": f"{{{{ is_number(states('{raw_entity(addr)}')) }}}}",
            "state": f"{{% set v = {raw_int(addr)} %}}{{% set m = {{{descs}}} %}}{{{{ m[v] if v in m else 'Unknown code ' ~ v }}}}",
        })
    # packed limits 201..204 (low byte zone 1, high byte zone 2)
    for addr, label in ((201, "T1S cooling upper limit"), (202, "T1S cooling lower limit"),
                        (203, "T1S heating upper limit"), (204, "T1S heating lower limit")):
        for zone, expr in (("zone 1", f"{raw_int(addr)} % 256"), ("zone 2", f"{raw_int(addr)} // 256")):
            n = nice(f"{label} {zone}")
            t_sensors.append({"name": n, "unique_id": slug(n), "unit_of_measurement": "°C",
                              "device_class": "temperature",
                              "availability": f"{{{{ is_number(states('{raw_entity(addr)}')) }}}}",
                              "state": f"{{{{ {expr} }}}}"})
    if r290:
        map_sensor(199, "Operation mode", OP_MODE_199)
        map_sensor(190, "Hydraulic module sub-model", SUB_MODEL_190)
        map_sensor(187, "Machine type", {6: "A-R290"})
    n = nice("Water ΔT (Tw_out - Tw_in)")
    t_sensors.append({
        "name": n, "unique_id": slug(n), "unit_of_measurement": "°C", "state_class": "measurement",
        "availability": f"{{{{ is_number(states('sensor.{slug(nice('Water outlet temperature Tw_out'))}')) and is_number(states('sensor.{slug(nice('Water inlet temperature Tw_in'))}')) }}}}",
        "state": f"{{{{ (states('sensor.{slug(nice('Water outlet temperature Tw_out'))}') | float) - (states('sensor.{slug(nice('Water inlet temperature Tw_in'))}') | float) }}}}",
    })

    # --- binary sensors from bits ----------------------------------------
    for addr, bit, name, dc, only290 in BIT_SENSORS:
        if only290 and not r290:
            continue
        n = nice(name)
        d = {"name": n, "unique_id": slug(n),
             "availability": f"{{{{ is_number(states('{raw_entity(addr)}')) }}}}",
             "state": f"{{{{ {raw_int(addr)} | bitwise_and({1 << bit}) > 0 }}}}"}
        if dc:
            d["device_class"] = dc
        t_binary.append(d)

    # --- bit switches (read-modify-write) --------------------------------
    for addr, bit, name, only290 in BIT_SWITCHES:
        if only290 and not r290:
            continue
        mask = 1 << bit
        key = slug(nice(name))
        l_switches[key] = {
            "unique_id": key,
            "friendly_name": nice(name),
            "value_template": f"{{{{ {raw_int(addr)} | bitwise_and({mask}) > 0 }}}}",
            "turn_on": [guard(addr)] + write_actions(addr, f"{{{{ {raw_int(addr)} | bitwise_or({mask}) }}}}", addr),
            "turn_off": [guard(addr)] + write_actions(addr, f"{{{{ {raw_int(addr)} | bitwise_and({65535 - mask}) }}}}", addr),
        }
    for addr, name in FORCED_SWITCHES:
        key = slug(nice(name))
        l_switches[key] = {
            "unique_id": key,
            "friendly_name": nice(name),
            "value_template": f"{{{{ {raw_int(addr)} == 1 }}}}",
            "turn_on": write_actions(addr, "1", addr),
            "turn_off": write_actions(addr, "2", addr),
        }

    # --- numbers ---------------------------------------------------------
    def number(addr, name, mn, mx, step, state_tpl, value_tpl, guarded=True):
        n = nice(name)
        actions = ([guard(addr)] if guarded else []) + write_actions(addr, value_tpl, addr)
        t_numbers.append({"name": n, "unique_id": slug(n), "min": mn, "max": mx, "step": step,
                          "availability": f"{{{{ is_number(states('{raw_entity(addr)}')) }}}}",
                          "state": state_tpl, "set_value": actions})

    for addr, name, mn, mx, step, scale, signed, only290 in NUMBERS:
        if only290 and not r290:
            continue
        # Signed registers are read as int16 by the raw sensor for these addresses.
        raw = raw_int(addr)
        state = f"{{{{ {raw} * {scale} }}}}" if scale != 1 else f"{{{{ {raw} }}}}"
        value = (f"{{{{ ((value | float) / {scale}) | round | int % 65536 }}}}" if scale != 1
                 else "{{ (value | int) % 65536 }}")
        number(addr, name, mn, mx, step, state, value, guarded=False)
    for addr, byte, name, mn, mx, step, scale, only290 in PACKED_NUMBERS:
        if only290 and not r290:
            continue
        raw = raw_int(addr)
        if byte == "low":
            state = f"{{{{ ({raw} % 256) * {scale} }}}}"
            value = f"{{{{ ({raw} // 256) * 256 + (((value | float) / {scale}) | round | int) }}}}"
        else:
            state = f"{{{{ ({raw} // 256) * {scale} }}}}"
            value = f"{{{{ ({raw} % 256) + (((value | float) / {scale}) | round | int) * 256 }}}}"
        number(addr, name, mn, mx, step, state, value)
    addr, name, mn, mx, step, scale = TS_NUMBER
    number(addr, name, mn, mx, step, f"{{{{ {raw_int(addr)} * {scale} }}}}",
           f"{{{{ ((value | float) / {scale}) | round | int }}}}", guarded=False)

    # --- selects ---------------------------------------------------------
    def select(addr, name, mapping, state_expr, value_expr_fn, guarded):
        n = nice(name)
        inv = ", ".join(f"{v}: '{k}'" for k, v in mapping.items())
        fwd = ", ".join(f"'{k}': {v}" for k, v in mapping.items())
        state = f"{{% set v = {state_expr} %}}{{% set m = {{{inv}}} %}}{{{{ m[v] if v in m else 'Unknown' }}}}"
        value = value_expr_fn(f"({{{{ {{{fwd}}}[option] }}}})")
        actions = ([guard(addr)] if guarded else []) + write_actions(addr, value, addr)
        options = "{{ [" + ", ".join(f"'{k}'" for k in mapping) + "] }}"
        t_selects.append({"name": n, "unique_id": slug(n), "options": options,
                          "availability": f"{{{{ is_number(states('{raw_entity(addr)}')) }}}}",
                          "state": state, "select_option": actions})

    for addr, name, mapping, only290 in SELECTS:
        if only290 and not r290:
            continue
        fwd = ", ".join(f"'{k}': {v}" for k, v in mapping.items())
        select(addr, name, mapping, raw_int(addr), lambda _: f"{{{{ {{{fwd}}}[option] }}}}", False)
    for addr, shift, width, name, mapping, only290 in PACKED_SELECTS:
        if only290 and not r290:
            continue
        mask = ((1 << width) - 1) << shift
        fwd = ", ".join(f"'{k}': {v}" for k, v in mapping.items())
        state_expr = f"({raw_int(addr)} // {1 << shift}) % {1 << width}"
        value = (f"{{{{ ({raw_int(addr)} | bitwise_and({65535 - mask})) "
                 f"| bitwise_or({{{fwd}}}[option] * {1 << shift}) }}}}")
        select(addr, name, mapping, state_expr, lambda _v, value=value: value, True)

    package = {
        "modbus": [{
            "name": HUB,
            "type": "serial",
            "port": "/dev/ttyUSB0",
            "baudrate": 9600,
            "bytesize": 8,
            "parity": "N",
            "stopbits": 1,
            "method": "rtu",
            "sensors": sensors,
        }],
        "template": [
            {"sensor": t_sensors},
            {"binary_sensor": t_binary},
            {"number": t_numbers},
            {"select": t_selects},
        ],
        "switch": [{"platform": "template", "switches": l_switches}],
    }
    return package


HEADER = """# ---------------------------------------------------------------------------
# Midea M-Thermal (Rotenso Windmi / Kaisai / Fisher / Airwell / Ferroli ...)
# Modbus RTU package for Home Assistant -- GENERATED, do not edit by hand.
#   generator : tools/gen_modbus_package.py {flag}
#   registers : community map from Mosibi/Midea-heat-pump-ESPHome (Apache-2.0)
#   wiring    : RS485 A+ -> H2, B- -> H1 on the wired controller PCB,
#               9600 baud 8N1, slave address 1 (see docs/modbus/README.md)
#
# Change the `modbus:` hub below to match your adapter:
#   USB RS485 dongle : type: serial, port: /dev/ttyUSB0 (as generated)
#   TCP gateway      : type: rtuovertcp, host: 192.168.x.y, port: 502
#                      (remove baudrate/bytesize/parity/stopbits/method)
# Installer parameters change how the heat pump protects itself. Write them
# only if you know what they do (FOR SERVICEMAN section of the manual).
# ---------------------------------------------------------------------------
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--r290", action="store_true", help="include R290-generation registers")
    args = ap.parse_args()
    package = build(args.r290)
    sys.stdout.write(HEADER.format(flag="--r290" if args.r290 else ""))
    yaml.safe_dump(package, sys.stdout, sort_keys=False, allow_unicode=True, width=200)


if __name__ == "__main__":
    main()
