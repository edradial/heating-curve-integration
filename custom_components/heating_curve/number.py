from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_GRID_MAX,
    CONF_GRID_MIN,
    CONF_POINT_COUNT,
    CONF_Y_MAX,
    CONF_Y_MIN,
    DOMAIN,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    cfg = entry.data

    point_count = cfg[CONF_POINT_COUNT]
    grid_min = cfg[CONF_GRID_MIN]
    grid_max = cfg[CONF_GRID_MAX]
    y_min = cfg[CONF_Y_MIN]
    y_max = cfg[CONF_Y_MAX]
    step = (grid_max - grid_min) / (point_count - 1) if point_count > 1 else 0

    entities = []
    for i in range(point_count):
        x = round(grid_min + step * i, 1)
        # sensible fallback default (only used the very first time, before
        # any value has ever been saved for this point): linear from y_max
        # at the coldest point to y_min at the warmest point
        computed_default = (
            round(y_max - (y_max - y_min) * (i / (point_count - 1)), 1)
            if point_count > 1
            else y_max
        )
        stored = manager.stored_values.get(str(i))
        initial_val = stored if stored is not None else computed_default

        ent = HeatingCurvePoint(entry, manager, i, x, y_min, y_max, initial_val)
        manager.register_point(i, ent)
        entities.append(ent)

    async_add_entities(entities)


class HeatingCurvePoint(NumberEntity):
    """A single draggable point on the weather compensation curve.

    Persistence is handled explicitly by HeatingCurveManager (via a
    dedicated Store, saved immediately on every change) rather than via
    Home Assistant's generic RestoreEntity mechanism, which only dumps
    state periodically / on clean shutdown and can lose a very recent
    change if Home Assistant is restarted shortly after a drag.
    """

    _attr_has_entity_name = True
    _attr_native_step = 1

    def __init__(self, entry, manager, index, x, y_min, y_max, initial_val):
        self._entry = entry
        self._manager = manager
        self._index = index
        self._attr_unique_id = f"{entry.entry_id}_point_{index}"
        self._attr_name = f"Point @ {x:g}°C"
        self._attr_native_min_value = y_min
        self._attr_native_max_value = y_max
        self._attr_native_unit_of_measurement = "°C"
        self._attr_native_value = initial_val

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Heating Curve",
        )

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
        await self._manager.async_save_point(self._index, value)
        await self._manager.async_recompute_and_apply()
