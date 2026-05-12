from __future__ import annotations

from core.cmd_general import GeneralCommands
from core.cmd_sistema import SistemaCommands
from core.cmd_network import NetworkCommands
from core.cmd_rf import RFCommands
from core.cmd_wireless import WirelessCommands
from core.cmd_mobile import MobileCommands
from core.cmd_osint import OsintCommands
from core.cmd_ofensivo import OfensivoCommands


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

    def __init__(self, sentinel):
        # _DomainBase.__init__ asigna self.s = sentinel
        # Con MRO de Python todos los mixins lo heredan correctamente
        self.s = sentinel
