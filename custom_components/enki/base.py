"""Base entity which all other entity platform classes can inherit.

As all entity types have a common set of properties, you can
create a base entity like this and inherit it in all your entity platforms.

This just makes your code more efficient and is totally optional.

See each entity platform (ie sensor.py, switch.py) for how this is inheritted
and what additional properties and methods you need to add for each entity type.

"""

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EnkiCoordinator

# Home Assistant 2026.8 deprecates `via_device` (a (domain, identifier) tuple) in
# favor of `via_device_id` (the id of the parent device in the device registry).
# Older versions only know `via_device`.
SUPPORTS_VIA_DEVICE_ID = "via_device_id" in DeviceInfo.__annotations__


class EnkiBaseEntity(CoordinatorEntity):
    """Base Entity Class.

    This inherits a CoordinatorEntity class to register your entites to be updated
    by your DataUpdateCoordinator when async_update_data is called, either on the scheduled
    interval or by forcing an update.
    """

    coordinator: EnkiCoordinator

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: EnkiCoordinator, device: dict[str, Any]
    ) -> None:
        """Initialise entity."""
        super().__init__(coordinator)
        self.device = device
        self.node_id = device["nodeId"]
        self.device_id = device["deviceId"]
        self.parameter = self.coordinator.get_device_parameter("deviceName")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.device.get("isEnabled", False) and self.device.get("state", None) != "DEACTIVATED"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator."""
        # This method is called by your DataUpdateCoordinator when a successful update runs.
        self.device = self.coordinator.get_device()
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        device_name = self.coordinator.get_device_parameter("deviceName")
        model = self.coordinator.get_device_parameter("modelNumber")
        manufacturer = self.coordinator.get_device_parameter("manufacturerId")
        if not model:
            model = self.coordinator.get_device_parameter("i18n")
            if model:
                model = model.replace(f"{manufacturer.lower()}_", "")
                model = model.replace('tr_device_', '')
                model = model.replace('_label', '')
                model = model.replace("_", " ")
                model = model.title()
            else:
                model = 'Unknown'
        return DeviceInfo(
            name=device_name,
            manufacturer=manufacturer,
            model=model,
            model_id=str(self.coordinator.get_device_parameter("deviceId")),
            sw_version=self.coordinator.get_device_parameter(
                "version"
            ),
            identifiers={
                (
                    DOMAIN,
                    self.node_id,
                )
            },
            serial_number=self.coordinator.get_device_parameter("eui64"),
            **self._via_device_info(),
        )

    def _via_device_info(self) -> dict[str, Any]:
        """Return the DeviceInfo keys linking this device to its parent."""
        parent_id = self.coordinator.get_device_parameter("parentId")
        if not parent_id:
            return {}

        if not SUPPORTS_VIA_DEVICE_ID:
            return {"via_device": (DOMAIN, parent_id)}

        config_entry = self.coordinator.config_entry
        if self.hass is None or config_entry is None:
            return {}

        registry = dr.async_get(self.hass)
        identifier = (DOMAIN, parent_id)
        if hasattr(registry, "async_get_device_by_identifier"):
            parent = registry.async_get_device_by_identifier(
                identifier, config_entry.entry_id
            )
        else:
            parent = registry.async_get_device(identifiers={identifier})
        return {"via_device_id": parent.id} if parent else {}

    @property
    def name(self) -> str:
        """Return the name of the device."""
        return self.parameter.replace("_", " ").title()

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}-{self.coordinator.get_device_parameter("nodeId")}-{self.parameter}"
