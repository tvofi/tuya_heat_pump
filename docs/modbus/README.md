# Installer parameters over Modbus (Midea M-Thermal OEMs: Rotenso Windmi, Kaisai, Fisher, …)

## Why a second connection

The Tuya Wi-Fi module of these heat pumps exposes about 25 data points: power,
mode, the two setpoints, a dozen temperatures, a fault bitmap. The installer
menu of the indoor unit (**FOR SERVICEMAN**: backup heater IBH thresholds and
power, DHW tank heater TBH, double zone, room thermostat type, weather curves,
T4 limits, disinfection, holiday, pump delays, floor drying, …) is **not in the
Tuya schema**, so no Tuya-based integration can read or write it. You can
verify this on your own device: *Download diagnostics* on the heat pump and
look at `schema` — every DP the module knows is listed there.

The same parameters are all available on the indoor unit's **Modbus RTU** port
and that is what this package uses. It runs next to the Tuya integration; the
Tuya side keeps doing what it does, Modbus adds the rest.

## Hardware

- An **RS485 adapter**: a USB RS485 dongle plugged into the Home Assistant
  host (`type: serial`), or an RS485-to-Ethernet/Wi-Fi gateway such as a
  Waveshare/Elfin/USR device in "Modbus RTU over TCP" mode (`type:
  rtuovertcp`). Any of them works; no ESPHome board is required (an ESPHome
  board also works, see the Mosibi project linked below).
- Wiring on the **wired controller** (the display of the indoor unit): remove
  the front panel, open the display's back panel, find terminals **H1**, **H2**
  and **E** on its PCB. Connect **A+ → H2**, **B− → H1**, shield/GND → E.
  Some units have the same H1/H2 pair on the hydraulic module's terminal strip
  as well. Power the unit down before touching anything.
- Bus settings: **9600 baud, 8 data bits, no parity, 1 stop bit**, Modbus
  address **1** (change `slave:` in the package if your unit is set to
  another address in FOR SERVICEMAN → HMI ADDRESS SET).

## Installation

1. Pick the file for your generation:
   - `midea_mthermal_r32.yaml` — R32 units (Rotenso Windmi TWM, most 2019–2023
     Midea OEMs). About 300 entities.
   - `midea_mthermal_r290.yaml` — R290 units (Windmi R290, Arctic R290,
     Nature). Adds energy metering, COP, IBH/TBH/AHS enabled status, zone 2
     custom curves, solar. About 385 entities.
2. Copy it to `<config>/packages/` and make sure packages are enabled in
   `configuration.yaml`:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
3. Edit the `modbus:` block at the top for your adapter:
   ```yaml
   modbus:
     - name: heatpump
       type: serial            # USB dongle
       port: /dev/ttyUSB0
       baudrate: 9600
       bytesize: 8
       parity: N
       stopbits: 1
       method: rtu
   ```
   or, for a TCP gateway:
   ```yaml
   modbus:
     - name: heatpump
       type: rtuovertcp
       host: 192.168.1.50
       port: 502
   ```
4. Check the configuration and restart Home Assistant. Entities are prefixed
   `HP …`; raw transport sensors are named `HP MB R<register>`.

## What you get

| Group | Examples | Entity type |
|---|---|---|
| Live values | Tw_in, Tw_out, T1, T1B, T2, T2B, T3, T4, T5, Ta, Tbt1/2, Tp, Th, TF, pressures, current, voltage, compressor and fan speed, flow, DC bus, curve targets | sensor |
| Status | operating mode, current fault + 3 history entries with code and description, defrost, anti-freeze, remote on/off, load outputs (IBH1, IBH2, TBH, pumps, valves, AHS, alarm) | sensor / binary sensor |
| Control | power per zone/DHW, mode, T1S zone 1/2, Ts, T5S, weather curve zone 1/2, silent mode + level, ECO, holiday home, disinfect, DHW recirculation, forced DHW/TBH/IBH | switch / select / number |
| **FOR SERVICEMAN** | DHW mode/priority/pump, dT5_ON, dT1S5, T4DHWMAX/MIN, t_INTERVAL_DHW, TBH (dT5_TBH_OFF, T4_TBH_ON, t_TBH_DELAY, **P_TBH**), disinfection (T5S_DI, t_DI_MAX, t_DI_HIGHTEMP), cooling and heating mode settings (T4CMAX/MIN, T4HMAX/MIN, dT1SC/H, dTSC/H, intervals, T1SetC1/2, T4C1/2, T1SetH1/2, T4H1/2, emitter types per zone, t_DELAY_PUMP), auto mode (T4AUTOCMIN/HMAX), temperature type (room / water flow / **double zone**), room thermostat (installed, mode, dual), **backup heater IBH** (T4_IBH_ON, dT1_IBH_ON, t_IBH_DELAY, IBH LOCATE, **P_IBH1**, **P_IBH2**), additional heat source AHS (T4_AHS_ON, dT1_AHS_ON, t_AHS_DELAY, M1M2 for AHS), holiday away setpoints, power input limitation, input define (Tbt1, Tbt2, Ta, Ta-adj, T1B/Tw2, solar input, pipe length, RT/Ta_PCB, PUMP_I silent), cascade (PER_START, TIME_ADJUST), floor drying and pre-heating | number / switch / select |

Regarding the three settings that prompted this: **IBH enabled**, **number of
IBH steps** and **TBH installed** are hardware choices on Midea units (DIP
switches S1/S2 on the hydraulic module, see the installation manual). They are
therefore *read-only* here: register 129 shows which heater outputs are live,
register 210 bit 14 reports "TBH supported", and on R290 units register 198
reports IBH/TBH/AHS enabled. Their thresholds, delays and rated powers
(P_IBH1, P_IBH2, P_TBH) are writable.

## Safety and caveats

- Serviceman parameters change how the unit protects itself. Change one at a
  time and keep the manual's ranges (the numbers are limited to them).
- Writes to bit and packed registers are read-modify-write from the last
  polled value and are blocked while that value is unknown, so a bad bus
  never clears other bits by accident.
- Registers 200–208 are read-only limits reported by the unit; 209 and up are
  writable.
- The register map is community knowledge (Mosibi/Midea-heat-pump-ESPHome,
  Apache-2.0, cross-checked with the Warm-Energy Modbus database and the
  Midea wired-controller manual). It has been used on many Midea OEM units
  but not by us on a Rotenso Windmi; if a value looks wrong, compare with the
  wired controller and open an issue with the register number.
- Polling ~150–200 registers at 9600 baud takes a few seconds per cycle; the
  package uses 30 s for live values and 120 s for settings. Lower
  `scan_interval` values are fine on a dedicated bus.

## Regenerating

`tools/gen_modbus_package.py` holds the register tables and writes the
packages; edit the tables rather than the YAML:

```bash
python tools/gen_modbus_package.py        > docs/modbus/midea_mthermal_r32.yaml
python tools/gen_modbus_package.py --r290 > docs/modbus/midea_mthermal_r290.yaml
```

## Credits

- Register map: [Mosibi/Midea-heat-pump-ESPHome](https://github.com/Mosibi/Midea-heat-pump-ESPHome) (Apache-2.0), the reference ESPHome implementation for Midea heat pumps and clones.
- Cross-checks: [Warm-Energy/Heat-Pump-Modbus-Database](https://github.com/Warm-Energy/Heat-Pump-Modbus-Database) and the Midea M-Thermal wired-controller operation manual (FOR SERVICEMAN menu).
