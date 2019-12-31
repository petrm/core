"""Support for WebOS TV."""
import asyncio
import logging

from aiopylgtv import PyLGTVCmdException, PyLGTVPairException, WebOsClient
import voluptuous as vol
from websockets.exceptions import ConnectionClosed

from homeassistant.const import (
    CONF_CUSTOMIZE,
    CONF_HOST,
    CONF_ICON,
    CONF_NAME,
    EVENT_HOMEASSISTANT_STOP,
)
import homeassistant.helpers.config_validation as cv

DOMAIN = "webostv"

CONF_SOURCES = "sources"
CONF_ON_ACTION = "turn_on_action"
CONF_STANDBY_CONNECTION = "standby_connection"
DEFAULT_NAME = "LG webOS Smart TV"
WEBOSTV_CONFIG_FILE = "webostv.conf"

CUSTOMIZE_SCHEMA = vol.Schema(
    {vol.Optional(CONF_SOURCES, default=[]): vol.All(cv.ensure_list, [cv.string])}
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Optional(CONF_CUSTOMIZE, default={}): CUSTOMIZE_SCHEMA,
                        vol.Required(CONF_HOST): cv.string,
                        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
                        vol.Optional(CONF_ON_ACTION): cv.SCRIPT_SCHEMA,
                        vol.Optional(
                            CONF_STANDBY_CONNECTION, default=False
                        ): cv.boolean,
                        vol.Optional(CONF_ICON): cv.string,
                    }
                )
            ],
        )
    },
    extra=vol.ALLOW_EXTRA,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass, config):
    """Set up the LG WebOS TV platform."""
    hass.data[DOMAIN] = {}

    tasks = [async_setup_tv(hass, config, conf) for conf in config[DOMAIN]]
    if tasks:
        await asyncio.gather(*tasks)

    return True


async def async_setup_tv(hass, config, conf):
    """Set up a LG WebOS TV based on host parameter."""

    host = conf[CONF_HOST]
    config_file = hass.config.path(WEBOSTV_CONFIG_FILE)
    standby_connection = conf[CONF_STANDBY_CONNECTION]

    client = WebOsClient(host, config_file, standby_connection=standby_connection)
    hass.data[DOMAIN][host] = {"client": client}

    if client.is_registered():
        await async_setup_tv_finalize(hass, config, conf, client)
    else:
        _LOGGER.warning("LG webOS TV %s needs to be paired", host)
        await async_request_configuration(hass, config, conf, client)


async def async_connect(client):
    """Attempt a connection, but fail gracefully if tv is off for example."""
    try:
        await client.connect()
    except (
        OSError,
        ConnectionClosed,
        ConnectionRefusedError,
        asyncio.TimeoutError,
        asyncio.CancelledError,
        PyLGTVPairException,
        PyLGTVCmdException,
    ):
        pass


async def async_setup_tv_finalize(hass, config, conf, client):
    """Make initial connection attempt and call platform setup."""

    async def async_on_stop(event):
        """Unregister callbacks and disconnect."""
        client.clear_state_update_callbacks()
        await client.disconnect()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_on_stop)

    await async_connect(client)
    hass.async_create_task(
        hass.helpers.discovery.async_load_platform("media_player", DOMAIN, conf, config)
    )
    hass.async_create_task(
        hass.helpers.discovery.async_load_platform("notify", DOMAIN, conf, config)
    )


async def async_request_configuration(hass, config, conf, client):
    """Request configuration steps from the user."""
    host = conf.get(CONF_HOST)
    name = conf.get(CONF_NAME)
    configurator = hass.components.configurator

    async def lgtv_configuration_callback(data):
        """Handle actions when configuration callback is called."""
        try:
            await client.connect()
        except PyLGTVPairException:
            _LOGGER.warning("Connected to LG webOS TV %s but not paired", host)
            return
        except (
            OSError,
            ConnectionClosed,
            ConnectionRefusedError,
            asyncio.TimeoutError,
            asyncio.CancelledError,
            PyLGTVCmdException,
        ):
            _LOGGER.error("Unable to connect to host %s", host)
            return

        await async_setup_tv_finalize(hass, config, conf, client)
        configurator.async_request_done(request_id)

    request_id = configurator.async_request_config(
        name,
        lgtv_configuration_callback,
        description="Click start and accept the pairing request on your TV.",
        description_image="/static/images/config_webos.png",
        submit_caption="Start pairing request",
    )
