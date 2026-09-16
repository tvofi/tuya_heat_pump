#!/usr/bin/env python3
"""Generate a Home Assistant Modbus package for GCHV-built heat pumps
(Rotenso Windmi monoblock WIM40X1..WIM160X3 and other Giwee/GCHV units).

Background
----------
The Rotenso Windmi is manufactured by GCHV (Guangdong Carrier Heating,
Ventilation & Air Conditioning, formerly Chigo HVAC; brand "Giwee"). The
unit speaks Modbus RTU on its A/B/E terminals, default 9600 8N1, slave
address 11. The installation manual's "Modbus table" lists registers with
hexadecimal GCHV addresses; the decimal Modbus address is the hex value
without the trailing H (0174H = 372).

Sources
-------
* Rotenso Windmi installation & user manual, Modbus table rows 20-159
  (transcribed from the owner's pages; rows 1-19 and 84-106 were not
  available and are covered by the owner-verified gist below where known).
* https://gist.github.com/hvdb/a6a6fdc889573084ac2bdd53e71303c7 (working
  Home Assistant configuration of a Windmi owner).

Conventions
-----------
* "Data=Temp*10" registers are read with scale 0.1 and written as
  round(value*10); negative ranges are read as int16 and written modulo
  65536 so -4 becomes 65532.
* hh:mm registers hold hour*256+minute: exposed as two numbers per
  register with read-modify-write.
* Day bitmaps (b7=Monday ... b1=Sunday) are exposed as one switch per
  day with read-modify-write.
* Writes use modbus.write_register (function 0x06); after every write the
  raw sensor is refreshed with homeassistant.update_entity.

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


def raw_id(addr: int) -> str:
    return slug(f"{PREFIX} gchv r{addr}")


def raw_entity(addr: int) -> str:
    return "sensor." + raw_id(addr)


def nice(name: str) -> str:
    return f"{PREFIX} {name}"


# ---------------------------------------------------------------------------
# Read-only values exposed directly as modbus sensors
# (addr, hex, name, input_type, data_type, scale, precision, unit, device_class, state_class, scan)
# ---------------------------------------------------------------------------
RO_VALUES = [
    # owner-verified temperatures (rows 1-19 of the manual, 0.1 °C)
    (1, "0001H", "Outdoor temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (2, "0002H", "Indoor temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (3, "0003H", "Inlet water temperature (EWT)", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (4, "0004H", "Outlet water temperature (LWT)", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (5, "0005H", "Refrigerant temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (10, "000AH", "Discharge temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (11, "000BH", "Air exchanger temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (23, "0017H", "Compressor frequency", "input", "uint16", 1, 0, "Hz", "frequency", "measurement", SCAN_STATUS),
    (85, "0055H", "Pump speed", "input", "uint16", 1, 0, "%", None, "measurement", SCAN_STATUS),
    (206, "00CEH", "DHW tank temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (372, "0174H", "Compressor runtime", "input", "uint16", 1, 0, "h", "duration", "total_increasing", SCAN_CONFIG),
    (374, "0176H", "Pump runtime", "input", "uint16", 1, 0, "h", "duration", "total_increasing", SCAN_CONFIG),
    (4097, "1001H", "IDU side capacity demand", "input", "uint16", 1, 0, None, None, "measurement", SCAN_STATUS),
    (4098, "1002H", "Capacity demand after ODU rectify", "input", "uint16", 1, 0, None, None, "measurement", SCAN_STATUS),
    (4100, "1004H", "Actual capacity output", "input", "uint16", 1, 0, None, None, "measurement", SCAN_STATUS),
    (4101, "1005H", "Fan speed level (0-8)", "input", "uint16", 1, 0, None, None, "measurement", SCAN_STATUS),
    (4102, "1006H", "Unit capacity", "input", "uint16", 1, 0, "kW", None, None, SCAN_CONFIG),
    (4104, "1008H", "LWT after BPHE inside unit (Tw-out)", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (4111, "100FH", "Required compressor frequency", "input", "uint16", 0.1, 1, "Hz", "frequency", "measurement", SCAN_STATUS),
    (4114, "1012H", "EXV opening degree", "input", "uint16", 4, 0, "steps", None, "measurement", SCAN_STATUS),
    (4115, "1013H", "IPM refrigerant cooling pipe temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (4116, "1014H", "AC current", "input", "uint16", 2, 0, "A", "current", "measurement", SCAN_STATUS),
    (4117, "1015H", "DC current", "input", "uint16", 4, 0, "A", "current", "measurement", SCAN_STATUS),
    (4118, "1016H", "AC voltage", "input", "uint16", 1, 0, "V", "voltage", "measurement", SCAN_STATUS),
    (4119, "1017H", "DC voltage", "input", "uint16", 0.5, 1, "V", "voltage", "measurement", SCAN_STATUS),
    (4122, "101AH", "Required fan speed upper motor", "input", "uint16", 10, 0, "rpm", None, "measurement", SCAN_STATUS),
    (4123, "101BH", "Required fan speed lower motor", "input", "uint16", 10, 0, "rpm", None, "measurement", SCAN_STATUS),
    (4124, "101CH", "Required EXV opening degree", "input", "uint16", 4, 0, "steps", None, "measurement", SCAN_STATUS),
    (4125, "101DH", "Actual fan speed upper motor", "input", "uint16", 10, 0, "rpm", None, "measurement", SCAN_STATUS),
    (4126, "101EH", "Actual fan speed lower motor", "input", "uint16", 10, 0, "rpm", None, "measurement", SCAN_STATUS),
    (4128, "1020H", "ODU program version", "input", "uint16", 1, 0, None, None, None, SCAN_CONFIG),
    (4129, "1021H", "ODU EEPROM version", "input", "uint16", 1, 0, None, None, None, SCAN_CONFIG),
    (4131, "1023H", "IPM module temperature (T9)", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (4132, "1024H", "T30 defrost calculation temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (4134, "1026H", "Target discharge temperature", "holding", "int16", 0.1, 1, "°C", "temperature", "measurement", SCAN_STATUS),
    (4138, "102AH", "Water flow feedback", "input", "uint16", 0.01, 2, "m³/h", None, "measurement", SCAN_STATUS),
    (4145, "1031H", "Modbus baud rate", "input", "uint16", 100, 0, "Bd", None, None, SCAN_CONFIG),
    (4147, "1033H", "Modbus ID", "input", "uint16", 1, 0, None, None, None, SCAN_CONFIG),
]

# Raw registers consumed by templates: (addr, hex, data_type, scan)
RAW = [
    (41, "0029H", "uint16", SCAN_STATUS),   # occupancy mode (owner gist)
    (44, "002CH", "uint16", SCAN_STATUS),   # setting mode (owner gist)
    (45, "002DH", "uint16", SCAN_STATUS),   # running mode (owner gist)
    (68, "0044H", "uint16", SCAN_STATUS),   # frequency reduction / night mode (owner gist)
    (105, "0069H", "uint16", SCAN_STATUS),  # flow switch
    (106, "006AH", "uint16", SCAN_STATUS),  # DI5..DI8 status
    (107, "006BH", "uint16", SCAN_STATUS),
    (108, "006CH", "uint16", SCAN_STATUS),
    (109, "006DH", "uint16", SCAN_STATUS),
    (201, "00C9H", "uint16", SCAN_STATUS),  # DHW mode
    (210, "00D2H", "uint16", SCAN_STATUS),  # DHW valve
    (521, "0209H", "uint16", SCAN_CONFIG),  # user interface type (owner gist)
    (4105, "1009H", "uint16", SCAN_STATUS), # alarm bitmap 1
    (4106, "100AH", "uint16", SCAN_STATUS), # alarm bitmap 2
    (4107, "100BH", "uint16", SCAN_STATUS), # alarm bitmap 3
    (4108, "100CH", "uint16", SCAN_STATUS), # alarm bitmap 4
    (4110, "100EH", "uint16", SCAN_STATUS), # ODU output status
    (4121, "1019H", "uint16", SCAN_STATUS), # frequency limitation reason 1
    (4127, "101FH", "uint16", SCAN_STATUS), # ODU input status
    (4130, "1022H", "uint16", SCAN_STATUS), # P6 reason
    (4133, "1025H", "uint16", SCAN_STATUS), # frequency limitation reason 2
    (4146, "1032H", "uint16", SCAN_CONFIG), # parity
]

# Writable numbers: (addr, hex, name, min, max, step, scale, signed, unit)
RW_NUMBERS = [
    (51,  "0033H", "Water control point (°C)", 5, 63, 0.5, 0.1, False, "°C"),
    (401, "0191H", "Occupied heating water setpoint (°C)", 25, 63, 0.5, 0.1, False, "°C"),
    (402, "0192H", "Unoccupied heating water setpoint offset (°C)", -20, 0, 0.5, 0.1, True, "°C"),
    (403, "0193H", "Economic heating water setpoint offset (°C)", -20, 0, 0.5, 0.1, True, "°C"),
    (404, "0194H", "DHW normal setpoint (°C)", 40, 63, 0.5, 0.1, False, "°C"),
    (405, "0195H", "DHW anti-legionella setpoint (°C)", 60, 70, 0.5, 0.1, False, "°C"),
    (406, "0196H", "DHW economic setpoint (°C)", 40, 63, 0.5, 0.1, False, "°C"),
    (407, "0197H", "Occupied cooling water setpoint (°C)", 5, 25, 0.5, 0.1, False, "°C"),
    (408, "0198H", "Unoccupied cooling water setpoint offset (°C)", 0, 10, 0.5, 0.1, False, "°C"),
    (409, "0199H", "Economic cooling water setpoint offset (°C)", 0, 10, 0.5, 0.1, False, "°C"),
    (412, "019CH", "Heating climatic curve max setpoint offset (°C)", -5, 5, 0.5, 0.1, True, "°C"),
    (413, "019DH", "Cooling climatic curve min setpoint offset (°C)", -5, 5, 0.5, 0.1, True, "°C"),
    (421, "01A5H", "Occupied heating air setpoint (°C)", 16, 32, 0.5, 0.1, False, "°C"),
    (422, "01A6H", "Unoccupied heating air setpoint offset (°C)", -20, 0, 0.5, 0.1, True, "°C"),
    (423, "01A7H", "Economic heating air setpoint offset (°C)", -20, 0, 0.5, 0.1, True, "°C"),
    (424, "01A8H", "Occupied cooling air setpoint (°C)", 16, 32, 0.5, 0.1, False, "°C"),
    (425, "01A9H", "Unoccupied cooling air setpoint offset (°C)", 0, 10, 0.5, 0.1, False, "°C"),
    (426, "01AAH", "Economic cooling air setpoint offset (°C)", 0, 10, 0.5, 0.1, False, "°C"),
    (514, "0202H", "Minimum OAT for heating with compressor (°C)", -26, 10, 0.5, 0.1, True, "°C"),
    (569, "0239H", "Water delta T setpoint (°C)", 3.5, 20, 0.5, 0.1, False, "°C"),
    (582, "0246H", "Custom heating curve min OAT (°C)", -30, 10, 0.5, 0.1, True, "°C"),
    (583, "0247H", "Custom heating curve max OAT (°C)", 10, 30, 0.5, 0.1, False, "°C"),
    (584, "0248H", "Custom heating curve min LWT (°C)", 25, 40, 0.5, 0.1, False, "°C"),
    (585, "0249H", "Custom heating curve max LWT (°C)", 30, 60, 0.5, 0.1, False, "°C"),
    (587, "024BH", "Custom cooling curve min OAT (°C)", 0, 30, 0.5, 0.1, False, "°C"),
    (588, "024CH", "Custom cooling curve max OAT (°C)", 24, 50, 0.5, 0.1, False, "°C"),
    (589, "024DH", "Custom cooling curve min LWT (°C)", 5, 20, 0.5, 0.1, False, "°C"),
    (590, "024EH", "Custom cooling curve max LWT (°C)", 5, 20, 0.5, 0.1, False, "°C"),
    (602, "025AH", "Warm-up time (min)", 0, 60, 1, 1, False, "min"),
    (603, "025BH", "Booster delta temperature (°C)", 1, 20, 0.5, 0.1, False, "°C"),
    (604, "025CH", "Booster OAT threshold (°C)", -20, 15, 0.5, 0.1, True, "°C"),
]

# Writable enumerations: (addr, hex, name, {label: value}, signed)
DI_TYPES = {"Disabled": 0, "Power limitation (night mode)": 1, "Load shed": 2,
            "Anti-legionella request": 3, "DHW request": 4, "DHW priority": 5}
DO_TYPES = {"Disabled": 0, "Unit in alarm": 1, "Unit in standby": 2, "Unit running": 3,
            "Unit in cool mode": 4, "Unit in heat mode": 5, "Unit in DHW": 6,
            "Unit in defrost": 7, "Unit controlled by Modbus": 8}
RW_SELECTS = [
    (581, "0245H", "Heating climatic curve", {"No curve (fixed setpoint)": -1, "Custom curve": 0,
                                               **{f"Curve {i}": i for i in range(1, 13)}}, True),
    (586, "024AH", "Cooling climatic curve", {"No curve (fixed setpoint)": -1, "Custom curve": 0,
                                               "Curve 1": 1, "Curve 2": 2}, True),
    (601, "0259H", "Backup heater type", {
        "Inner EH + DHW EH + gas boiler": 0, "Inner EH + DHW EH": 1, "DHW EH + gas boiler": 2,
        "Inner EH + gas boiler": 3, "DHW EH": 4, "Gas boiler": 5, "Inner EH": 6,
        "No auxiliary heater": 7}, False),
    (4109, "100DH", "Control mode", {"Water temperature control": 0, "Ambient temperature control": 1}, False),
    (502, "01F6H", "Discrete input 5 function", DI_TYPES, False),
    (503, "01F7H", "Discrete input 6 function", DI_TYPES, False),
    (504, "01F8H", "Discrete input 7 function", DI_TYPES, False),
    (505, "01F9H", "Discrete input 8 function", DI_TYPES, False),
    (500, "01F4H", "Discrete output 5 function", DO_TYPES, False),
    (506, "01FAH", "Discrete output 8 function", DO_TYPES, False),
    (507, "01FBH", "Discrete output 9 function", DO_TYPES, False),
]

# Writable 0/1 registers: (addr, hex, name)
RW_SWITCHES = [
    (703, "02BFH", "DHW priority"),
    (320, "0140H", "Force discrete output 5"),
    (337, "0151H", "Force discrete output 8"),
    (338, "0152H", "Force discrete output 9"),
]

# hh:mm registers (hour*256+minute): (addr, hex, name)
TIME_REGS = [
    (518, "0206H", "Night mode start"),
    (519, "0207H", "Night mode end"),
    (712, "02C8H", "DHW schedule start"),
    (713, "02C9H", "DHW schedule stop"),
    (715, "02CBH", "Anti-legionella schedule start"),
]

# Day bitmaps b7=Monday ... b1=Sunday: (addr, hex, name)
DAY_BITMAPS = [
    (711, "02C7H", "DHW schedule"),
    (714, "02CAH", "Anti-legionella schedule"),
]
DAYS = [("Monday", 7), ("Tuesday", 6), ("Wednesday", 5), ("Thursday", 4),
        ("Friday", 3), ("Saturday", 2), ("Sunday", 1)]

# Read-only enumerations shown as text: (addr, name, {value: label})
RO_MAPS = [
    (201, "DHW mode", {0: "Eco", 1: "Anti-legionella", 2: "Regular"}),
    (4130, "P6 (IPM protection) reason", {
        0: "None", 0x0A: "IPM error", 0x01: "DC voltage too low", 0x02: "DC voltage too high",
        0x04: "MCE error / synchronisation / closed loop", 0x05: "Compressor speed fault",
        0x07: "Phase error", 0x08: "Compressor speed changing fault", 0x09: "Compressor speed incorrect"}),
    (4146, "Modbus parity", {0: "None", 1: "Odd", 2: "Even"}),
]

# Read-only bit flags: (addr, bit, name, device_class)
RO_BITS = [
    (105, 0, "Flow switch closed", "opening"),
    (106, 0, "Discrete input 5 closed", None),
    (107, 0, "Discrete input 6 closed", None),
    (108, 0, "Discrete input 7 closed", None),
    (109, 0, "Discrete input 8 closed", None),
    (210, 0, "DHW valve on", "opening"),
    (4110, 0, "ODU output: AC fan motor high", "running"),
    (4110, 1, "ODU output: AC fan motor low", "running"),
    (4110, 2, "ODU output: compressor heater", "heat"),
    (4110, 3, "ODU output: chassis heater", "heat"),
    (4110, 4, "ODU output: power PTC", "power"),
    (4110, 5, "ODU output: SV1", None),
    (4110, 6, "ODU output: 4-way valve", None),
    (4110, 7, "ODU output: SV2", None),
    (4127, 0, "Low pressure switch", "problem"),
    (4127, 1, "High pressure switch", "problem"),
]

# Bitmask -> text (sum of reasons): (addr, name, {bitvalue: label})
MASK_TEXT = [
    (4121, "Compressor frequency limitation reason 1", {
        1: "T3B ODU coil", 2: "T4", 4: "T5", 8: "Voltage", 16: "Current", 32: "T9",
        64: "Night mode", 128: "LWT"}),
    (4133, "Compressor frequency limitation reason 2", {
        1: "LWT/EWT tolerance", 2: "Heating SH3", 4: "T4 lowest frequency", 8: "Cooling T2B"}),
]

# Alarm bitmaps: (addr, name, {bit: label})
ALARMS = [
    (4105, "Alarm bitmap 1", {
        0: "Water flow switch fail", 1: "Comm fail ODU - hydraulic PCB", 2: "LWT sensor after EH fail",
        3: "BPHE outlet refrigerant sensor fail", 4: "BPHE inlet refrigerant sensor fail", 5: "ODU fail",
        6: "DHW tank sensor fail", 7: "EWT of BPHE sensor fail", 8: "LWT of BPHE sensor fail",
        9: "Comm fail wired controller - PCB", 10: "Bi-zone sensor fail", 11: "Auxiliary heat LWT sensor fail"}),
    (4106, "Alarm bitmap 2", {
        1: "Temperature difference EWT/LWT too high", 2: "Water flow rate shortage",
        3: "Temperature difference WT/LWT abnormal", 6: "EH feedback protect"}),
    (4107, "Alarm bitmap 3", {
        0: "Condenser sensor fail", 1: "Discharge temp sensor fail",
        3: "BPHE outlet refrigerant high temp protection", 4: "P6 error 3 times in 30 min",
        5: "AC voltage abnormal", 6: "OAT sensor fail", 7: "Over current protection",
        8: "IPM protection (P6)", 9: "3x high discharge temp in 100 min (H6)",
        10: "3x IPM high temp in 60 min (H12)", 11: "EEPROM alarm (E10)",
        12: "High pressure protection (P1)", 13: "3x low pressure in 30 min (H5)",
        14: "2x DC fan motor alarm in 10 min (H9)", 15: "Condenser temp too high (P5)"}),
    (4108, "Alarm bitmap 4", {
        0: "Comm fail IDU - ODU (E2)", 1: "ODU fan motor error (P9)", 2: "IPM temp too high (Pb)",
        3: "IDU quantity decrease (H7)", 4: "3x over current in 60 min (H10)",
        5: "Discharge sensor fail (P4)", 6: "Refrigerant cool pipe sensor fail (Ec)",
        7: "Low pressure protection (P2)"}),
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def raw_int(addr: int) -> str:
    return f"(states('{raw_entity(addr)}') | int(0))"


def avail(addr: int) -> str:
    return f"{{{{ is_number(states('{raw_entity(addr)}')) }}}}"


def guard(addr: int) -> dict:
    return {"condition": "template", "value_template": avail(addr)}


def write(addr: int, value_tpl: str) -> list[dict]:
    return [
        {"service": "modbus.write_register",
         "data": {"hub": HUB, "slave": SLAVE, "address": addr, "value": value_tpl}},
        {"service": "homeassistant.update_entity", "target": {"entity_id": raw_entity(addr)}},
    ]


def raw_sensor(addr: int, hexaddr: str, dtype: str, scan: int, input_type: str = "holding") -> dict:
    return {"name": f"{PREFIX} GCHV R{addr} ({hexaddr})", "unique_id": raw_id(addr), "slave": SLAVE,
            "address": addr, "input_type": input_type, "data_type": dtype, "scan_interval": scan}


def build() -> dict:
    sensors, t_sensors, t_binary, t_numbers, t_selects = [], [], [], [], []
    switches: dict[str, dict] = {}
    raw_defined: set[int] = set()

    for addr, hexaddr, name, itype, dtype, scale, prec, unit, dc, sc, scan in RO_VALUES:
        d = {"name": nice(name), "unique_id": slug(nice(name)), "slave": SLAVE, "address": addr,
             "input_type": itype, "data_type": dtype, "scan_interval": scan}
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

    for addr, hexaddr, dtype, scan in RAW:
        sensors.append(raw_sensor(addr, hexaddr, dtype, scan))
        raw_defined.add(addr)

    def ensure_raw(addr, hexaddr, signed=False, scan=SCAN_CONFIG):
        if addr not in raw_defined:
            sensors.append(raw_sensor(addr, hexaddr, "int16" if signed else "uint16", scan))
            raw_defined.add(addr)

    # numbers
    for addr, hexaddr, name, mn, mx, step, scale, signed, unit in RW_NUMBERS:
        ensure_raw(addr, hexaddr, signed)
        state = f"{{{{ {raw_int(addr)} * {scale} }}}}" if scale != 1 else f"{{{{ {raw_int(addr)} }}}}"
        value = (f"{{{{ (((value | float) / {scale}) | round | int) % 65536 }}}}" if scale != 1
                 else "{{ (value | int) % 65536 }}")
        t_numbers.append({"name": nice(name), "unique_id": slug(f"{PREFIX} gchv w{addr}"),
                          "min": mn, "max": mx, "step": step, "availability": avail(addr),
                          "state": state, "set_value": write(addr, value)})

    # selects
    for addr, hexaddr, name, mapping, signed in RW_SELECTS:
        ensure_raw(addr, hexaddr, signed)
        inv = ", ".join(f"{v}: '{k}'" for k, v in mapping.items())
        fwd = ", ".join(f"'{k}': {v}" for k, v in mapping.items())
        t_selects.append({
            "name": nice(name), "unique_id": slug(f"{PREFIX} gchv w{addr}"),
            "options": "{{ [" + ", ".join(f"'{k}'" for k in mapping) + "] }}",
            "availability": avail(addr),
            "state": f"{{% set v = {raw_int(addr)} %}}{{% set m = {{{inv}}} %}}{{{{ m[v] if v in m else 'Unknown' }}}}",
            "select_option": write(addr, f"{{{{ ({{{fwd}}}[option]) % 65536 }}}}"),
        })

    # 0/1 switches
    for addr, hexaddr, name in RW_SWITCHES:
        ensure_raw(addr, hexaddr, scan=SCAN_STATUS)
        key = slug(nice(name))
        switches[key] = {"unique_id": key, "friendly_name": nice(name),
                         "value_template": f"{{{{ {raw_int(addr)} == 1 }}}}",
                         "turn_on": write(addr, "1"), "turn_off": write(addr, "0")}

    # hh:mm registers -> hour and minute numbers
    for addr, hexaddr, name in TIME_REGS:
        ensure_raw(addr, hexaddr)
        t_numbers.append({"name": nice(f"{name} hour"), "unique_id": slug(f"{PREFIX} gchv w{addr} hour"),
                          "min": 0, "max": 23, "step": 1, "availability": avail(addr),
                          "state": f"{{{{ {raw_int(addr)} // 256 }}}}",
                          "set_value": [guard(addr)] + write(addr, f"{{{{ (value | int) * 256 + ({raw_int(addr)} % 256) }}}}")})
        t_numbers.append({"name": nice(f"{name} minute"), "unique_id": slug(f"{PREFIX} gchv w{addr} minute"),
                          "min": 0, "max": 59, "step": 1, "availability": avail(addr),
                          "state": f"{{{{ {raw_int(addr)} % 256 }}}}",
                          "set_value": [guard(addr)] + write(addr, f"{{{{ ({raw_int(addr)} // 256) * 256 + (value | int) }}}}")})
        t_sensors.append({"name": nice(f"{name} time"), "unique_id": slug(f"{PREFIX} gchv t{addr}"),
                          "availability": avail(addr),
                          "state": f"{{{{ '%02d:%02d' | format({raw_int(addr)} // 256, {raw_int(addr)} % 256) }}}}"})

    # day bitmaps -> one switch per day
    for addr, hexaddr, name in DAY_BITMAPS:
        ensure_raw(addr, hexaddr)
        for day, bit in DAYS:
            mask = 1 << bit
            key = slug(nice(f"{name} {day}"))
            switches[key] = {"unique_id": key, "friendly_name": nice(f"{name} {day}"),
                             "value_template": f"{{{{ {raw_int(addr)} | bitwise_and({mask}) > 0 }}}}",
                             "turn_on": [guard(addr)] + write(addr, f"{{{{ {raw_int(addr)} | bitwise_or({mask}) }}}}"),
                             "turn_off": [guard(addr)] + write(addr, f"{{{{ {raw_int(addr)} | bitwise_and({65535 - mask}) }}}}")}

    # read-only maps
    for addr, name, mapping in RO_MAPS:
        items = ", ".join(f"{k}: '{v}'" for k, v in mapping.items())
        t_sensors.append({"name": nice(name), "unique_id": slug(nice(name)), "availability": avail(addr),
                          "state": f"{{% set v = {raw_int(addr)} %}}{{% set m = {{{items}}} %}}{{{{ m[v] if v in m else 'Unknown ' ~ v }}}}"})
    for addr, name in ((41, "Occupancy mode (raw)"), (44, "Setting mode (raw)"), (45, "Running mode (raw)"),
                       (68, "Frequency reduction / night mode (raw)"), (521, "User interface type (raw)")):
        t_sensors.append({"name": nice(name), "unique_id": slug(nice(name)), "availability": avail(addr),
                          "state": f"{{{{ {raw_int(addr)} }}}}"})

    # bits
    for addr, bit, name, dc in RO_BITS:
        d = {"name": nice(name), "unique_id": slug(nice(name)), "availability": avail(addr),
             "state": f"{{{{ {raw_int(addr)} | bitwise_and({1 << bit}) > 0 }}}}"}
        if dc:
            d["device_class"] = dc
        t_binary.append(d)

    # mask texts
    for addr, name, mapping in MASK_TEXT:
        pairs = ", ".join(f"({v}, '{label}')" for v, label in mapping.items())
        t_sensors.append({"name": nice(name), "unique_id": slug(nice(name)), "availability": avail(addr),
                          "state": f"{{% set v = {raw_int(addr)} %}}{{% set ns = namespace(r=[]) %}}"
                                   f"{{% for b, n in [{pairs}] %}}{{% if v | bitwise_and(b) %}}{{% set ns.r = ns.r + [n] %}}{{% endif %}}{{% endfor %}}"
                                   f"{{{{ ns.r | join(', ') if ns.r else 'None' }}}}"})

    # alarms: per-bitmap text + one combined problem sensor
    alarm_exprs = []
    for addr, name, mapping in ALARMS:
        pairs = ", ".join(f"({1 << b}, '{label}')" for b, label in mapping.items())
        t_sensors.append({"name": nice(name), "unique_id": slug(nice(name)), "availability": avail(addr),
                          "state": f"{{% set v = {raw_int(addr)} %}}{{% set ns = namespace(r=[]) %}}"
                                   f"{{% for b, n in [{pairs}] %}}{{% if v | bitwise_and(b) %}}{{% set ns.r = ns.r + [n] %}}{{% endif %}}{{% endfor %}}"
                                   f"{{{{ ns.r | join(', ') if ns.r else 'OK' }}}}"})
        alarm_exprs.append(f"{raw_int(addr)} > 0")
    t_binary.append({"name": nice("Alarm"), "unique_id": slug(nice("Alarm")), "device_class": "problem",
                     "availability": " and ".join(f"is_number(states('{raw_entity(a)}'))" for a, _, _ in ALARMS).join(["{{ ", " }}"]),
                     "state": "{{ " + " or ".join(alarm_exprs) + " }}"})

    return {
        "modbus": [{"name": HUB, "type": "rtuovertcp", "host": "192.168.1.50", "port": 8899, "sensors": sensors}],
        "template": [{"sensor": t_sensors}, {"binary_sensor": t_binary}, {"number": t_numbers}, {"select": t_selects}],
        "switch": [{"platform": "template", "switches": switches}],
    }


HEADER = """# ---------------------------------------------------------------------------
# Rotenso Windmi (GCHV / Giwee monoblock) Modbus RTU package for Home
# Assistant -- GENERATED by tools/gen_gchv_package.py, do not edit by hand.
#
#   wiring   : RS485 A/B/E terminals of the unit
#   settings : 9600 baud 8N1, slave address 11 (defaults; registers
#              1031H-1033H show the active values)
#   source   : Rotenso Windmi installation manual, "Modbus table"
#              (GCHV addresses, hex without trailing H = decimal), and the
#              owner-verified gist by hvdb
#
# Change the `modbus:` hub to match your adapter: rtuovertcp for a TCP
# gateway (Elfin-EW11 default port 8899), or
#   type: serial, port: /dev/ttyUSB0, baudrate: 9600, bytesize: 8,
#   parity: N, stopbits: 1, method: rtu
# Installer parameters change how the unit protects itself; keep the
# manual's ranges and change one thing at a time.
# ---------------------------------------------------------------------------
"""


def main() -> None:
    sys.stdout.write(HEADER)
    yaml.safe_dump(build(), sys.stdout, sort_keys=False, allow_unicode=True, width=200)


if __name__ == "__main__":
    main()
