from __future__ import annotations

import shutil
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


DEPENDENCIAS: dict[str, dict[str, tuple[str, str]]] = {
    "RF / SDR": {
        "rtl_sdr":        ("rtl_sdr",        "rtl-sdr"),
        "rtl_power":      ("rtl_power",       "rtl-sdr"),
        "rtl_test":       ("rtl_test",        "rtl-sdr"),
        "dump1090":       ("dump1090",        "dump1090-fa"),
        "sox":            ("sox",             "sox"),
    },
    "Wireless": {
        "aircrack-ng":    ("aircrack-ng",     "aircrack-ng"),
        "airodump-ng":    ("airodump-ng",     "aircrack-ng"),
        "aireplay-ng":    ("aireplay-ng",     "aircrack-ng"),
        "iwconfig":       ("iwconfig",        "wireless-tools"),
        "hostapd":        ("hostapd",         "hostapd"),
    },
    "Forense": {
        "adb":            ("adb",             "android-tools-adb"),
        "exiftool":       ("exiftool",        "libimage-exiftool-perl"),
        "binwalk":        ("binwalk",         "binwalk"),
        "strings":        ("strings",         "binutils"),
    },
    "Red": {
        "nmap":           ("nmap",            "nmap"),
        "tshark":         ("tshark",          "tshark"),
        "tcpdump":        ("tcpdump",         "tcpdump"),
        "masscan":        ("masscan",         "masscan"),
        "netdiscover":    ("netdiscover",     "netdiscover"),
    },
    "Ataque / Auditoría": {
        "hydra":          ("hydra",           "hydra"),
        "hashcat":        ("hashcat",         "hashcat"),
        "sqlmap":         ("sqlmap",          "sqlmap"),
        "msfconsole":     ("msfconsole",      "metasploit-framework"),
    },
}

_CRITICOS = {"nmap", "aircrack-ng", "tshark", "adb"}


class SystemChecker:

    def __init__(self, console: Console | None = None) -> None:

        self._console = console or Console()

    def verificar_dependencias(self, silencioso: bool = False) -> bool:
        resultados: dict[str, dict[str, bool]] = {}
        criticos_faltantes: list[str] = []

        for categoria, tools in DEPENDENCIAS.items():
            resultados[categoria] = {}
            for nombre, (ejecutable, _paquete) in tools.items():
                ok = shutil.which(ejecutable) is not None
                resultados[categoria][nombre] = ok
                if not ok and ejecutable in _CRITICOS:
                    criticos_faltantes.append(ejecutable)

        if not silencioso:
            self._imprimir_tabla(resultados)

        all_criticos_ok = len(criticos_faltantes) == 0
        return all_criticos_ok

    def _imprimir_tabla(self, resultados: dict[str, dict[str, bool]]) -> None:
        total_ok = 0
        total = 0

        for categoria, tools in resultados.items():
            tabla = Table(
                title=f"[bold cyan]{categoria}[/bold cyan]",
                box=box.SIMPLE_HEAD,
                header_style="bold yellow",
                show_edge=False,
                expand=False,
            )
            tabla.add_column("Herramienta",  style="white",    min_width=18)
            tabla.add_column("Ejecutable",   style="dim cyan",  min_width=16)
            tabla.add_column("Paquete",      style="dim",       min_width=28)
            tabla.add_column("Estado",       justify="center",  min_width=14)

            for nombre, (ejecutable, paquete) in DEPENDENCIAS[categoria].items():
                ok = resultados[categoria][nombre]
                total += 1
                if ok:
                    total_ok += 1
                    estado = "[bold green]✔  OK[/bold green]"
                elif ejecutable in _CRITICOS:
                    estado = "[bold red]✖  CRÍTICO[/bold red]"
                else:
                    estado = "[yellow]○  MISSING[/yellow]"

                tabla.add_row(nombre, ejecutable, paquete, estado)

            self._console.print(tabla)

        # Resumen final
        color = "green" if total_ok == total else (
            "red" if total_ok < total // 2 else "yellow")
        self._console.print(
            Panel(
                f"[{color}]Herramientas disponibles: {total_ok}/{total}[/{color}]\n"
                + (
                    "[green]✔  Todos los sistemas operativos.[/green]"
                    if total_ok == total
                    else "[yellow][!] Algunas funciones estarán deshabilitadas.[/yellow]\n"
                         "[dim]Instala los paquetes faltantes para acceso completo.[/dim]"
                ),
                title="[bold cyan]◈ DIAGNÓSTICO DE DEPENDENCIAS[/bold cyan]",
                border_style=color,
                box=box.HEAVY_HEAD,
            )
        )

    def instalar_sugerencia(self, herramienta: str) -> str | None:
        for tools in DEPENDENCIAS.values():
            if herramienta in tools:
                _, paquete = tools[herramienta]
                return f"sudo apt install -y {paquete}"
        return None
