"""Helper constants."""
# pylint: disable=missing-class-docstring
from enum import Enum


class HacsCategory(str, Enum):
    APPDAEMON = "appdaemon"
    INTEGRATION = "integration"
    LOVELACE = "lovelace"
    NETDAEMON = "netdaemon"
    PYTHON_SCRIPT = "python_script"
    THEME = "theme"


class HacsStage(str, Enum):
    SETUP = "setup"
    STARTUP = "startup"
    RUNNING = "running"
    BACKGROUND = "background"
