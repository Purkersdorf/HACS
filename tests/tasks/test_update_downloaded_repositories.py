# pylint: disable=missing-function-docstring,missing-module-docstring, protected-access
import pytest

from custom_components.hacs.base import HacsBase
from custom_components.hacs.enums import HacsCategory, HacsStage
from custom_components.hacs.repositories.base import HacsRepository


@pytest.mark.asyncio
async def test_update_downloaded_repositories(hacs: HacsBase, repository: HacsRepository):
    await hacs.tasks.async_load()
    task = hacs.tasks.get("update_downloaded_repositories")

    repository.data.category = HacsCategory.INTEGRATION
    repository.data.installed = True
    hacs.repositories.register(repository)

    hacs.enable_hacs_category(HacsCategory.INTEGRATION)

    assert task

    assert hacs.queue.pending_tasks == 0
    await task.execute_task()
    assert hacs.queue.pending_tasks == 1


@pytest.mark.asyncio
async def test_update_downloaded_repositories_skip_hacs_on_startup(
    hacs: HacsBase,
    repository: HacsRepository,
):
    await hacs.tasks.async_load()
    task = hacs.tasks.get("update_downloaded_repositories")

    hacs.status.startup = True

    repository.data.category = HacsCategory.INTEGRATION
    repository.data.installed = True
    repository.data.full_name = "hacs/integration"
    hacs.repositories.register(repository)

    hacs.enable_hacs_category(HacsCategory.INTEGRATION)

    assert task

    assert hacs.queue.pending_tasks == 0
    await task.execute_task()
    assert hacs.queue.pending_tasks == 0
