"""Set up some common test helper things."""
# pytest: disable=protected-access
from . import patch_time  # noqa: F401, isort:skip
import asyncio
from collections import OrderedDict
from dataclasses import asdict
from glob import iglob
import json
import logging
import os
import shutil
from typing import Any, Generator
from unittest.mock import MagicMock, patch

from _pytest.assertion.util import _compare_eq_iterable
from awesomeversion import AwesomeVersion
import freezegun
from homeassistant import loader
from homeassistant.auth.models import Credentials
from homeassistant.auth.providers.homeassistant import HassAuthProvider
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.runner import HassEventLoopPolicy
from homeassistant.setup import async_setup_component
import pytest
import pytest_asyncio
from pytest_snapshot.plugin import Snapshot

from custom_components.hacs.base import HacsBase
from custom_components.hacs.const import DOMAIN
from custom_components.hacs.repositories import (
    HacsAppdaemonRepository,
    HacsIntegrationRepository,
    HacsNetdaemonRepository,
    HacsPluginRepository,
    HacsPythonScriptRepository,
    HacsTemplateRepository,
    HacsThemeRepository,
)
from custom_components.hacs.utils.store import async_load_from_store

from tests import _async_suggest_report_issue_mock_call_tracker
from tests.common import (
    IGNORED_BASE_FILES,
    REQUEST_CONTEXT,
    MockOwner,
    ProxyClientSession,
    ResponseMocker,
    WSClient,
    async_test_home_assistant_dev,
    async_test_home_assistant_min_version,
    client_session_proxy,
    create_config_entry,
    dummy_repository_base,
    get_hacs,
    mock_storage as mock_storage,
    recursive_remove_key,
    safe_json_dumps,
    setup_integration as common_setup_integration,
)

# Set default logger
logging.basicConfig(level=logging.INFO)
if "GITHUB_ACTION" in os.environ:
    logging.basicConfig(
        format="::%(levelname)s:: %(message)s",
        level=logging.DEBUG,
    )

# All test coroutines will be treated as marked.
# pytestmark = pytest.mark.asyncio

asyncio.set_event_loop_policy(HassEventLoopPolicy(False))
asyncio.set_event_loop_policy = lambda policy: None

# Disable sleep in tests
_sleep = asyncio.sleep
asyncio.sleep = lambda _: _sleep(0)


@pytest.fixture(autouse=True)
def time_freezer() -> Generator[freezegun.api.FrozenDateTimeFactory, None, None]:
    with freezegun.freeze_time("2019-02-26T15:02:39Z") as frozen_time:
        yield frozen_time


@pytest.fixture(autouse=True)
def set_request_context(request: pytest.FixtureRequest):
    """Set request context for every test."""
    REQUEST_CONTEXT.set(request)


@pytest.fixture()
def connection():
    """Mock fixture for connection."""
    yield MagicMock()


@pytest.fixture
def hass_storage():
    """Fixture to mock storage."""
    with mock_storage() as stored_data:
        yield stored_data


@pytest.fixture(scope="session")
def event_loop():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def hass(time_freezer, event_loop, tmpdir, check_report_issue: None):
    """Fixture to provide a test instance of Home Assistant."""

    def exc_handle(loop, context):
        """Handle exceptions by rethrowing them, which will fail the test."""
        if exception := context.get("exception"):
            exceptions.append(exception)
        orig_exception_handler(loop, context)

    exceptions: list[Exception] = []
    if AwesomeVersion(HA_VERSION) > "2023.6.0":
        context_manager = async_test_home_assistant_dev(event_loop, config_dir=tmpdir.strpath)
        hass_obj = event_loop.run_until_complete(context_manager.__aenter__())
    else:
        hass_obj = event_loop.run_until_complete(
            async_test_home_assistant_min_version(event_loop, config_dir=tmpdir.strpath)
        )
    event_loop.run_until_complete(async_setup_component(hass_obj, "homeassistant", {}))
    with patch("homeassistant.components.python_script.setup", return_value=True):
        assert event_loop.run_until_complete(async_setup_component(hass_obj, "python_script", {}))

    orig_exception_handler = event_loop.get_exception_handler()
    event_loop.set_exception_handler(exc_handle)

    yield hass_obj

    event_loop.run_until_complete(hass_obj.async_stop(force=True))
    for ex in exceptions:
        raise ex
    shutil.rmtree(hass_obj.config.config_dir)


@pytest.fixture
def hacs(hass: HomeAssistant, setup_integration: None) -> HacsBase:
    """Fixture to provide a HACS object."""
    return get_hacs(hass)


@pytest.fixture
def repository(hacs):
    """Fixtrue for HACS repository object"""
    yield dummy_repository_base(hacs)


@pytest.fixture
def repository_integration(hacs):
    """Fixtrue for HACS integration repository object"""
    repository_obj = HacsIntegrationRepository(hacs, "test/test")
    yield dummy_repository_base(hacs, repository_obj)


@pytest.fixture
def repository_theme(hacs):
    """Fixtrue for HACS theme repository object"""
    repository_obj = HacsThemeRepository(hacs, "test/test")
    yield dummy_repository_base(hacs, repository_obj)


@pytest.fixture
def repository_plugin(hacs):
    """Fixtrue for HACS plugin repository object"""
    repository_obj = HacsPluginRepository(hacs, "test/test")
    yield dummy_repository_base(hacs, repository_obj)


@pytest.fixture
def repository_python_script(hacs):
    """Fixtrue for HACS python_script repository object"""
    repository_obj = HacsPythonScriptRepository(hacs, "test/test")
    yield dummy_repository_base(hacs, repository_obj)


@pytest.fixture
def repository_template(hacs):
    """Fixtrue for HACS template repository object"""
    repository_obj = HacsTemplateRepository(hacs, "test/test")
    yield dummy_repository_base(hacs, repository_obj)


@pytest.fixture
def repository_appdaemon(hacs):
    """Fixtrue for HACS appdaemon repository object"""
    repository_obj = HacsAppdaemonRepository(hacs, "test/test")
    yield dummy_repository_base(hacs, repository_obj)


@pytest.fixture
def repository_netdaemon(hacs):
    """Fixtrue for HACS netdaemon repository object"""
    repository_obj = HacsNetdaemonRepository(hacs, "test/test")
    yield dummy_repository_base(hacs, repository_obj)


class SnapshotFixture(Snapshot):
    async def assert_hacs_data(
        self,
        hacs: HacsBase,
        filename: str,
        additional: dict[str, Any] | None = None,
    ):
        pass


@pytest.fixture
def snapshots(snapshot: Snapshot) -> SnapshotFixture:
    """Fixture for a snapshot."""
    snapshot.snapshot_dir = "tests/snapshots"

    async def assert_hacs_data(
        hacs: HacsBase,
        filename: str,
        additional: dict[str, Any] | None = None,
    ):
        await hacs.data.async_force_write()
        downloaded = [
            f.replace(f"{hacs.core.config_path}", "/config")
            for f in iglob(f"{hacs.core.config_path}/**", recursive=True)
            if os.path.isfile(f)
        ]
        data = {}
        stored_data = await async_load_from_store(hacs.hass, "data")
        for key, value in stored_data["repositories"].items():
            data[key] = {}
            for entry in value:
                data[key][entry["id"]] = entry

        snapshot.assert_match(
            safe_json_dumps(
                recursive_remove_key(
                    {
                        "_directory": sorted(f for f in downloaded if f not in IGNORED_BASE_FILES),
                        "_data": data,
                        "_hacs": {
                            "system": asdict(hacs.system),
                            "status": asdict(hacs.status),
                            "stage": hacs.stage,
                            "configuration": {
                                "experimental": hacs.configuration.experimental,
                                "debug": hacs.configuration.debug,
                                "dev": hacs.configuration.dev,
                            },
                        },
                        "_entities": sorted(
                            (
                                {
                                    "entity_id": hacs.hass.states.get(entity.entity_id).entity_id,
                                    "state": hacs.hass.states.get(entity.entity_id).state,
                                    "attributes": hacs.hass.states.get(entity.entity_id).attributes,
                                    **recursive_remove_key(entity.as_partial_dict, ("id",)),
                                }
                                for entity in er.async_entries_for_config_entry(
                                    er.async_get(hacs.hass),
                                    hacs.configuration.config_entry.entry_id,
                                )
                            ),
                            key=lambda x: x["unique_id"],
                        ),
                        **(additional or {}),
                    },
                    ("categories", "config_entry_id", "device_id", "labels"),
                )
            ),
            filename,
        )

    snapshot.assert_hacs_data = assert_hacs_data
    return snapshot


@pytest_asyncio.fixture(autouse=True)
async def proxy_session(hass: HomeAssistant) -> Generator:
    """Fixture for a proxy_session."""
    mock_session = await client_session_proxy(hass)
    with patch(
        "homeassistant.helpers.aiohttp_client.async_get_clientsession", return_value=mock_session
    ), patch("scripts.data.generate_category_data.ClientSession", ProxyClientSession), patch(
        "aiohttp.ClientSession", ProxyClientSession
    ):
        yield


@pytest_asyncio.fixture
async def ws_client(hass: HomeAssistant) -> WSClient:
    """Owner authenticated Websocket client fixture."""
    auth_provider = HassAuthProvider(hass, hass.auth._store, {"type": "homeassistant"})
    hass.auth._providers[(auth_provider.type, auth_provider.id)] = auth_provider
    owner = MockOwner.create(hass)

    credentials = Credentials(
        auth_provider_type=auth_provider.type,
        auth_provider_id=auth_provider.id,
        data={"username": "testadmin"},
    )

    await auth_provider.async_initialize()
    await hass.auth.async_link_user(owner, credentials)
    refresh_token = await hass.auth.async_create_refresh_token(
        owner, "https://hacs.xyz/testing", credential=credentials
    )

    return WSClient(hass, hass.auth.async_create_access_token(refresh_token))


@pytest.fixture()
def response_mocker() -> ResponseMocker:
    """Mock fixture for responses."""
    mocker = ResponseMocker()
    yield mocker
    mocker.responses.clear()


@pytest_asyncio.fixture()
async def setup_integration(hass: HomeAssistant, check_report_issue: None) -> None:
    ## Assert the string to ensure the format did not change
    if AwesomeVersion(HA_VERSION) >= "2023.11.0":
        assert not len(_async_suggest_report_issue_mock_call_tracker)
        _async_suggest_report_issue_mock_call_tracker.clear()
        assert (
            loader.async_suggest_report_issue(
                hass, integration_domain=DOMAIN, module="custom_components.hacs"
            )
            == "report it to the author of the 'hacs' custom integration"
        )
        assert len(_async_suggest_report_issue_mock_call_tracker) == 1
        _async_suggest_report_issue_mock_call_tracker.clear()

    assert len(_async_suggest_report_issue_mock_call_tracker) == 0

    config_entry = create_config_entry(
        options={
            "experimental": True,
            "appdaemon": True,
            "netdaemon": True,
        }
    )
    await common_setup_integration(hass, config_entry)
    yield
    await hass.config_entries.async_remove(config_entry.entry_id)


@pytest_asyncio.fixture()
async def check_report_issue() -> None:
    """Finish things up."""
    yield
    if times := len(_async_suggest_report_issue_mock_call_tracker):
        raise AssertionError(
            f"homeassistant.loader.async_suggest_report_issue has been called {times} times"
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int):
    response_mocker = ResponseMocker()
    calls = {}

    if session.config.args[0] != "tests" or exitstatus != 0:
        return

    for call in response_mocker.calls:
        if (_test_caller := call.get("_test_caller")) is None:
            continue
        if _test_caller not in calls:
            if call.get("_uses_setup_integration"):
                calls[_test_caller] = {
                    c: -1
                    for c in [
                        "https://data-v2.hacs.xyz/appdaemon/data.json",
                        "https://data-v2.hacs.xyz/critical/data.json",
                        "https://data-v2.hacs.xyz/integration/data.json",
                        "https://data-v2.hacs.xyz/plugin/data.json",
                        "https://data-v2.hacs.xyz/python_script/data.json",
                        "https://data-v2.hacs.xyz/removed/data.json",
                        "https://data-v2.hacs.xyz/template/data.json",
                        "https://data-v2.hacs.xyz/theme/data.json",
                    ]
                }
            else:
                calls[_test_caller] = {}
        if (url := call.get("url")) not in calls[_test_caller]:
            calls[_test_caller][url] = 0
        calls[_test_caller][url] += 1

    filtered_calls = {
        k: v
        for k, v in {t: {k: v for k, v in c.items() if v != 0} for t, c in calls.items()}.items()
        if v
    }

    if session.config.option.snapshot_update:
        with open("tests/output/proxy_calls.json", mode="w", encoding="utf-8") as file:
            file.write(safe_json_dumps(filtered_calls))
            return

    with open("tests/output/proxy_calls.json", encoding="utf-8") as file:
        current = json.load(file)
        if current != filtered_calls:
            diff = ""
            for test in current:
                if test not in filtered_calls:
                    diff += f"Test '{test}' was removed\n"
            for test in filtered_calls:
                if test not in current:
                    diff += f"Test '{test}' was added\n"
            for test in filtered_calls:
                if test not in current:
                    continue
                if filtered_calls[test] == current[test]:
                    continue
                diff += f"Test '{test}' has changed\n"
                diff += "\n".join(_compare_eq_iterable(filtered_calls[test], current[test], 3))
                diff += "\n"

            raise AssertionError(f"API calls have changed, run scripts/snapshot-update\n{diff}")
