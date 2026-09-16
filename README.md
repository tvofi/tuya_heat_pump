# Tuya Heat Pump - Home Assistant Integration

<img src="https://raw.githubusercontent.com/Korkuttum/tuya_heat_pump/main/images/heatpump.webp" width="200">

 ⚠️ **Note:**  
> This integration has only been tested with the heat pump brands listed below.  
> If your heat pump is a different brand and the integration does not work, please run the script at the following link and share the generated file with me:  
> [tuya_api_test.py](https://github.com/Korkuttum/tuya_heat_pump/blob/main/test/tuya_api_test.py)

### Supported Brands
📋 **[Detailed list](https://github.com/Korkuttum/tuya_heat_pump/blob/main/supported_models.md)**

| No | Brand | | No | Brand | | No | Brand |
|---|---|---|---|---|---|---|---|
| 1 | Arçelik (Beko, Grundig) | | 17 | Fairland | | 33 | Poolex Dreamline |
| 2 | Alsavo by Zealux | | 18 | Fairland Inverter Plus | | 34 | Poolsana |
| 3 | ACIQ | | 19 | GRAT | | 35 | Power World |
| 4 | Adlar Castra | | 20 | Heative Next | | 36 | Power World PW030 |
| 5 | Adlar Castra Domestic | | 21 | Inventor Xforce | | 37 | Power World R290 Full DC |
| 6 | Alps Exclusive | | 22 | IPS Pool Systems | | 38 | Pure Blue Onyx |
| 7 | Aquark | | 23 | ITS | | 39 | Reclaim Eco R290 |
| 8 | Aquastrong | | 24 | Ivapool | | 40 | Rotenso Windmi |
| 9 | Aquatech X6 | | 25 | Kensol | | 41 | SolarEast |
| 10 | Aquatech X6 320L | | 26 | Kushiro (Luqstoff) | | 42 | SolarEast BLN |
| 11 | Cordivari Vestalis | | 27 | Lunna LV LT1530 (Nordic LV LT1530) | | 43 | Swim&Fun Fjord |
| 12 | Della | | 28 | Macon/Arctic | | 44 | Water TechniX |
| 13 | Ecologic Ecopool | | 29 | Mango | | 45 | W'eau |
| 14 | Effecta Air-IQ R290 | | 30 | Mitte Aerotermia | | 46 | W'eau WFI-007 |
| 15 | EnviroSun HP+ | | 31 | Mr. Silent FC25 (Aquara Pool Inverter) | | 47 | Wopoltop |
| 16 | Evoheat 40T | | 32 | MyCond BeeThermic | | | |

---

This project allows you to control and monitor your Tuya heat pump device through Home Assistant — supports Cloud, Local (LAN push), and optional real-time MQTT push on top of Cloud mode.

---

## Prerequisites

### Enabling Tuya IoT Cloud Service

To use this integration, you need to create a project in the Tuya IoT Platform, grant API access, and link your device to the project.

**Steps:**

1. Log in to ***[Tuya IoT Platform](https://iot.tuya.com/)***.
2. Go to ***Cloud > Project Management*** and create a new project or select an existing one.
3. Select the ***Devices*** tab:
   - If your devices are already listed, proceed to the next step.
   - If you have no devices yet, open the ***Link App Account*** tab below. Click the ***Add App Account*** button on the right, then select ***Tuya App Account Authorization***. Scan the QR code using your Tuya mobile app and grant permission. Your devices will then appear.
4. Click on the ***Service API*** tab above, then click the ***Go to Authorize*** button and add the following APIs to your project:
   - ***IoT Core***
   - ***Smart Home Basic Service***
   - ***Device Status Notification***
   - ***Authorization Token Management***
5. Retrieve your ***Access ID*** and ***Access Secret*** from the project panel.

> ⚠️ **Important:** The integration will not work without API authorization and device linking.

---

## Installation

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Korkuttum&repository=tuya_heat_pump&category=integration)

### Method 1: Installation via HACS (Recommended)

1. Make sure you have **HACS** installed in your Home Assistant instance.
2. Go to **HACS** → **Integrations**.
3. Click the search icon in the top right and search for **"Tuya Heat Pump"**.
4. Click **Download** on the integration.
5. Restart Home Assistant.

### Method 2: Manual Installation

1. Download the latest release from the [GitHub repository](https://github.com/Korkuttum/tuya_heat_pump).
2. Extract the files and copy the `tuya_heat_pump` folder into your Home Assistant `custom_components` directory.
3. Restart Home Assistant.
---

## Connection Types Compared

| Connection Type | Tuya IoT Account | Local Key | Internet (after setup) | Data Updates | Cloud API Load | Extra Setup |
|---|:---:|:---:|:---:|---|---|---|
| **Local** | ✅ | ✅ | ❌ Not required | Real-time push | None | Device IP + Local Key |
| **Cloud** | ✅ | ❌ | ✅ Required | Poll interval | Regular polling | — |
| **Cloud + MQTT** | ✅ | ❌ | ✅ Required | Real-time push | Minimal | User Code + QR scan |

---

## Configuration

After installation, restart Home Assistant and follow these steps:

1. Go to “Settings > Devices & Services”.
2. Click “Add Integration”.
3. Search for and select “Tuya Heat Pump”.
4. For Cloud mode: enter your Tuya IoT Platform credentials:
    - Access ID
    - Access Secret
    - Device ID
5. For Local mode: switch the Connection Type to “Local” and enter:
    - Device IP
    - Local Key
    - Protocol (e.g. 3.3 / 3.4)
    - Device ID

### Optional: Enabling MQTT (Real-time Push)

On top of Cloud mode, you can optionally enable real-time MQTT push via the Tuya Sharing (Smart Life app) broker — instant state updates instead of waiting on the poll interval, and less load on the Tuya cloud API.

- During setup (Cloud mode), enter your **User Code** and complete the **QR scan** with the Smart Life / Tuya app when prompted.
- This step is entirely optional — skip it and the integration works exactly as before.
- If the push token ever becomes invalid, you'll see a clickable **Repair** notification under *Settings > System > Repairs* to reconnect.

### Live register discovery (every data point, mapped or not)

A model file only knows the data points its author labelled. Everything else your heat pump reports used to be invisible. With **Auto-discover unmapped data points** (on by default, toggle it in the integration's *Configure* dialog) the integration reads the device's full Tuya *thing model* — the same register map the Smart Life app renders its UI from — and creates an entity for every data point the model file does not cover:

| Tuya type | Read-only | Writable |
|---|---|---|
| `value` | sensor (unit, scale and device class from the schema) | number (min/max/step/scale from the schema) |
| `bool` | binary sensor | switch |
| `enum` | sensor (labelled) | select |
| `bitmap` | "… Description" sensor listing active flags + problem binary sensor | — |
| `raw` / `string` | diagnostic sensor (raw blobs are created disabled) | — |

- Discovered entities carry a `discovered: true` attribute plus `tuya_name` (Tuya's own, often Chinese, name — translated to English where possible), `tuya_type` and `tuya_access`.
- Writable discovered entities appear under *Configuration* on the device page. They write the same DP the Tuya app writes.
- Works in Cloud and Local mode. Local mode still needs the cloud credentials once to fetch the schema; it is cached in the config entry afterwards. Without any schema (e.g. no cloud), unknown local DPs are exposed read-only as `DP <id>`.
- Curated model files always win: a discovered entity never replaces one defined in `models/`.
- **Download diagnostics** (device page → ⋮ → *Download diagnostics*) gives you the full schema, live values, the mapping in use and the list of still-unmapped codes — attach it when requesting a model file.
- In **Local** mode, known DPs the device leaves out of its status frame are requested explicitly every 5 minutes, so settings and counters that are normally hidden still show up.
- Two services complete the picture: `tuya_heat_pump.write_dp` writes any DP by code or id (for registers without an entity, or ones the schema wrongly marks read-only) and `tuya_heat_pump.refresh` polls immediately.
- Step-by-step guide to turning discovered entities into curated ones, decoding raw blobs and generating a model file from the diagnostics: 📖 **[docs/MAPPING_REGISTERS.md](https://github.com/Korkuttum/tuya_heat_pump/blob/main/docs/MAPPING_REGISTERS.md)**

---

## Notes

- You can monitor and control features like temperature, operation mode, and fan speed.
- Easily use in automations and dashboards.

---

## Diagnostic & Setup Scripts

Standalone scripts for onboarding new devices and debugging — run manually on your own computer, outside Home Assistant. 📖 **[Full guide →](https://github.com/Korkuttum/tuya_heat_pump/blob/main/test/README.md)**

- [`tuya_api_test.py`](https://github.com/Korkuttum/tuya_heat_pump/blob/main/test/tuya_api_test.py) — pulls your device's full cloud schema and live values, start here for any new device.
- [`lokal_key_extractor.py`](https://github.com/Korkuttum/tuya_heat_pump/blob/main/test/lokal_key_extractor.py) — tries to recover your device's Local Key for LAN mode.
- [`tuya_dps_explorer.py`](https://github.com/Korkuttum/tuya_heat_pump/blob/main/test/tuya_dps_explorer.py) — reads raw DP values directly over your local network.
- [`raw_explorer.py`](https://github.com/Korkuttum/tuya_heat_pump/blob/main/test/raw_explorer.py) — live GUI for decoding hidden raw data-points, like a missing target temperature setting.
- [`discovery_preview.py`](https://github.com/Korkuttum/tuya_heat_pump/blob/main/test/discovery_preview.py) — shows offline which extra entities live register discovery would create from a `tuya_api_test.py` dump.

---

## Support My Work

If you find this integration helpful, consider supporting the development:

[![Become a Patreon](https://img.shields.io/badge/Become_a-Patron-red.svg?style=for-the-badge&logo=patreon)](https://www.patreon.com/korkuttum)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This integration is an independent project and is not affiliated with, endorsed by, or connected to Tuya Inc. in any way. This is a community project provided "as is" without warranty of any kind. Use at your own risk.
