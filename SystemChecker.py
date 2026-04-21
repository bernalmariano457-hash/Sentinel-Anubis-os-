import shutil
from rich.table import Table
from rich.panel import Panel
from rich.console import Console

console = Console()


class SystemChecker:
    def __init__(self):
        # Mapeo de comandos que el Sentinel necesita
        self.dependencies = {
            "Network Audit": "nmap",
            "SQL Injection": "sqlmap",
            "Brute Force": "hydra",
            "Mobile Forensic": "adb",
            "Exploit Engine": "msfconsole"
        }

    def verificar_dependencias(self):
        tabla = Table(
            title="[bold cyan]🔍 DIAGNÓSTICO DE DEPENDENCIAS[/bold cyan]", box=None)
        tabla.add_column("Capacidad", style="white")
        tabla.add_column("Herramienta", style="bold yellow")
        tabla.add_column("Estado", justify="center")

        all_ok = True

        for capacidad, comando in self.dependencies.items():
            # shutil.which busca el ejecutable en el sistema
            instalado = shutil.which(comando) is not None

            estado = "[bold green]OK[/bold green]" if instalado else "[bold red]MISSING[/bold red]"
            tabla.add_row(capacidad, comando, estado)

            if not instalado:
                all_ok = False

        console.print(tabla)

        if not all_ok:
            console.print(Panel(
                "[yellow][!] Advertencia:[/yellow] Algunas funciones están deshabilitadas.\n"
                "Instala las herramientas faltantes para tener acceso total.",
                border_style="yellow"
            ))
        else:
            console.print(
                "[bold green][+] Todos los sistemas críticos están operativos.[/bold green]\n")

        return all_ok
