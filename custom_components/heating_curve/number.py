from __future__ import annotations

from homeassistant.components.number import RestoreNumber
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
        # sensible default: linear from y_max at the coldest point to y_min
        # at the warmest point — the user drags it into shape afterwards
        default_val = (
            round(y_max - (y_max - y_min) * (i / (point_count - 1)), 1)
            if point_count > 1
            else y_max
        )
        ent = HeatingCurvePoint(entry, manager, i, x, y_min, y_max, default_val)
        manager.register_point(i, ent)
        entities.append(ent)

    async_add_entities(entities)


class HeatingCurvePoint(RestoreNumber):
    """A single draggable point on the weather compensation curve."""

    _attr_has_entity_name = True
    _attr_native_step = 1

    def __init__(self, entry, manager, index, x, y_min, y_max, default_val):
        self._entry = entry
        self._manager = manager
        self._index = index
        self._attr_unique_id = f"{entry.entry_id}_point_{index}"
        self._attr_name = f"Point @ {x:g}°C"
        self._attr_native_min_value = y_min
        self._attr_native_max_value = y_max
        self._attr_native_unit_of_measurement = "°C"
        self._attr_native_value = default_val

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Heating Curve",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = last.native_value

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
        await self._manager.async_recompute_and_apply()
