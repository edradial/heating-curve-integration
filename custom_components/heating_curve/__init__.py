from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)

from .const import (
    CONF_GRID_MAX,
    CONF_GRID_MIN,
    CONF_MODBUS_HUB,
    CONF_MODBUS_UNIT,
    CONF_ONOFF_ENTITY,
    CONF_OUTSIDE_SENSOR,
    CONF_POINT_COUNT,
    CONF_REGISTER,
    DOMAIN,
    FRONTEND_JS_FILENAME,
    FRONTEND_URL_BASE,
)

_LOGGER = logging.getLogger(__name__)

WRITE_INTERVAL = timedelta(minutes=10)


class HeatingCurveManager:
    """Holds the curve's point entities and computes/applies the setpoint."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self.points: dict[int, "HeatingCurvePoint"] = {}
        self.target_entity = None

    def register_point(self, index: int, entity) -> None:
        self.points[index] = entity

    def register_target(self, entity) -> None:
        self.target_entity = entity

    def compute_target(self) -> float | None:
        cfg = self.entry.data
        point_count = cfg[CONF_POINT_COUNT]

        if len(self.points) < point_count:
            return None

        grid_min = cfg[CONF_GRID_MIN]
        grid_max = cfg[CONF_GRID_MAX]
        step = (grid_max - grid_min) / (point_count - 1) if point_count > 1 else 0
        grid = [grid_min + step * i for i in range(point_count)]

        vals = []
        for i in range(point_count):
            point = self.points.get(i)
            if point is None or point.native_value is None:
                return None
            vals.append(point.native_value)

        outside_state = self.hass.states.get(cfg[CONF_OUTSIDE_SENSOR])
        if outside_state is None or outside_state.state in ("unknown", "unavailable"):
            return None
        try:
            t = float(outside_state.state)
        except ValueError:
            return None

        t = max(grid[0], min(grid[-1], t))

        for i in range(point_count - 1):
            if grid[i] <= t <= grid[i + 1]:
                span = grid[i + 1] - grid[i]
                ratio = (t - grid[i]) / span if span else 0
                return round(vals[i] + (vals[i + 1] - vals[i]) * ratio, 1)

        return vals[-1]

    async def async_recompute_and_apply(self, *_args) -> None:
        value = self.compute_target()
        if value is None:
            return

        if self.target_entity is not None:
            self.target_entity.update_value(value)

        cfg = self.entry.data
        onoff_entity = cfg.get(CONF_ONOFF_ENTITY)
        if onoff_entity:
            onoff_state = self.hass.states.get(onoff_entity)
            if onoff_state is None or onoff_state.state != "on":
                return

        try:
            await self.hass.services.async_call(
                "modbus",
                "write_register",
                {
                    "address": cfg[CONF_REGISTER],
                    "hub": cfg[CONF_MODBUS_HUB],
                    "unit": cfg[CONF_MODBUS_UNIT],
                    "value": int(round(value)),
                },
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Heating Curve: failed to write modbus register")


async def _async_register_frontend(hass: HomeAssistant) -> None:
    if hass.data.get(DOMAIN, {}).get("_frontend_registered"):
        return
    www_path = Path(__file__).parent / "www"
    js_path = www_path / FRONTEND_JS_FILENAME
    if not js_path.exists():
        _LOGGER.warning("Heating Curve: frontend file not found at %s", js_path)
        return
    try:
        hass.http.register_static_path(
            f"{FRONTEND_URL_BASE}/{FRONTEND_JS_FILENAME}",
            str(js_path),
            cache_headers=False,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Heating Curve: failed to register static path")
        return
    add_extra_js_url(hass, f"{FRONTEND_URL_BASE}/{FRONTEND_JS_FILENAME}")
    hass.data.setdefault(DOMAIN, {})["_frontend_registered"] = True


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    await _async_register_frontend(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    await _async_register_frontend(hass)

    manager = HeatingCurveManager(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = manager

    # number platform must finish registering points before sensor platform
    # (which only reads point values, never creates them) is set up.
    await hass.config_entries.async_forward_entry_setups(entry, ["number"])
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    remove_outside = async_track_state_change_event(
        hass, [entry.data[CONF_OUTSIDE_SENSOR]], manager.async_recompute_and_apply
    )
    remove_interval = async_track_time_interval(
        hass, manager.async_recompute_and_apply, WRITE_INTERVAL
    )
    entry.async_on_unload(remove_outside)
    entry.async_on_unload(remove_interval)

    await manager.async_recompute_and_apply()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, ["number", "sensor"]
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
