"""The Enki integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.storage import Store

from .api import API
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
)
from .coordinator import EnkiCoordinator

PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.FAN,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.COVER,
    Platform.SELECT,
    Platform.ALARM_CONTROL_PANEL,
]


@dataclass
class RuntimeData:
    """Runtime data."""

    coordinators: dict[str, EnkiCoordinator]
    gateways: dict[str, dict]


EnkiConfigEntry = ConfigEntry[RuntimeData]


async def _create_gateways(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    devices: list[dict],
) -> dict[str, dict]:
    """Create Enki gateway devices."""

    device_registry = dr.async_get(hass)

    gateways: dict[str, dict] = {}

    for device in devices:
        if device.get("deviceType") != "gateways":
            continue

        gateway_id = device.get("nodeId")

        if not gateway_id:
            continue

        gateways[gateway_id] = device

        manufacturer = device.get(
            "manufacturerId",
            "Enki",
        )

        model = device.get("modelNumber")

        if not model:
            model = device.get("i18n")

            if model:
                model = model.replace(
                    "tr_device_",
                    ""
                )
                model = model.replace(
                    "_label",
                    ""
                )
                model = model.replace(
                    f"{manufacturer.lower()}_",
                    ""
                )
                model = model.replace(
                    "_",
                    " "
                )
                model = model.title()
            else:
                model = "Enki Gateway"

        device_registry.async_get_or_create(
            config_entry_id=config_entry.entry_id,
            identifiers={(DOMAIN, gateway_id)},
            manufacturer=manufacturer,
            name=device.get(
                "deviceName",
                "Enki Connect Box",
            ),
            model=model,
            sw_version=device.get("version"),
            serial_number=device.get(
                "serialNumber"
            ),
        )

        LOGGER.debug(
            "Created gateway device %s",
            gateway_id,
        )

    return gateways


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EnkiConfigEntry,
) -> bool:
    """Set up Enki from a config entry."""

    LOGGER.info(
        "Setting up Enki integration for %s",
        config_entry.title,
    )

    api = API(
        user=config_entry.data[CONF_USERNAME],
        pwd=config_entry.data[CONF_PASSWORD],
    )

    try:
        devices = await api.get_devices()
    except Exception as err:
        raise ConfigEntryNotReady(
            "Unable to fetch Enki devices"
        ) from err

    #
    # Create gateways
    #
    gateways = await _create_gateways(
        hass,
        config_entry,
        devices,
    )

    poll_interval = int(
        config_entry.data.get(
            CONF_SCAN_INTERVAL,
            DEFAULT_SCAN_INTERVAL,
        )
    )

    interval_store = Store(
        hass,
        1,
        f"{DOMAIN}_{config_entry.entry_id}_device_update_intervals",
    )

    stored_intervals = await interval_store.async_load()

    interval_overrides: dict[str, int] = {}

    if isinstance(stored_intervals, dict):
        for node_id, seconds in stored_intervals.items():
            try:
                interval_overrides[node_id] = max(
                    1,
                    int(seconds),
                )
            except (TypeError, ValueError):
                continue

    coordinators: dict[str, EnkiCoordinator] = {}

    for device in devices:
        node_id = device.get("nodeId")

        if not node_id:
            continue

        if node_id in coordinators:
            continue

        try:
            interval = interval_overrides.get(
                node_id,
                max(
                    1,
                    int(
                        device.get(
                            "update_interval",
                            poll_interval,
                        )
                    ),
                ),
            )
        except (TypeError, ValueError):
            interval = poll_interval

        LOGGER.debug(
            "Setting update interval for %s to %s seconds",
            node_id,
            interval,
        )

        device["update_interval"] = interval

        coordinator = EnkiCoordinator(
            hass,
            config_entry,
            api,
            device,
            interval,
            interval_overrides,
            interval_store,
        )

        coordinator.async_set_updated_data(
            [device]
        )

        config_entry.async_on_unload(
            coordinator.shutdown
        )

        coordinators[node_id] = coordinator

    config_entry.runtime_data = RuntimeData(
        coordinators=coordinators,
        gateways=gateways,
    )

    await hass.config_entries.async_forward_entry_setups(
        config_entry,
        PLATFORMS,
    )

    LOGGER.info(
        "Enki integration loaded successfully. "
        "%s coordinators created. "
        "%s gateways discovered.",
        len(coordinators),
        len(gateways),
    )

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Allow device deletion from HA."""

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    config_entry: EnkiConfigEntry,
) -> bool:
    """Unload Enki config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry,
        PLATFORMS,
    )

    return unload_ok