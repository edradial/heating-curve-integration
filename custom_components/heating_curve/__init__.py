from __future__ import annotations

import asyncio
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
    CONF_Y_MAX,
    CONF_Y_MIN,
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


async def _wait_for_entity_ids(manager: "HeatingCurveManager", timeout: float = 5.0) -> bool:
    elapsed = 0.0
    while elapsed < timeout:
        if manager.target_entity and manager.target_entity.entity_id:
            if manager.points and all(p.entity_id for p in manager.points.values()):
                return True
        await asyncio.sleep(0.1)
        elapsed += 0.1
    return False


def _build_card_yaml(entry: ConfigEntry, manager: "HeatingCurveManager") -> str:
    cfg = entry.data
    point_count = cfg[CONF_POINT_COUNT]
    grid_min = cfg[CONF_GRID_MIN]
    grid_max = cfg[CONF_GRID_MAX]
    step = (grid_max - grid_min) / (point_count - 1) if point_count > 1 else 0

    lines = [
        "type: custom:heating-curve-card",
        f"title: {entry.title}",
        'unit: "°C"',
        f"y_min: {cfg[CONF_Y_MIN]:g}",
        f"y_max: {cfg[CONF_Y_MAX]:g}",
        "service_domain: number",
        f"current_x_entity: {cfg[CONF_OUTSIDE_SENSOR]}",
    ]
    if manager.target_entity is not None and manager.target_entity.entity_id:
        lines.append(f"current_y_entity: {manager.target_entity.entity_id}")
    lines.append("points:")
    for i in range(point_count):
        x = round(grid_min + step * i, 1)
        point = manager.points.get(i)
        entity_id = point.entity_id if point and point.entity_id else "unknown.entity"
        lines.append(f"  - x: {x:g}")
        lines.append(f"    entity: {entity_id}")

    return "\n".join(lines)


async def _async_notify_dashboard_card(
    hass: HomeAssistant, entry: ConfigEntry, manager: "HeatingCurveManager"
) -> None:
    ready = await _wait_for_entity_ids(manager)
    if not ready:
        _LOGGER.warning(
            "Heating Curve (%s): entities did not finish registering in time; "
            "skipping the ready-made dashboard card notification. Check "
            "Developer Tools > States for the entity IDs manually.",
            entry.title,
        )
        return

    yaml_text = _build_card_yaml(entry, manager)
    message = (
        f"Your **{entry.title}** curve is set up. Add this card to your "
        f"dashboard: open a dashboard, **Edit Dashboard → Edit in YAML**, "
        f"and paste this into a section's `cards:` list:\n\n"
        f"```yaml\n{yaml_text}\n```"
    )
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": f"Heating Curve — {entry.title}: dashboard card ready",
            "message": message,
            "notification_id": f"heating_curve_card_{entry.entry_id}",
        },
    )


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

    hass.async_create_task(_async_notify_dashboard_card(hass, entry, manager))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, ["number", "sensor"]
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
