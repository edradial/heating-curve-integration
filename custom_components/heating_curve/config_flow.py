from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

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
    DEFAULT_GRID_MAX,
    DEFAULT_GRID_MIN,
    DEFAULT_MODBUS_UNIT,
    DEFAULT_POINT_COUNT,
    DEFAULT_Y_MAX,
    DEFAULT_Y_MIN,
    DOMAIN,
)


class HeatingCurveConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Heating Curve."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            unique_id = f"{user_input[CONF_MODBUS_HUB]}_{user_input[CONF_REGISTER]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input.get("name", "Heating Curve"),
                data=user_input,
            )

        schema = vol.Schema(
            {
                vol.Required("name", default="Heating Curve"): str,
                vol.Required(
                    CONF_POINT_COUNT, default=DEFAULT_POINT_COUNT
                ): vol.All(vol.Coerce(int), vol.Range(min=2, max=30)),
                vol.Required(
                    CONF_GRID_MIN, default=DEFAULT_GRID_MIN
                ): vol.Coerce(float),
                vol.Required(
                    CONF_GRID_MAX, default=DEFAULT_GRID_MAX
                ): vol.Coerce(float),
                vol.Required(CONF_Y_MIN, default=DEFAULT_Y_MIN): vol.Coerce(float),
                vol.Required(CONF_Y_MAX, default=DEFAULT_Y_MAX): vol.Coerce(float),
                vol.Required(CONF_OUTSIDE_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_MODBUS_HUB): str,
                vol.Required(CONF_REGISTER): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=65535)
                ),
                vol.Required(
                    CONF_MODBUS_UNIT, default=DEFAULT_MODBUS_UNIT
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=255)),
                vol.Optional(CONF_ONOFF_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
