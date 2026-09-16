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
| **Rotenso Windmi** monoblock (WIM40X1 … WIM160X3, incl. the 14 kW WIM140X3) and other **Giwee / GCHV** monoblocks | GCHV (Guangdong Carrier HVAC, formerly Chigo), "GCHV" Modbus table in the installation manual pp. 122–123 | `rotenso_windmi_gchv.yaml` | owner-verified read-only map (38 registers) + 2 verified writable setpoints; the rest of the writable table still to be transcribed from the manual |
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

### What the Windmi package contains

- Temperatures (registers 1–11, 51, 4104, 4115, 4131, 4132, 4134; 0.1 °C):
  outdoor, indoor, inlet (ETW), outlet (LWT), refrigerant, discharge, air
  exchanger, water control point, LWT after the plate heat exchanger, IPM
  refrigerant pipe (TL), IPM module (T9), T30 defrost calculation, target
  discharge.
- Status: setting mode, running mode, occupancy mode, frequency reduction
  (night) mode, user interface type, backup heater type, warm-up time, water
  ΔT setpoint (raw values; the enumerations are in the manual's table).
- Compressor and hydraulics: actual/required compressor frequency, pump
  speed, capacity demand (IDU side and after ODU rectify), actual capacity
  output, unit capacity, fan speeds (required/actual, upper/lower motor),
  EXV opening, AC current, water flow feedback, compressor and pump runtime.
- Writable (verified from the manual): occupied heating air setpoint
  (01A5H = 421, 16–32 °C) and booster delta temperature (025BH = 603,
  1–20 °C). Both are written as temperature × 10 with function 0x06.

### Completing the writable table

The manual's Modbus table (installation & user manual, pages 122–123, and
the wired controller manual's "Modbus parameters" page) lists the writable
parameters with function codes 0x06/0x10: operating mode (0259H, values
0–7), warm-up time (025AH), booster OAT threshold (025CH), backup heater
settings, water setpoints, on/off, and more. Add each verified row to
`WRITABLE` in `tools/gen_gchv_package.py` as
`(decimal_address, "hexH", "name (unit)", min, max, step, scale, "unit")`
and regenerate:

```bash
python tools/gen_gchv_package.py > docs/modbus/rotenso_windmi_gchv.yaml
```

If you can share those two pages (photo or text), the table can be completed
in one pass.

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
