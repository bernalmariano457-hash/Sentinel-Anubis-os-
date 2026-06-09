from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class DictionaryManager:

    def __init__(self, sentinel=None) -> None:
        if sentinel is not None and hasattr(sentinel, "console"):
            self._console = sentinel.console
        else:
            from rich.console import Console
            self._console = Console()

    BASE_PATHS: list[str] = [
        "/usr/share/wordlists",
        "/usr/share/seclists",
        os.path.expanduser("~/.wordlists"),
    ]

    DICT_MAP: dict[str, list[str]] = {
        "ssh": [
            "metasploit/unix_passwords.txt",
            "rockyou.txt",
        ],
        "ftp": [
            "metasploit/ftp_default_pass.txt",
            "metasploit/unix_passwords.txt",
        ],
        "http-post-form": [
            "dirbuster/directory-list-2.3-medium.txt",
            "dirbuster/directory-list-2.3-small.txt",
        ],
        "http-get": [
            "dirbuster/directory-list-2.3-medium.txt",
            "dirbuster/directory-list-2.3-small.txt",
        ],
        "mysql": [
            "metasploit/mysql_default_pass.txt",
            "rockyou.txt",
        ],
        "telnet": [
            "metasploit/mirai_pass.txt",
            "metasploit/unix_passwords.txt",
        ],
        "smb": [
            "metasploit/unix_passwords.txt",
            "rockyou.txt",
        ],
        "rdp": [
            "rockyou.txt",
        ],
        "default": [
            "rockyou.txt",
        ],
    }

    LOCAL_FALLBACK = Path("local_pass.txt")

    # API pública

    def obtener_ruta_diccionario(self, protocolo: str) -> Path | None:
        protocolo = protocolo.lower().strip()
        candidatos = self.DICT_MAP.get(protocolo, self.DICT_MAP["default"])

        for base in self.BASE_PATHS:
            for sub in candidatos:
                ruta = Path(base) / sub
                if ruta.is_file():
                    logger.info("[Dict] Usando: %s", ruta)
                    return ruta

        for base in self.BASE_PATHS:
            ruta = Path(base) / "rockyou.txt"
            if ruta.is_file():
                self._console.print(
                    f"[yellow][!] Diccionario específico para '{protocolo}' no encontrado. "
                    f"Usando rockyou.txt[/yellow]"
                )
                return ruta

        if self.LOCAL_FALLBACK.is_file():
            self._console.print(
                "[bold red][!] Wordlists estándar no encontradas. "
                "Usando local_pass.txt[/bold red]"
            )
            return self.LOCAL_FALLBACK

        self._console.print(
            "[bold red][!] No se encontró ningún diccionario. "
            "Instala wordlists: sudo apt install wordlists seclists[/bold red]"
        )
        logger.error(
            "[Dict] Sin diccionarios disponibles para protocolo: %s", protocolo)
        return None

    def listar_protocolos(self) -> list[str]:
        return [p for p in self.DICT_MAP if p != "default"]

    def agregar_protocolo(self, protocolo: str, rutas: list[str]) -> None:
        self.DICT_MAP[protocolo.lower()] = rutas
        logger.info("[Dict] Protocolo '%s' registrado con %d rutas.",
                    protocolo, len(rutas))
