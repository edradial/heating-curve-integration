# Heating Curve (Weather Compensation) — Home Assistant Integration

A weather-compensation heating curve as a proper Home Assistant integration.
It creates its own point entities, computes the interpolated setpoint for
the current outdoor temperature, writes it to a Modbus holding register,
and serves its own dashboard card — all through one config flow, no YAML,
no manually-created helpers.

## What it creates

For each configured curve:

- N `number` entities ("Point @ X°C") — drag/edit these to shape the curve.
  Values are restored across restarts.
- 1 `sensor` entity ("Target") — the live interpolated setpoint for the
  current outdoor temperature.
- A background task that recomputes the target whenever a point changes,
  whenever the outdoor sensor changes, and every 10 minutes as a fallback,
  and writes it to your Modbus register (only while the optional on/off
  entity, if configured, is "on").

## Installation

1. HACS → Integrations → ⋮ → **Custom repositories**
2. Add this repository URL, category **Integration**
3. Find "Heating Curve (Weather Compensation)" → **Install**
4. **Restart Home Assistant** (required for a new integration, unlike
   frontend cards)

## Setup

Settings → Devices & Services → **+ Add Integration** → search
"Heating Curve"

Fill in the form:

| Field | What to enter |
|---|---|
| Name | Whatever you like, e.g. "Heat Pump Curve" |
| Number of curve points | e.g. 9 |
| Outdoor temp at coldest / warmest point | e.g. -20 and 20 |
| Min / Max allowed setpoint | the valid range for YOUR device's register (check its protocol document) |
| Outdoor temperature sensor | your own outdoor temp sensor |
| Modbus hub name | exactly as configured under `modbus:` in your `configuration.yaml` |
| Setpoint holding register address | from YOUR device's protocol document — do not assume it matches someone else's setup, even the same model |
| Modbus slave/unit ID | usually 1 |
| On/off switch (optional) | the integration only writes while this is "on" |

Submit — the entities are created immediately, with a sensible default
straight-line curve you can then drag into shape.

## Adding the card to your dashboard

The card (`custom:heating-curve-card`) is registered automatically by the
integration — no separate HACS Frontend install, no manual Resources step.

Right after setup finishes, the integration sends a **notification** (bell
icon, top right) with a ready-to-paste YAML block that already has the
correct entity IDs filled in — no need to hunt through Developer Tools.
Open a dashboard, **Edit Dashboard → Edit in YAML**, and paste the block
into any section's `cards:` list.

If you ever need it again, or the notification was dismissed before you
copied it, check **Settings → Devices & Services → Heating Curve →
\<your curve name\>** to see the exact entity IDs, and use this template:

```yaml
type: custom:heating-curve-card
title: Weather Compensation Curve
unit: "°C"
y_min: 20          # match what you entered during setup
y_max: 60
service_domain: number
current_x_entity: sensor.YOUR_OUTSIDE_TEMP_SENSOR
current_y_entity: sensor.YOUR_CURVE_NAME_target
points:
  - x: -20
    entity: number.YOUR_CURVE_NAME_point_20_0_c
  - x: -15
    entity: number.YOUR_CURVE_NAME_point_15_0_c
  # ...one entry per point, exact IDs from the device page
```

## Notes / limitations

- Settings entered during setup (hub name, register, ranges, etc.) cannot
  currently be edited from the UI afterwards — remove and re-add the
  integration to change them. Point values themselves (the curve shape) are
  of course editable anytime via the number entities / card.
- Turn off any built-in weather-compensation feature on your controller
  itself, if it has one — otherwise it may fight with this curve for the
  same register.
- `hass.http.register_static_path` (used to serve the card) is deprecated
  in very recent Home Assistant core versions in favor of an async
  variant; it still works but may log a deprecation warning. This will be
  updated in a future release of this integration.
- Double- and triple-check the register address and hub name for YOUR
  device before relying on this for anything safety-critical.
