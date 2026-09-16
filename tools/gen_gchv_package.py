#!/usr/bin/env python3
"""Generate a Home Assistant Modbus package for GCHV-built heat pumps
(Rotenso Windmi monoblock and other Giwee/GCHV OEM units).

Background
----------
The Rotenso Windmi (WIM40X1 .. WIM160X3) is manufactured by GCHV
(Guangdong Carrier Heating, Ventilation & Air Conditioning, formerly
Chigo HVAC; brand "Giwee"). Its wired controller speaks Modbus RTU on the
A/B/E terminals ("ABE" port) and the installation manual (pages 122-123,
"Modbus Table") lists the registers with GCHV-style hexadecimal addresses
(e.g. 0174H). Decimal address = hex without the trailing H, e.g.
0174H = 372.

The register list below is what a Windmi owner has verified in Home
Assistant (https://gist.github.com/hvdb/a6a6fdc889573084ac2bdd53e71303c7):
default slave address 11, read-only so far. The manual's table also
contains writable parameters (function codes 0x06 / 0x10: setting mode,
occupied heating air setpoint, warm-up time, booster settings, ...);
they are added to WRITABLE below as they are confirmed from the manual.

Usage
-----
    python tools/gen_gchv_package.py > docs/modbus/rotenso_windmi_gchv.yaml
"""
from __future__ import annotations

import re
import sys

import yaml

HUB = "heatpump"
SLAVE = 11
PREFIX = "HP"
SCAN_STATUS = 30
SCAN_CONFIG = 120


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# (addr, name, input_type, data_type, scale, precision, unit, device_class, state_class, scan)
# input_type follows the owner's working config: "input" = function 0x04,
# "holding" = function 0x03. The manual allows both for most registers.
REGISTERS = [
    # ---- temperatures (0x03, 0.1 °C) ----
    (1,    "Outdoor temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (2,    "Indoor temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (3,    "Inlet water temperature (ETW)", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (4,    "Outlet water temperature (LWT)", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (5,    "Refrigerant temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (10,   "Discharge temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (11,   "Air exchanger temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (51,   "Water control point", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (4104, "LWT after BPHE", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (4115, "IPM refrigerant cooling pipe temperature (TL)", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (4131, "IPM module temperature (T9)", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (4132, "T30 defrost calculation temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (4134, "Target discharge temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    # ---- status / modes (0x04) ----
    (41,   "Occupancy mode (raw)", "input", "uint16", 1, 0, None, None, None, SCAN_STATUS),
    (44,   "Setting mode (raw)", "input", "uint16", 1, 0, None, None, None, SCAN_STATUS),
    (45,   "Running mode (raw)", "input", "uint16", 1, 0, None, None, None, SCAN_STATUS),
    (68,   "Frequency reduction / night mode (raw)", "input", "uint16", 1, 0, None, None, None, SCAN_STATUS),
    (521,  "User interface type (raw)", "input", "uint16", 1, 0, None, None, None, SCAN_CONFIG),
    (569,  "Water delta T setpoint", "input", "uint16", 1, 0, "°C", None, None, SCAN_CONFIG),
    (601,  "Backup heater type (raw)", "input", "uint16", 1, 0, None, None, None, SCAN_CONFIG),
    (602,  "Warm-up time", "input", "uint16", 1, 0, "min", None, None, SCAN_CONFIG),
    # ---- compressor / fans / pump ----
    (23,   "Compressor frequency", "input", "uint16", 1, 0, "Hz", "frequency", "measurement", SCAN_STATUS),
    (85,   "Pump speed", "input", "uint16", 1, 0, None, None, "measurement", SCAN_STATUS),
    (372,  "Compressor runtime", "input", "uint16", 1, 0, "h", "duration", "total_increasing", SCAN_CONFIG),
    (374,  "Pump runtime", "input", "uint16", 1, 0, "h", "duration", "total_increasing", SCAN_CONFIG),
    (4097, "IDU side capacity demand", "input", "uint16", 1, 0, None, None, "measurement", SCAN_STATUS),
    (4098, "Capacity demand after ODU rectify", "input", "uint16", 1, 0, None, None, "measurement", SCAN_STATUS),
    (4100, "Actual capacity output", "input", "uint16", 1, 0, None, None, "measurement", SCAN_STATUS),
    (4101, "Fan speed", "input", "uint16", 1, 0, None, None, "measurement", SCAN_STATUS),
    (4102, "Unit capacity", "input", "uint16", 1, 0, "kW", None, None, SCAN_CONFIG),
    (4111, "Required compressor frequency", "input", "uint16", 1, 0, "Hz", "frequency", "measurement", SCAN_STATUS),
    (4116, "AC current", "input", "uint16", 1, 0, "A", "current", "measurement", SCAN_STATUS),
    (4122, "Required fan speed upper motor", "input", "uint16", 1, 0, "rpm", None, "measurement", SCAN_STATUS),
    (4123, "Required fan speed lower motor", "input", "uint16", 1, 0, "rpm", None, "measurement", SCAN_STATUS),
    (4124, "Required EXV opening", "input", "uint16", 1, 0, "steps", None, "measurement", SCAN_STATUS),
    (4125, "Actual fan speed upper motor", "input", "uint16", 1, 0, "rpm", None, "measurement", SCAN_STATUS),
    (4126, "Actual fan speed lower motor", "input", "uint16", 1, 0, "rpm", None, "measurement", SCAN_STATUS),
    (4138, "Water flow feedback", "input", "uint16", 1, 0, "m³/h", None, "measurement", SCAN_STATUS),
]

# Writable parameters confirmed from the manual's Modbus table (function
# codes 0x06 / 0x10, value = temperature * 10). Only entries whose address,
# range and scaling were verified are listed; extend from pages 122-123.
# (addr, hex, name, min, max, step, scale, unit)
WRITABLE: list[tuple] = [
    (421, "01A5H", "Occupied heating air setpoint (°C)", 16, 32, 1, 0.1, "°C"),
    (603, "025BH", "Booster delta temperature (°C)", 1, 20, 1, 0.1, "°C"),
]


HEADER = """# ---------------------------------------------------------------------------
# Rotenso Windmi (GCHV / Giwee monoblock) Modbus RTU package for Home
# Assistant -- GENERATED by tools/gen_gchv_package.py, do not edit by hand.
#
#   wiring   : RS485 A/B/E terminals ("ABE" port) of the unit
#   settings : slave address 11 (default), set baud/parity to what the
#              wired controller reports (see manual, "Modbus Table")
#   source   : owner-verified register list (gist by hvdb) matching the
#              GCHV table in the Rotenso Windmi installation manual,
#              pages 122-123 (hex address without the trailing H = decimal)
#
# Change the `modbus:` hub to match your adapter (USB RS485 dongle or a
# TCP gateway such as Elfin-EW11 in Modbus RTU-over-TCP mode).
# ---------------------------------------------------------------------------
"""


def build() -> dict:
    sensors = []
    for addr, name, input_type, dtype, scale, prec, unit, dc, sc, scan in REGISTERS:
        d = {
            "name": f"{PREFIX} {name}",
            "unique_id": slug(f"{PREFIX} gchv r{addr}"),
            "slave": SLAVE,
            "address": addr,
            "input_type": input_type,
            "data_type": dtype,
            "scan_interval": scan,
        }
        if scale != 1:
            d["scale"] = scale
            d["precision"] = prec
        if unit:
            d["unit_of_measurement"] = unit
        if dc:
            d["device_class"] = dc
        if sc:
            d["state_class"] = sc
        sensors.append(d)

    numbers = []
    for addr, hexaddr, name, mn, mx, step, scale, unit in WRITABLE:
        # raw readback sensor for the same register (0x03)
        sensors.append({
            "name": f"{PREFIX} GCHV R{addr} ({hexaddr})",
            "unique_id": slug(f"{PREFIX} gchv r{addr}"),
            "slave": SLAVE, "address": addr, "input_type": "holding",
            "data_type": "int16", "scan_interval": SCAN_CONFIG,
        })
        raw_entity = "sensor." + slug(f"{PREFIX} gchv r{addr}")
        numbers.append({
            "name": f"{PREFIX} {name}",
            "unique_id": slug(f"{PREFIX} gchv w{addr}"),
            "min": mn, "max": mx, "step": step,
            "availability": f"{{{{ is_number(states('{raw_entity}')) }}}}",
            "state": f"{{{{ (states('{raw_entity}') | float(0)) * {scale} }}}}",
            "set_value": [
                {"service": "modbus.write_register",
                 "data": {"hub": HUB, "slave": SLAVE, "address": addr,
                          "value": f"{{{{ ((value | float) / {scale}) | round | int }}}}"}},
                {"service": "homeassistant.update_entity", "target": {"entity_id": raw_entity}},
            ],
        })

    package = {
        "modbus": [{
            "name": HUB,
            "type": "rtuovertcp",
            "host": "192.168.1.50",
            "port": 8899,
            "sensors": sensors,
        }],
    }
    if numbers:
        package["template"] = [{"number": numbers}]
    return package


def main() -> None:
    sys.stdout.write(HEADER)
    yaml.safe_dump(build(), sys.stdout, sort_keys=False, allow_unicode=True, width=200)


if __name__ == "__main__":
    main()
