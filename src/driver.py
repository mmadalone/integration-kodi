#!/usr/bin/env python3
"""
This module implements a Remote Two integration driver for Kodi receivers.

:copyright: (c) 2026 by Albaintor
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import logging
import os
import sys
from typing import Any

# sys.path.insert(0, os.path.abspath("../integration-python-library"))
import ucapi

import config
import kodi_device
import media_player
import remote
import selector
import sensor
import setup_flow
from config import KodiEntity
from const import filter_attributes
from kodi_device import _log_task_exception

_LOG = logging.getLogger("driver")  # avoid having __main__ in log messages
if sys.platform == "win32":
    _LOOP = asyncio.SelectorEventLoop()
else:
    _LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)

# Global variables
api = ucapi.IntegrationAPI(_LOOP)
# Map of id -> device instance
_configured_kodis: dict[str, kodi_device.KodiDevice] = {}
_remote_in_standby = False  # pylint: disable=C0103


@api.listens_to(ucapi.Events.CONNECT)
async def on_connect_cmd() -> None:
    """Connect all configured TVs when the Remote sends the connect command."""
    await api.set_device_state(ucapi.DeviceStates.CONNECTED)
    # TODO check if we were in standby and ignore the call? We'll also get an EXIT_STANDBY
    _LOG.debug("Connect command: connecting device(s)")
    for device in _configured_kodis.values():
        # start background task
        # TODO ? what is the connect event for (against exit from standby)
        # await _LOOP.create_task(device.power_on())
        try:
            await _LOOP.create_task(device.connect())
        except RuntimeError as ex:
            _LOG.debug("Could not connect to device %s : %s", device.device_config.address, ex)


@api.listens_to(ucapi.Events.DISCONNECT)
async def on_disconnect_cmd():
    """Disconnect all configured TVs when the Remote Two sends the disconnect command."""
    # pylint: disable = W0212
    if len(api._clients) == 0:
        _LOG.debug("Disconnect requested")
        for device in _configured_kodis.values():
            # start background task
            await _LOOP.create_task(device.disconnect())
    else:
        _LOG.debug("Disconnect requested but 1 client is connected %s", api._clients)


@api.listens_to(ucapi.Events.ENTER_STANDBY)
async def on_enter_standby() -> None:
    """Enter standby notification from Remote Two.

    Disconnect every Kodi instances.
    """
    global _remote_in_standby

    _remote_in_standby = True
    _LOG.debug("Enter standby event: disconnecting device(s)")
    for configured in _configured_kodis.values():
        await configured.disconnect()


async def connect_device(device: kodi_device.KodiDevice):
    """Connect device and send state."""
    try:
        _LOG.debug("Connecting device %s...", device.id)
        await device.connect()
        _LOG.debug("Device %s connected, sending attributes for subscribed entities", device.id)
        await on_device_update(device.id, None)

    except RuntimeError as ex:
        _LOG.error("Error while reconnecting to Kodi %s", ex)


@api.listens_to(ucapi.Events.EXIT_STANDBY)
async def on_exit_standby() -> None:
    """
    Exit standby notification from Remote Two.

    Connect all Kodi instances.
    """
    global _remote_in_standby

    _remote_in_standby = False
    _LOG.debug("Exit standby event: connecting Kodi device(s) %s", _configured_kodis)

    for configured in _configured_kodis.values():
        # start background task
        try:
            await _LOOP.create_task(connect_device(configured))
        except RuntimeError as ex:
            _LOG.error("Error while reconnecting to Kodi %s", ex)
        # _LOOP.create_task(configured.connect())


async def _post_subscribe_refresh(device_id: str, entity_id: str, timeout: float = 30.0) -> None:
    """Patch 41: handle the subscribe-during-initial-connect race.

    `on_subscribe_entities` pushes `device.attributes` synchronously when the
    activity card opens. If the integration is mid-initial-connect (e.g. just
    after a reinstall), `_media_image_data` / `_media_image_url` are still
    empty — so the synchronous push ships `MEDIA_IMAGE_URL=""` and the remote
    blanks the artwork.

    The first `_update_states()` to complete will emit Events.UPDATE → driver
    `on_device_update` will propagate via `api.configured_entities.update_attributes`,
    which is the canonical fix path. This helper is belt-and-braces for the
    timing-sensitive corner case where the late propagation doesn't actually
    stick on the new subscriber. We register a one-shot listener for the next
    Events.UPDATE from the device, then re-push the full attribute snapshot to
    the just-subscribed entity. Bounded by `timeout` so a permanently-idle
    integration doesn't leak the listener.
    """
    _LOG.debug("[patch41] _post_subscribe_refresh entered: device=%s entity=%s", device_id, entity_id)
    if device_id not in _configured_kodis:
        _LOG.debug("[patch41] device %s not in _configured_kodis — bail", device_id)
        return
    device = _configured_kodis[device_id]

    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()

    def _on_next_update(*_args: Any, **_kwargs: Any) -> None:  # noqa: ANN001
        if not fut.done():
            fut.set_result(None)

    device.events.once(kodi_device.Events.UPDATE, _on_next_update)
    _LOG.debug("[patch41] one-shot Events.UPDATE listener registered, waiting up to %.1fs", timeout)

    try:
        await asyncio.wait_for(fut, timeout=timeout)
        _LOG.debug("[patch41] Events.UPDATE arrived, proceeding to re-push attributes")
    except asyncio.TimeoutError:
        # No emission within the window — integration is idle (no playback) or
        # stuck. Either way, nothing to re-push. The pyee `once` listener is
        # already removed at this point because it self-removes on first fire;
        # if it didn't fire, it stays registered. Remove it manually.
        _LOG.debug("[patch41] timed out waiting for Events.UPDATE; abandoning")
        try:
            device.events.remove_listener(kodi_device.Events.UPDATE, _on_next_update)
        except (KeyError, ValueError):
            pass
        return

    # Re-push the current snapshot. on_device_update handled the partial-delta
    # emit already, but the new subscriber's view of the entity may have been
    # cached from the synchronous (empty) push in on_subscribe_entities. This
    # second push overwrites that.
    configured_entity = api.configured_entities.get(entity_id)
    if configured_entity is None:
        _LOG.debug("[patch41] configured_entity not found for %s — bail", entity_id)
        return
    if isinstance(configured_entity, media_player.KodiMediaPlayer):
        attrs = filter_attributes(device.attributes, ucapi.media_player.Attributes)
        # Mask the data URI body so logs stay readable; just show MIME prefix + length.
        mip = attrs.get(ucapi.media_player.Attributes.MEDIA_IMAGE_URL.value, "")
        if isinstance(mip, str) and mip.startswith("data:"):
            semi = mip.find(";")
            mime_part = mip[5:semi] if semi > 0 else "?"
            mip_disp = f"<data URI mime={mime_part!r} len={len(mip)}>"
        elif isinstance(mip, str) and mip:
            mip_disp = f"<URL len={len(mip)}>"
        else:
            mip_disp = "<EMPTY>"
        _LOG.debug(
            "[patch41] re-pushing media_player attributes for %s; media_image_url=%s; total_keys=%d",
            entity_id,
            mip_disp,
            len(attrs),
        )
        api.configured_entities.update_attributes(entity_id, attrs)
    else:
        _LOG.debug("[patch41] entity %s is not a KodiMediaPlayer — skipping re-push", entity_id)


@api.listens_to(ucapi.Events.SUBSCRIBE_ENTITIES)
async def on_subscribe_entities(entity_ids: list[str]) -> None:
    """
    Subscribe to given entities.

    :param entity_ids: entity identifiers.
    """
    global _remote_in_standby

    _remote_in_standby = False
    _LOG.debug("Subscribe entities event: %s", entity_ids)

    for entity_id in entity_ids:
        entity: KodiEntity | None = api.configured_entities.get(entity_id)
        device_id = entity.deviceid
        if device_id in _configured_kodis:
            device = _configured_kodis[device_id]
            state = device.get_state()
            if isinstance(entity, media_player.KodiMediaPlayer):
                api.configured_entities.update_attributes(
                    entity_id, filter_attributes(device.attributes, ucapi.media_player.Attributes)
                )
                # Patch 41: schedule a follow-up refresh that waits for the
                # next state-update emission and re-pushes the snapshot. Closes
                # the subscribe-during-initial-connect race that produced
                # blank artwork on first activity-card open after reinstall.
                asyncio.create_task(_post_subscribe_refresh(device_id, entity_id)).add_done_callback(
                    _log_task_exception
                )
            elif isinstance(entity, remote.KodiRemote):
                api.configured_entities.update_attributes(
                    entity_id, {ucapi.remote.Attributes.STATE: remote.KODI_REMOTE_STATE_MAPPING.get(state)}
                )
            elif isinstance(entity, sensor.KodiSensor):
                api.configured_entities.update_attributes(entity_id, entity.update_attributes())
            elif isinstance(entity, selector.KodiSelect):
                api.configured_entities.update_attributes(entity_id, entity.update_attributes())
            continue

        device = config.devices.get(device_id)
        if device:
            _configure_new_device(device, connect=True)
            _LOOP.create_task(_configured_kodis.get(device_id).connect())
        else:
            _LOG.error("Failed to subscribe entity %s: no Kodi configuration found", entity_id)


@api.listens_to(ucapi.Events.UNSUBSCRIBE_ENTITIES)
async def on_unsubscribe_entities(entity_ids: list[str]) -> None:
    """On unsubscribe, we disconnect the objects and remove listeners for events."""
    _LOG.debug("Unsubscribe entities event: %s", entity_ids)
    devices_to_remove = set()
    for entity_id in entity_ids:
        entity: KodiEntity | None = api.configured_entities.get(entity_id)
        device_id = entity.deviceid
        if device_id is None:
            continue
        devices_to_remove.add(device_id)

    # Keep devices that are used by other configured entities not in this list
    for entity_entry in api.configured_entities.get_all():
        entity_id = entity_entry.get("entity_id", "")
        if entity_id in entity_ids:
            continue
        entity: KodiEntity | None = api.configured_entities.get(entity_id)
        device_id = entity.deviceid
        if device_id is None:
            continue
        if device_id in devices_to_remove:
            devices_to_remove.remove(device_id)

    for device_id in devices_to_remove:
        if device_id in _configured_kodis:
            await _configured_kodis[device_id].disconnect()
            _configured_kodis[device_id].events.remove_all_listeners()


async def on_device_connected(device_id: str):
    """Handle device connection."""
    _LOG.debug("Kodi connected: %s", device_id)

    if device_id not in _configured_kodis:
        _LOG.warning("Kodi %s is not configured", device_id)
        return

    await api.set_device_state(ucapi.DeviceStates.CONNECTED)
    await on_device_update(device_id, None)


async def on_device_disconnected(device_id: str):
    """Handle device disconnection."""
    _LOG.debug("Kodi disconnected: %s", device_id)

    for configured_entity in _get_entities(device_id):
        if configured_entity.entity_type == ucapi.EntityTypes.MEDIA_PLAYER:
            api.configured_entities.update_attributes(
                configured_entity.id, {ucapi.media_player.Attributes.STATE: ucapi.media_player.States.UNAVAILABLE}
            )
        elif configured_entity.entity_type == ucapi.EntityTypes.REMOTE:
            api.configured_entities.update_attributes(
                configured_entity.id, {ucapi.remote.Attributes.STATE: ucapi.remote.States.UNAVAILABLE}
            )
        elif configured_entity.entity_type == ucapi.EntityTypes.SENSOR:
            api.configured_entities.update_attributes(
                configured_entity.id, {ucapi.sensor.Attributes.STATE: ucapi.sensor.States.UNAVAILABLE}
            )

    # TODO #20 when multiple devices are supported, the device state logic isn't that simple anymore!
    await api.set_device_state(ucapi.DeviceStates.DISCONNECTED)


async def on_device_connection_error(device_id: str, message):
    """Set entities of Kodi to state UNAVAILABLE if device connection error occurred."""
    _LOG.error(message)

    for configured_entity in _get_entities(device_id):
        if configured_entity.entity_type == ucapi.EntityTypes.MEDIA_PLAYER:
            api.configured_entities.update_attributes(
                configured_entity.id, {ucapi.media_player.Attributes.STATE: ucapi.media_player.States.UNAVAILABLE}
            )
        elif configured_entity.entity_type == ucapi.EntityTypes.REMOTE:
            api.configured_entities.update_attributes(
                configured_entity.id, {ucapi.remote.Attributes.STATE: ucapi.remote.States.UNAVAILABLE}
            )
        elif configured_entity.entity_type == ucapi.EntityTypes.SENSOR:
            api.configured_entities.update_attributes(
                configured_entity.id, {ucapi.sensor.Attributes.STATE: ucapi.sensor.States.UNAVAILABLE}
            )

    # TODO #20 when multiple devices are supported, the device state logic isn't that simple anymore!
    await api.set_device_state(ucapi.DeviceStates.ERROR)


async def handle_device_address_change(device_id: str, address: str) -> None:
    """Update device configuration with changed IP address."""
    # TODO discover
    device = config.devices.get(device_id)
    if device and device.address != address:
        _LOG.info("Updating IP address of configured Kodi %s: %s -> %s", device_id, device.address, address)
        device.address = address
        config.devices.update(device)


async def on_device_update(device_id: str, update: dict[str, Any] | None) -> list[str]:
    """Update attributes of configured media-player entity if device properties changed.

    :param device_id: device identifier
    :param update: dictionary containing the updated properties or None if
    :return list[str]: list of unconfigured devices against entities
    """
    if update is None:
        if device_id not in _configured_kodis:
            return []
        device = _configured_kodis[device_id]
        update = device.attributes
    else:
        _LOG.info("[%s] Kodi update: %s", device_id, update)

    attributes = None
    unconfigured_devices: list[str] = []

    for configured_entity in _get_entities(device_id):
        if isinstance(configured_entity, media_player.KodiMediaPlayer):
            attributes = filter_attributes(update, ucapi.media_player.Attributes)
        elif isinstance(configured_entity, remote.KodiRemote):
            attributes = configured_entity.filter_changed_attributes(update)
        elif isinstance(configured_entity, sensor.KodiSensor):
            attributes = configured_entity.update_attributes(update)
        elif isinstance(configured_entity, selector.KodiSelect):
            attributes = configured_entity.update_attributes(update)

        if attributes:
            api.configured_entities.update_attributes(configured_entity.id, attributes)

        if configured_entity.device_id not in _configured_kodis:
            unconfigured_devices.append(configured_entity.device_id)
    return unconfigured_devices


def _get_entities(device_id: str, include_all=False) -> list[KodiEntity]:
    """
    Return all associated entities of the given device.

    :param device_id: the device  identifier
    :param include_all: include both configured and available entities
    :return: list of entities
    """
    entities = []
    for entity_entry in api.configured_entities.get_all():
        entity: KodiEntity | None = api.configured_entities.get(entity_entry.get("entity_id", ""))
        if entity is None or entity.deviceid != device_id:
            continue
        entities.append(entity)
    if not include_all:
        return entities
    for entity_entry in api.available_entities.get_all():
        entity: KodiEntity | None = api.available_entities.get(entity_entry.get("entity_id", ""))
        if entity is None or entity.deviceid != device_id:
            continue
        entities.append(entity)
    return entities


def _configure_new_device(device_config: config.KodiConfigDevice, connect: bool = True) -> None:
    """
    Create and configure a new device.

    Supported entities of the device are created and registered in the integration library as available entities.

    :param device_config: the receiver configuration.
    :param connect: True: start connection to receiver.
    """
    # the device should not yet be configured, but better be safe
    if device_config.id in _configured_kodis:
        device = _configured_kodis[device_config.id]
        asyncio.create_task(device.disconnect()).add_done_callback(_log_task_exception)
    else:
        device = kodi_device.KodiDevice(device_config, loop=_LOOP)

        asyncio.create_task(on_device_connected(device.id)).add_done_callback(_log_task_exception)
        # asyncio.rundevice.events.on(lg.Events.CONNECTED, on_device_connected)
        # device.events.on(lg.Events.DISCONNECTED, on_device_disconnected)
        device.events.on(kodi_device.Events.ERROR, on_device_connection_error)
        device.events.on(kodi_device.Events.UPDATE, on_device_update)
        # TODO event change address
        # receiver.events.on(lg.Events.IP_ADDRESS_CHANGED, handle_lg_address_change)
        # receiver.connect()
        _configured_kodis[device.id] = device

    _register_available_entities(device_config, device)

    if connect:
        # start background connection task
        try:
            _LOOP.create_task(device.connect()).add_done_callback(_log_task_exception)
        except RuntimeError as ex:
            _LOG.debug("Could not connect to device, probably because it is starting with magic packet %s", ex)


def _register_available_entities(device_config: config.KodiConfigDevice, device: kodi_device.KodiDevice) -> None:
    """
    Create entities for given device and register them as available entities.

    :param device_config: Receiver
    """
    # plain and simple for now: only one media_player per device
    # entity = media_player.create_entity(device)
    entities: list[KodiEntity] = [
        media_player.KodiMediaPlayer(device_config, device),
        remote.KodiRemote(device_config, device),
        selector.KodiAudioStreamSelect(device_config, device),
        selector.KodiSubtitleStreamSelect(device_config, device),
        selector.KodiChapterSelect(device_config, device),
        sensor.KodiAudioStream(device_config, device),
        sensor.KodiSubtitleStream(device_config, device),
        sensor.KodiChapter(device_config, device),
        sensor.KodiVideoInfo(device_config, device),
        sensor.KodiAudioInfo(device_config, device),
        sensor.KodiSensorVolume(device_config, device),
        sensor.KodiSensorMuted(device_config, device),
    ]

    for entity in entities:
        if api.available_entities.contains(entity.id):
            api.available_entities.remove(entity.id)
        api.available_entities.add(entity)


def on_device_added(device: config.KodiConfigDevice) -> None:
    """Handle a newly added device in the configuration."""
    _LOG.debug("New device added: %s", device)

    async def _add_device(device: config.KodiConfigDevice) -> None:
        _configure_new_device(device, connect=False)
        await on_device_connected(device.id)

    asyncio.create_task(_add_device(device)).add_done_callback(_log_task_exception)


def on_device_updated(device: config.KodiConfigDevice) -> None:
    """Handle an updated device in the configuration."""
    _LOG.debug("Device config updated: %s, reconnect with new configuration", device)
    _configure_new_device(device, connect=True)


def on_device_removed(device: config.KodiConfigDevice | None) -> None:
    """Handle a removed device in the configuration."""
    if device is None:
        _LOG.debug("Configuration cleared, disconnecting & removing all configured Kodi instances")
        for configured in _configured_kodis.values():
            _LOOP.create_task(_async_remove(configured)).add_done_callback(_log_task_exception)
        _configured_kodis.clear()
        api.configured_entities.clear()
        api.available_entities.clear()
    else:
        if device.id in _configured_kodis:
            _LOG.debug("Disconnecting from removed Kodi %s", device.id)
            configured = _configured_kodis.pop(device.id)
            _LOOP.create_task(_async_remove(configured)).add_done_callback(_log_task_exception)
            for entity in _get_entities(configured.id):
                api.configured_entities.remove(entity.id)
                api.available_entities.remove(entity.id)


async def _async_remove(device: kodi_device.KodiDevice) -> None:
    """Disconnect from receiver and remove all listeners."""
    await device.disconnect()
    device.events.remove_all_listeners()


async def main():
    """Start the Remote Two integration driver."""
    logging.basicConfig()

    level = os.getenv("UC_LOG_LEVEL", "DEBUG").upper()
    logging.getLogger("discover").setLevel(level)
    logging.getLogger("driver").setLevel(level)
    logging.getLogger("media_player").setLevel(level)
    logging.getLogger("remote").setLevel(level)
    logging.getLogger("sensor").setLevel(level)
    logging.getLogger("selector").setLevel(level)
    logging.getLogger("kodi_device").setLevel(level)
    logging.getLogger("setup_flow").setLevel(level)
    logging.getLogger("config").setLevel(level)
    logging.getLogger("media_browser").setLevel(level)
    logging.getLogger("pykodi.kodi").setLevel(level)

    # Load driver config
    config.devices = config.Devices(api.config_dir_path, on_device_added, on_device_removed, on_device_updated)
    for device_config in config.devices.all():
        _configure_new_device(device_config, connect=False)
    setup = setup_flow.SetupFlow()
    await api.init("driver.json", setup.driver_setup_handler)


if __name__ == "__main__":
    _LOOP.run_until_complete(main())
    _LOOP.run_forever()
