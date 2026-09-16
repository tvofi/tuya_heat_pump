# Mapping the remaining registers of your heat pump

This guide is for the moment after you have installed the integration and
want to turn *every* data point (DP, "register") of your heat pump into a
properly named, properly scaled Home Assistant entity. It uses the Rotenso
Windmi (Midea M-Thermal OEM, modelId `000004k4z6`) as the example, but the
steps are the same for every model.

## 0. What you get out of the box

| Layer | What it covers | Where it lives |
|---|---|---|
| **Model file** | The curated, human-named entities for your modelId | `custom_components/tuya_heat_pump/models/<modelId>.py` |
| **Live register discovery** | Every other DP the device reports, typed from the device's own Tuya schema | `discovery.py`, option *Auto-discover unmapped data points* (on by default) |
| **Hidden-DP polling (local mode)** | DPs the device leaves out of its status frame are requested explicitly every 5 minutes | coordinator, `updatedps()` |
| **Services** | `tuya_heat_pump.write_dp` writes any DP by code or id; `tuya_heat_pump.refresh` polls now | `services.py` |
| **Diagnostics** | Full schema + live values + mapping + unmapped codes as one JSON | device page → ⋮ → *Download diagnostics* |

So after installation you already *see* everything the device reports. What
is left is making the discovered entities pretty and permanent, and decoding
raw blobs.

## 1. Install and look at the device page

1. Install the integration (HACS custom repository or copy the folder), restart
   Home Assistant, add the heat pump (Cloud or Local — Local still needs the
   cloud credentials once to fetch the schema).
2. Open *Settings → Devices & services → Tuya Heat Pump → your device*.
   Entities from the model file are listed with their curated names.
   Discovered ones are marked with a `discovered: true` attribute and, when
   writable, appear under **Configuration**. Raw blobs are created **disabled**
   under **Diagnostic**; enable the ones you want to watch.
3. Check the log for the summary line:
   `Register discovery: N extra entities from unmapped data points (...)`.

## 2. Download the diagnostics

Device page → ⋮ → **Download diagnostics**. The JSON contains:

- `schema`: every DP with `dp_id`, `code`, `name` (Tuya's Chinese name),
  `access` (`ro`/`rw`/`wr`), `type` and `spec` (min/max/step/scale/unit, enum
  `range`, bitmap `label`).
- `live_data`: the current value of every DP.
- `entities` / `discovered`: what the model file and discovery created.
- `unmapped_codes`: codes the device reports that nothing reads (should be
  empty while discovery is on).
- `schema_not_reported`: DPs the schema lists but the device has never sent
  (e.g. the `timer` raw DP). In Local mode these are re-requested every 5
  minutes; in Cloud mode they show up as soon as the device reports them.

You can attach this file to a GitHub issue as-is: secrets are redacted.

## 3. Generate a model-file skeleton

The preview script accepts the diagnostics JSON directly:

```bash
cd test
python discovery_preview.py ~/Downloads/tuya_heat_pump-<id>.json
python discovery_preview.py ~/Downloads/tuya_heat_pump-<id>.json ../custom_components/tuya_heat_pump/models/000004k4z6.py
python discovery_preview.py ~/Downloads/tuya_heat_pump-<id>.json ../custom_components/tuya_heat_pump/models/000004k4z6.py --emit-model > extra.py
```

- Without a model file it lists everything; with one it lists only what the
  model file does **not** cover yet.
- `--emit-model` prints those entries in model-file syntax (`SENSOR_TYPES`,
  `SWITCH_TYPES`, …) with a `# dp N — last value: …` comment on each.

## 4. Turn a discovered entity into a curated one

Open `custom_components/tuya_heat_pump/models/000004k4z6.py` and paste the
generated entry into the matching dict, then fix:

| Key | Meaning |
|---|---|
| dict key | becomes the entity's unique id (`<device>_<key>`) — keep it stable |
| `dp_id`, `code` | the Tuya DP; `code` may differ from the key when several entities read one DP |
| `name`, `icon`, `unit`, `device_class`, `state_class` | presentation |
| `conversion` | Python expression on `value`, e.g. `"value / 10"`; may return `None` to hide a sentinel |
| `value_map` | `{raw: label}` lookup for enum-style values |
| `min_value`, `max_value`, `step`, `api_conversion` | numbers: HA range and the expression turning the HA value into the DP value (`"int(value * 10)"`) |
| `options` | selects: `{tuya_key: "Label"}` |
| `entity_category`, `enabled_default` | `"config"`/`"diagnostic"`; create disabled |
| `formula`, `precision` | derived sensor from other sensors, e.g. `"Tout - Tin"` |

Restart Home Assistant (or reload the integration). Because the key is the
same as the discovered entity's key, the entity keeps its id and history and
simply gets the new name and scaling.

Not sure what a DP means? The `tuya_name` attribute (Chinese) is usually more
truthful than the English code — e.g. `temp_current_f` is `水箱温度` = tank
temperature, `switch_microwave` is `水箱电加热` = tank electric heater. For
Midea-based units the Midea M-Thermal service manual and the community
Modbus register lists use the same sensor names (T1, T1B, T3, T4, T5, Tw2,
TW_in/TW_out, Tbt1/Tbt2, Ta, Th, Tp).

## 5. Writable registers that discovery typed read-only

The Tuya schema's `access` decides whether discovery creates a number/switch
or a sensor. If you know a DP is really writable, test it first:

```yaml
service: tuya_heat_pump.write_dp
data:
  code: DHWSET      # or dp_id: 104
  value: 48         # raw DP value: already multiplied by the DP's scale
```

If the device accepts it, promote the entry in the model file to a number,
switch or select. The service logs a warning (but still tries) when the
schema says `ro`.

## 6. Raw blobs (e.g. the Rotenso `timer`, dp 16)

Raw DPs are opaque byte arrays, often several values packed together.

1. Run `test/raw_explorer.py` (see `test/README.md`); it shows every raw DP
   split into int32/int16/uint8 fields, live.
2. Change the corresponding setting in the Tuya / Smart Life app and watch
   which field moves.
3. Add a *raw-field* entity to the model file — the integration reads and
   writes single fields inside the blob for you:

```python
"timer_start_hour": {
    "dp_id": 16,
    "raw_source": "timer",     # the raw DP's code
    "field_index": 2,          # which field
    "encoding": "uint8",       # int32_be | int16_be | uint8
    "name": "Timer start hour",
    "min_value": 0, "max_value": 23, "step": 1,
},
```

Raw-field entries work in `SENSOR_TYPES`, `NUMBER_TYPES`, `SWITCH_TYPES` and
`SELECT_TYPES`.

## 7. Contribute it back

Once the entries are named and verified on the device, open a pull request
(or an issue with the diagnostics JSON attached) in the upstream repository
so the next Rotenso / Midea-OEM owner gets them out of the box.
