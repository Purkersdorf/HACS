"""Setup HACS."""
from aiogithubapi import AIOGitHubAPIException, GitHub, GitHubAPI
from aiogithubapi.const import ACCEPT_HEADERS
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.const import __version__ as HAVERSION
from homeassistant.core import CoreState
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.loader import async_get_integration

from custom_components.hacs.const import DOMAIN, STARTUP
from custom_components.hacs.enums import (
    ConfigurationType,
    HacsDisabledReason,
    HacsStage,
    LovelaceMode,
)
from custom_components.hacs.hacsbase.data import HacsData
from custom_components.hacs.helpers.functions.constrains import check_constrains
from custom_components.hacs.helpers.functions.remaining_github_calls import (
    get_fetch_updates_for,
)
from custom_components.hacs.operational.reload import async_reload_entry
from custom_components.hacs.operational.remove import async_remove_entry


from custom_components.hacs.operational.setup_actions.websocket_api import (
    async_setup_hacs_websockt_api,
)
from custom_components.hacs.share import get_hacs
from custom_components.hacs.tasks.manager import HacsTaskManager

try:
    from homeassistant.components.lovelace import system_health_info
except ImportError:
    from homeassistant.components.lovelace.system_health import system_health_info


async def _async_common_setup(hass):
    """Common setup stages."""
    integration = await async_get_integration(hass, DOMAIN)
    hacs = get_hacs()
    hacs.enable_hacs()
    await hacs.async_set_stage(None)
    hacs.log.info(STARTUP.format(version=integration.version))

    hacs.integration = integration
    hacs.version = integration.version
    hacs.hass = hass
    hacs.data = HacsData()
    hacs.system.running = True
    hacs.session = async_create_clientsession(hass)
    hacs.tasks = HacsTaskManager()

    try:
        lovelace_info = await system_health_info(hacs.hass)
    except (TypeError, KeyError, HomeAssistantError):
        # If this happens, the users YAML is not valid, we assume YAML mode
        lovelace_info = {"mode": "yaml"}
    hacs.log.debug(f"Configuration type: {hacs.configuration.config_type}")
    hacs.core.config_path = hacs.hass.config.path()
    hacs.core.ha_version = HAVERSION

    hacs.core.lovelace_mode = lovelace_info.get("mode", "yaml")
    hacs.core.lovelace_mode = LovelaceMode(lovelace_info.get("mode", "yaml"))

    await hacs.tasks.async_load()
    hass.data[DOMAIN] = hacs


async def async_setup_entry(hass, config_entry):
    """Set up this integration using UI."""
    hacs = get_hacs()

    if config_entry.source == SOURCE_IMPORT:
        hass.async_create_task(hass.config_entries.async_remove(config_entry.entry_id))
        return False
    if hass.data.get(DOMAIN) is not None:
        return False

    hacs.configuration.update_from_dict(
        {
            "config_entry": config_entry,
            "config_type": ConfigurationType.CONFIG_ENTRY,
            **config_entry.data,
            **config_entry.options,
        }
    )

    await _async_common_setup(hass)
    return await async_startup_wrapper_for_config_entry()


async def async_setup(hass, config):
    """Set up this integration using yaml."""
    hacs = get_hacs()
    if DOMAIN not in config:
        return True
    if hacs.configuration.config_type == ConfigurationType.CONFIG_ENTRY:
        return True

    hacs.configuration.update_from_dict(
        {
            "config_type": ConfigurationType.YAML,
            **config[DOMAIN],
            "config": config[DOMAIN],
        }
    )

    await _async_common_setup(hass)
    await async_startup_wrapper_for_yaml()
    return True


async def async_startup_wrapper_for_config_entry():
    """Startup wrapper for ui config."""
    hacs = get_hacs()
    hacs.configuration.config_entry.add_update_listener(async_reload_entry)
    try:
        startup_result = await async_hacs_setup()
    except AIOGitHubAPIException:
        startup_result = False
    if not startup_result:
        hacs.system.disabled = True
        raise ConfigEntryNotReady
    hacs.enable_hacs()
    return startup_result


async def async_startup_wrapper_for_yaml(_=None):
    """Startup wrapper for yaml config."""
    hacs = get_hacs()
    try:
        startup_result = await async_hacs_setup()
    except AIOGitHubAPIException:
        startup_result = False
    if not startup_result:
        hacs.system.disabled = True
        hacs.log.info("Could not setup HACS, trying again in 15 min")
        async_call_later(hacs.hass, 900, async_startup_wrapper_for_yaml)
        return
    hacs.enable_hacs()


async def async_hacs_setup():
    """HACS startup tasks."""
    hacs = get_hacs()
    await hacs.async_set_stage(HacsStage.SETUP)

    if hacs.system.disabled:
        return False

    # Setup websocket API
    await async_setup_hacs_websockt_api()

    # Setup GitHub API clients
    session = async_create_clientsession(hacs.hass)

    ## Legacy client
    hacs.github = GitHub(
        hacs.configuration.token,
        session,
        headers={
            "User-Agent": f"HACS/{hacs.version}",
            "Accept": ACCEPT_HEADERS["preview"],
        },
    )

    ## New GitHub client
    hacs.githubapi = GitHubAPI(
        token=hacs.configuration.token,
        session=session,
        **{"client_name": f"HACS/{hacs.version}"},
    )

    can_update = await get_fetch_updates_for(hacs.githubapi)
    if can_update is None:
        hacs.log.critical("Your GitHub token is not valid")
        hacs.disable_hacs(HacsDisabledReason.INVALID_TOKEN)
        return False

    if can_update != 0:
        hacs.log.debug(f"Can update {can_update} repositories")
    else:
        hacs.log.error(
            "Your GitHub account has been ratelimited, HACS will resume when the limit is cleared"
        )
        hacs.disable_hacs(HacsDisabledReason.RATE_LIMIT)
        return False

    # Check HACS Constrains
    if not await hacs.hass.async_add_executor_job(check_constrains):
        if hacs.configuration.config_type == ConfigurationType.CONFIG_ENTRY:
            if hacs.configuration.config_entry is not None:
                await async_remove_entry(hacs.hass, hacs.configuration.config_entry)
        hacs.disable_hacs(HacsDisabledReason.CONSTRAINS)
        return False

    # Restore from storefiles
    if not await hacs.data.restore():
        hacs_repo = hacs.get_by_name("hacs/integration")
        hacs_repo.pending_restart = True
        if hacs.configuration.config_type == ConfigurationType.CONFIG_ENTRY:
            if hacs.configuration.config_entry is not None:
                await async_remove_entry(hacs.hass, hacs.configuration.config_entry)
        hacs.disable_hacs(HacsDisabledReason.RESTORE)
        return False

    # Setup startup tasks
    if hacs.hass.state == CoreState.running:
        async_call_later(hacs.hass, 5, hacs.startup_tasks)
    else:
        hacs.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, hacs.startup_tasks)

    # Mischief managed!
    await hacs.async_set_stage(HacsStage.WAITING)
    hacs.log.info(
        "Setup complete, waiting for Home Assistant before startup tasks starts"
    )

    return not hacs.system.disabled
