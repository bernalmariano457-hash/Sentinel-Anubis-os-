"""
╔══════════════════════════════════════════════════════════════════╗
║  APEX SENTINEL — validators.py                                   ║
║  Validación de entradas del usuario                              ║
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import ipaddress
import re
from typing import Optional

from rich.console import Console
from rich.prompt import Prompt


class Validador:
    MAX_INTENTOS = 3

    @staticmethod
    def es_ip(v: str) -> bool:
        try:
            ipaddress.ip_address(v)
            return True
        except ValueError:
            return False

    @staticmethod
    def es_rango_cidr(v: str) -> bool:
        try:
            ipaddress.ip_network(v, strict=False)
            return True
        except ValueError:
            return False

    @staticmethod
    def es_mac(v: str) -> bool:
        return bool(re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", v))

    @staticmethod
    def es_url(v: str) -> bool:
        return bool(re.match(
            r"^https?://[^\s/$.?#].[^\s]*$", v, re.IGNORECASE
        ))

    @staticmethod
    def es_frecuencia(v: str) -> bool:
        try:
            return 1.0 <= float(v) <= 6000.0
        except ValueError:
            return False

    @classmethod
    def pedir(cls, console: Console, prompt: str, validador=None,
              error: str = "Valor inválido.", default=None,
              password: bool = False, intentos: Optional[int] = None):
        max_i = intentos or cls.MAX_INTENTOS
        prompt_fmt = f"\n[bold cyan]{prompt}[/bold cyan]"
        if default is not None:
            prompt_fmt += f" [dim](Enter = {default})[/dim]"
        prompt_fmt += ": "

        for i in range(max_i):
            try:
                if password:
                    valor = Prompt.ask(prompt_fmt, password=True)
                else:
                    valor = console.input(prompt_fmt).strip()
                if not valor and default is not None:
                    return default
                if validador is None or validador(valor):
                    return valor
                restantes = max_i - i - 1
                msg = f"  [red][!] {error}[/red]"
                if restantes > 0:
                    msg += f" [dim]({restantes} intento{'s' if restantes != 1 else ''} restante)[/dim]"
                console.print(msg)
            except KeyboardInterrupt:
                console.print("\n[yellow][!] Cancelado.[/yellow]")
                raise
        return default

    @classmethod
    def pedir_ip(cls, console: Console, prompt: str = "[?] IP objetivo"):
        return cls.pedir(console, prompt, cls.es_ip, "IP inválida. Ej: 192.168.1.1")

    @classmethod
    def pedir_rango(cls, console: Console, prompt: str = "[?] Rango de red",
                    default: str = "192.168.1.0/24"):
        return cls.pedir(console, prompt, cls.es_rango_cidr,
                         "CIDR inválido. Ej: 192.168.1.0/24", default=default)

    @classmethod
    def pedir_url(cls, console: Console, prompt: str = "[?] URL objetivo"):
        return cls.pedir(console, prompt, cls.es_url,
                         "URL inválida. Debe empezar con http:// o https://")

    @classmethod
    def pedir_frecuencia(cls, console: Console, prompt: str = "[?] Frecuencia (MHz)"):
        v = cls.pedir(console, prompt, cls.es_frecuencia,
                      "Frecuencia inválida. Rango: 1.0 - 6000.0 MHz")
        return float(v) if v else None

    @classmethod
    def pedir_segundos(cls, console: Console, prompt: str = "[?] Duración (segundos)",
                       minimo: int = 1, maximo: int = 300,
                       default: int = 30) -> int:
        def validar(v):
            try:
                return minimo <= int(v) <= maximo
            except ValueError:
                return False
        v = cls.pedir(
            console, f"{prompt} [{minimo}-{maximo}]", validar,
            f"Número entre {minimo} y {maximo}.", default=str(default)
        )
        return int(v) if v else default
