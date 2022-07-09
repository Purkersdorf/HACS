"""Class for plugins in HACS."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..enums import HacsCategory, HacsDispatchEvent
from ..exceptions import HacsException
from ..utils.decorator import concurrent
from ..utils.json import json_loads
from .base import HacsRepository

if TYPE_CHECKING:
    from ..base import HacsBase


class HacsPluginRepository(HacsRepository):
    """Plugins in HACS."""

    def __init__(self, hacs: HacsBase, full_name: str):
        """Initialize."""
        super().__init__(hacs=hacs)
        self.data.full_name = full_name
        self.data.full_name_lower = full_name.lower()
        self.data.file_name = None
        self.data.category = HacsCategory.PLUGIN
        self.content.path.local = self.localpath

    @property
    def localpath(self):
        """Return localpath."""
        return f"{self.hacs.core.config_path}/www/community/{self.data.full_name.split('/')[-1]}"

    async def validate_repository(self):
        """Validate."""
        # Run common validation steps.
        await self.common_validate()

        # Custom step 1: Validate content.
        self.update_filenames()

        if self.content.path.remote is None:
            raise HacsException(
                f"{self.string} Repository structure for {self.ref.replace('tags/','')} is not compliant"
            )

        if self.content.path.remote == "release":
            self.content.single = True

        # Handle potential errors
        if self.validate.errors:
            for error in self.validate.errors:
                if not self.hacs.status.startup:
                    self.logger.error("%s %s", self.string, error)
        return self.validate.success

    @concurrent(concurrenttasks=10, backoff_time=5)
    async def update_repository(self, ignore_issues=False, force=False):
        """Update."""
        if not await self.common_update(ignore_issues, force) and not force:
            return

        # Get plugin objects.
        self.update_filenames()

        if self.content.path.remote is None:
            self.validate.errors.append(
                f"{self.string} Repository structure for {self.ref.replace('tags/','')} is not compliant"
            )

        if self.content.path.remote == "release":
            self.content.single = True

        # Signal entities to refresh
        if self.data.installed:
            self.hacs.async_dispatch(
                HacsDispatchEvent.REPOSITORY,
                {
                    "id": 1337,
                    "action": "update",
                    "repository": self.data.full_name,
                    "repository_id": self.data.id,
                },
            )

    async def get_package_content(self):
        """Get package content."""
        try:
            package = await self.repository_object.get_contents("package.json", self.ref)
            package = json_loads(package.content)

            if package:
                self.data.authors = package["author"]
        except BaseException:  # lgtm [py/catch-base-exception] pylint: disable=broad-except
            pass

    def update_filenames(self) -> None:
        """Get the filename to target."""
        possible_locations = (
            ("",) if self.repository_manifest.content_in_root else ("release", "dist", "")
        )

        # Handler for plug requirement 3
        if self.repository_manifest.filename:
            valid_filenames = (self.repository_manifest.filename,)
        else:
            valid_filenames = (
                f"{self.data.name.replace('lovelace-', '')}.js",
                f"{self.data.name}.js",
                f"{self.data.name}.umd.js",
                f"{self.data.name}-bundle.js",
            )

        for location in possible_locations:
            if location == "release":
                if not self.releases.objects:
                    continue
                release = self.releases.objects[0]
                if not release.assets:
                    continue
                asset = release.assets[0]
                for filename in valid_filenames:
                    if filename == asset.name:
                        self.data.file_name = filename
                        self.content.path.remote = "release"
                        break

            else:
                for filename in valid_filenames:
                    if f"{location+'/' if location else ''}{filename}" in [
                        x.full_path for x in self.tree
                    ]:
                        self.data.file_name = filename.split("/")[-1]
                        self.content.path.remote = location
                        break
