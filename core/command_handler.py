from __future__ import annotations

from typing import TYPE_CHECKING

from core.cmd_general import GeneralCommands
from core.cmd_sistema import SistemaCommands
from core.cmd_network import NetworkCommands
from core.cmd_rf import RFCommands
from core.cmd_wireless import WirelessCommands
from core.cmd_mobile import MobileCommands
from core.cmd_osint import OsintCommands
from core.cmd_ofensivo import OfensivoCommands

if TYPE_CHECKING:
    from Main import ApexSentinel


class CommandHandler(
    GeneralCommands,
    SistemaCommands,
    NetworkCommands,
    RFCommands,
    WirelessCommands,
    MobileCommands,
    OsintCommands,
    OfensivoCommands,
):
    def __init__(self, sentinel: ApexSentinel) -> None:
        self.s = sentinel
