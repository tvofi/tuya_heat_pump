# Installer parameters over Modbus

## Why a second connection

The Tuya Wi-Fi module of these heat pumps exposes about 25 data points: power,
mode, the two setpoints, a dozen temperatures, a fault bitmap. The installer
menu (backup heater, DHW tank heater, double zone, room thermostat type,
weather curves, ambient limits, disinfection, holiday, pump delays, …) is
**not in the Tuya schema**, so no Tuya-based integration can read or write
it. You can verify this on your own device: *Download diagnostics* on the
heat pump and look at `schema` — every DP the module knows is listed there.

Those parameters are available on the unit's **Modbus RTU** port instead.
The packages in this folder use only Home Assistant's built-in `modbus` and
`template` integrations and run next to the Tuya integration.

## Which package is for which unit

| Unit | Manufacturer / controller | Package | Status |
|---|---|---|---|
| **Rotenso Windmi** monoblock (WIM40X1 … WIM160X3, incl. the 14 kW WIM140X3) and other **Giwee / GCHV** monoblocks | GCHV (Guangdong Carrier HVAC, formerly Chigo), "GCHV" Modbus table in the installation manual pp. 122–123 | `rotenso_windmi_gchv.yaml` | manual's Modbus table rows 20–159 transcribed (219 entities: every writable setpoint, curve, DHW/anti-legionella schedule, backup heater type, I/O configuration, decoded alarms); rows 1–19, 84–106, 137–138, 150–158 still to add |
| Midea M-Thermal OEMs: **Kaisai** KHC/KMK, **Airwell** Wellea, **Ferroli** Omnia, **Inventor** Matrix, **Kaysun** Aquantia, **YORK**, Midea Arctic/Nature | Midea, wired controller H1/H2 | `midea_mthermal_r32.yaml`, `midea_mthermal_r290.yaml` | full community map, every FOR SERVICEMAN parameter writable |

**Do not use the Midea packages on a Rotenso Windmi.** The Windmi's register
layout is completely different (hexadecimal GCHV addresses such as 0174H,
decimal 372) and writing Midea addresses to it would set unrelated
parameters.

How the Windmi was identified: a Windmi owner's working Home Assistant
configuration ([gist by hvdb](https://gist.github.com/hvdb/a6a6fdc889573084ac2bdd53e71303c7))
uses slave address 11 on the unit's A/B/E terminals with registers 1–11,
23, 41–45, 51, 68, 85, 372, 374, 521, 569, 601, 602 and 4097–4138, all of
which match the "GCHV address" column of the Rotenso Windmi installation
manual (0174H compressor runtime = 372, 0176H pump runtime = 374, 1006H unit
capacity = 4102, 0017H compressor frequency = 23). GCHV is Guangdong Carrier
Heating, Ventilation & Air Conditioning; its ATW monoblock is sold as
"Giwee" and rebadged by Rotenso.

## Rotenso Windmi (GCHV): hardware and setup

- **Port**: the A / B / E terminals ("ABE") on the unit's terminal strip.
  A+ → A, B− → B, shield → E. Power the unit down before wiring.
- **Bus**: Modbus RTU, default **9600 baud, 8N1, slave address 11**
  (configurable in the wired controller's Modbus parameter menu).
- **Adapter**: an RS485-to-Ethernet/Wi-Fi gateway in Modbus RTU-over-TCP
  mode (the owner used an Elfin-EW11 powered from the unit's USB port;
  `type: rtuovertcp`, port 8899 is the Elfin default) or a USB RS485 dongle
  (`type: serial`, `port: /dev/ttyUSB0`, `baudrate: 9600`, `parity: N`,
  `stopbits: 1`, `bytesize: 8`, `method: rtu`).
- Copy `rotenso_windmi_gchv.yaml` to `<config>/packages/` (enable packages
  with `homeassistant: packages: !include_dir_named packages`), edit the
  `modbus:` block for your adapter, restart.

### What the Windmi package contains (219 entities)

Transcribed from the manual's Modbus table (rows 20–159) plus the owner
gist for rows 1–19:

- **Temperatures** (0.1 °C): outdoor, indoor, inlet EWT, outlet LWT,
  refrigerant, discharge, air exchanger, DHW tank, LWT after the plate heat
  exchanger (Tw-out), IPM refrigerant pipe, IPM module (T9), T30 defrost
  calculation, target discharge.
- **Compressor / hydraulics**: actual and required compressor frequency,
  pump speed, capacity demand (IDU side, after ODU rectify) and actual
  output, unit capacity, fan speed level and upper/lower motor rpm
  (required and actual), EXV opening (required and actual), AC/DC current
  and voltage, water flow, compressor and pump runtime, ODU program and
  EEPROM version, Modbus baud/parity/ID as seen by the unit.
- **Status**: DHW mode, DHW valve, flow switch, discrete inputs 5–8, ODU
  output relays (fan H/L, compressor and chassis heater, PTC, SV1, SV2,
  4-way valve), low/high pressure switches, compressor frequency limitation
  reasons 1 and 2 (decoded), P6/IPM protection reason (decoded), the four
  **alarm bitmaps decoded to text** (sensor fails, protections with the
  E/P/H code from the manual) and one combined *Alarm* problem sensor.
- **Writable setpoints** (numbers, 0.5 °C steps): water control point;
  occupied/unoccupied/economic heating and cooling water setpoints and
  offsets; occupied/unoccupied/economic heating and cooling air setpoints
  and offsets; DHW normal, economic and anti-legionella setpoints; heating
  and cooling curve setpoint offsets; custom heating and cooling curve
  points (min/max OAT, min/max LWT); minimum OAT for heating with
  compressor; water ΔT setpoint; warm-up time; booster delta temperature
  and OAT threshold.
- **Writable selections**: heating climatic curve (none / custom / 1–12),
  cooling climatic curve (none / custom / 1–2), **backup heater type**
  (inner EH, DHW EH, gas boiler combinations, none), control mode (water or
  ambient temperature), function of discrete inputs 5–8 and discrete
  outputs 5, 8, 9.
- **Writable switches**: DHW priority, forced discrete outputs 5/8/9, and
  the day-of-week bitmaps of the DHW and anti-legionella schedules (one
  switch per day).
- **Schedule times** (hour and minute numbers, plus a read-only hh:mm
  sensor): night mode start/end, DHW schedule start/stop, anti-legionella
  start.

Not yet covered: rows 1–19 beyond the temperatures (the on/off and
mode-setting registers, occupancy, night mode enable), rows 84–106 and
137–138, 150–158 — those manual pages were not available. The registers
41, 44, 45, 68 and 521 from the owner gist are exposed raw until their
value tables are known.

### Completing the table

Add rows to the tables at the top of `tools/gen_gchv_package.py`
(`RO_VALUES`, `RW_NUMBERS`, `RW_SELECTS`, `RW_SWITCHES`, `TIME_REGS`,
`DAY_BITMAPS`, `RO_MAPS`, `RO_BITS`, `ALARMS`) and regenerate:

```bash
python tools/gen_gchv_package.py > docs/modbus/rotenso_windmi_gchv.yaml
```

## Midea M-Thermal OEMs: hardware and setup

- Wiring on the **wired controller** (the display of the indoor unit):
  terminals **H1**, **H2** and **E** on its PCB. **A+ → H2**, **B− → H1**,
  shield → E.
- Bus: 9600 baud, 8N1, Modbus address 1 (FOR SERVICEMAN → HMI ADDRESS SET).
- Pick `midea_mthermal_r32.yaml` (R32 units, about 300 entities) or
  `midea_mthermal_r290.yaml` (R290 units, about 385 entities: adds energy
  metering, COP, IBH/TBH/AHS enabled status, zone 2 custom curves, solar).
- Every FOR SERVICEMAN parameter is exposed as a number, switch or select:
  DHW settings, tank heater TBH (dT5_TBH_OFF, T4_TBH_ON, t_TBH_DELAY,
  P_TBH), disinfection, cooling/heating limits and curves, emitter types,
  double zone, room thermostat, backup heater IBH (T4_IBH_ON, dT1_IBH_ON,
  t_IBH_DELAY, IBH LOCATE, P_IBH1, P_IBH2), additional heat source, holiday
  setpoints, power limitation, input define, cascade, floor drying.
- Bit and packed registers are read-modify-written from the last polled
  value and blocked while that value is unknown.

## Safety and caveats

- Installer parameters change how a unit protects itself. Change one at a
  time and keep the manual's ranges.
- None of the packages has been run by us on a real bus. Confirm that the
  unit answers at the expected slave address before writing anything, and
  compare values with the wired controller.
- Polling 40–200 registers at 9600 baud takes a few seconds per cycle; the
  packages use 30 s for live values and 120 s for settings.

## Regenerating

`tools/gen_gchv_package.py` (Rotenso Windmi / GCHV) and
`tools/gen_modbus_package.py` (Midea) hold the register tables; edit the
tables rather than the YAML.

## Credits

- Rotenso Windmi register list: [hvdb's Home Assistant gist](https://gist.github.com/hvdb/a6a6fdc889573084ac2bdd53e71303c7) and the Rotenso Windmi installation & user manual (GCHV Modbus table).
- Midea register map: [Mosibi/Midea-heat-pump-ESPHome](https://github.com/Mosibi/Midea-heat-pump-ESPHome) (Apache-2.0), cross-checked with [Warm-Energy/Heat-Pump-Modbus-Database](https://github.com/Warm-Energy/Heat-Pump-Modbus-Database) and the Midea M-Thermal wired-controller manual.
