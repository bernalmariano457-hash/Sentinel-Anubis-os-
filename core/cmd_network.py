from __future__ import annotations

import socket
import time

from rich import box
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from core.commands._base import _DomainBase
from core.validators import Validador


class NetworkCommands(_DomainBase):

    # ── ARP Scan ──────────────────────────────────────────────────────

    def scan(self):
        s = self.s
        if s._ARP is None:
            self.console.print("[red][!] Scapy no disponible.[/red]")
            return
        rango = Validador.pedir_rango(self.console)
        if not rango:
            return
        s.animar_barra(f"ESCANEANDO HOSTS EN {rango}...")
        try:
            resultado = s._srp(
                s._Ether(dst="ff:ff:ff:ff:ff:ff") / s._ARP(pdst=rango),
                timeout=3, verbose=False
            )[0]
            tabla = Table(header_style="bold cyan",
                          box=box.SIMPLE_HEAD, show_edge=False)
            tabla.add_column("IP",         style="cyan",   min_width=15)
            tabla.add_column("MAC",        style="yellow", min_width=18)
            tabla.add_column("Fabricante", style="white")
            hosts = []
            for _, reci in resultado:
                fab = s.obtener_fabricante(reci.hwsrc)
                tabla.add_row(reci.psrc, reci.hwsrc, fab)
                hosts.append(
                    {"ip": reci.psrc, "mac": reci.hwsrc, "fabricante": fab})
            self.console.print(tabla)
            if s.gp:
                s.gp.registrar_evidencia(
                    "arp_scan", f"Scan ARP en {rango}: {len(hosts)} hosts",
                    {"rango": rango, "hosts": hosts})
            s.log.info(
                f"Scan ARP en {rango}: {len(resultado)} hosts", "NetworkScan")
        except Exception:
            self.console.print(
                "[red][!] Error de permisos. Ejecuta como root/administrador.[/red]")

    # ── Port Scan ─────────────────────────────────────────────────────

    def portscan(self):
        s = self.s
        objetivo = Validador.pedir_ip(
            self.console, f"\n{s.nombre} [TARGET IP]")
        if not objetivo:
            return
        s.animar_barra(f"AUDITANDO PUERTOS EN {objetivo}...")
        puertos = {
            21: "FTP",    22: "SSH",        23: "Telnet",
            25: "SMTP",   80: "HTTP",       443: "HTTPS",
            445: "SMB",   3306: "MySQL",    5432: "PostgreSQL",
            8080: "HTTP-Alt",
        }
        tabla = Table(header_style="bold red",
                      box=box.SIMPLE_HEAD, show_edge=False)
        tabla.add_column("Puerto",   style="cyan",   justify="center")
        tabla.add_column("Servicio", style="yellow")
        tabla.add_column("Estado",   justify="center")
        abiertos = []
        for puerto, servicio in puertos.items():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                if sock.connect_ex((objetivo, puerto)) == 0:
                    tabla.add_row(str(puerto), servicio,
                                  "[green]ABIERTO[/green]")
                    abiertos.append({"puerto": puerto, "servicio": servicio})
                sock.close()
            except socket.error:
                pass
        self.console.print(tabla)
        self.console.print(f"[dim]Puertos abiertos: {len(abiertos)}[/dim]")
        if s.gp and abiertos:
            s.gp.registrar_evidencia(
                "portscan", f"PortScan en {objetivo}: {len(abiertos)} puertos",
                {"ip": objetivo, "puertos": abiertos})
        s.log.info(
            f"PortScan {objetivo}: {len(abiertos)} puertos abiertos", "PortScan")
        if abiertos and s.cve:
            if Prompt.ask("\n[?] ¿Cruzar con CVE?", choices=["s", "n"], default="s") == "s":
                s.cve.analizar_resultado_scan(
                    [{"nombre": a["servicio"], "version": ""} for a in abiertos])

    # ── Sweep / Sniff / AdvScan ───────────────────────────────────────

    def sweep(self):
        if not self._modulo_ok("sweep"):
            return
        rango = Validador.pedir_rango(self.console)
        self.s.sweep.escanear_perimetro(rango)

    def sniff(self):
        if not self._modulo_ok("sniffer"):
            return
        filtro = self.console.input(
            "\n[bold cyan]  [?] Filtro (Enter para ninguno)[/bold cyan]: ").strip()
        segundos = Validador.pedir_segundos(self.console, default=30)
        self.s.sniffer.iniciar_captura(filtro=filtro, duracion=segundos)

    def advscan(self):
        if not self._modulo_ok("adv_scanner"):
            return
        ip = Validador.pedir_ip(self.console, "[?] IP del objetivo")
        if ip:
            self.s.adv_scanner.escanear_objetivo(ip)

    # ── Radar ─────────────────────────────────────────────────────────

    def radar(self):
        s = self.s
        if not self._modulo_ok("radar") or not self._modulo_ok("geomap"):
            return
        s._limpiar()
        s.geomap.abrir_mapa()
        try:
            while True:
                panel_radar = s.radar.render_radar()
                s.geomap.generar_mapa(s.radar.targets)
                s._limpiar()
                self.console.print(panel_radar)
                time.sleep(2)
        except KeyboardInterrupt:
            self.console.print("\n[yellow][!] Radar detenido.[/yellow]")

    # ── Auditoría / Hydra ─────────────────────────────────────────────

    def audit(self):
        s = self.s
        if not self._modulo_ok("hydra") or not self._modulo_ok("dict_manager"):
            return
        self.console.print(
            "\n[bold magenta]⚔  MÓDULO HYDRA INICIADO[/bold magenta]")
        target = Validador.pedir_ip(self.console, "[?] IP del objetivo")
        if not target:
            return
        servicio = Prompt.ask(
            "[?] Servicio",
            choices=["ssh", "ftp", "mysql", "http-get", "telnet"],
            default="ssh",
        )
        diccionario = s.dict_manager.obtener_ruta_diccionario(servicio)
        if diccionario is None:
            self.console.print(
                "[red][!] No hay diccionarios disponibles. "
                "Instala wordlists: sudo apt install wordlists[/red]")
            return
        if Prompt.ask(f"¿Iniciar ataque con {diccionario}?", choices=["s", "n"], default="n") == "s":
            resultado = s.hydra.ejecutar_ataque(
                target, servicio, "root", diccionario)
            if resultado:
                s.mostrar_dashboard_exito(target, servicio, resultado)

    # ── Vuln Scan / SQL Check ─────────────────────────────────────────

    def vulnscan(self):
        s = self.s
        if not self._modulo_ok("audit_engine"):
            return
        target = Validador.pedir_ip(self.console, "[?] IP a analizar")
        if not target:
            return
        resultado = s.audit_engine.escaneo_vulnerabilidades(target)
        if resultado.error:
            self.console.print(
                f"[red][!] Error en escaneo: {resultado.error}[/red]")
            return
        contenido = resultado.stdout or "[dim]Sin resultados.[/dim]"
        self.console.print(
            Panel(contenido, title="RESULTADOS DE VULNERABILIDAD", border_style="red"))
        if resultado.stderr:
            s.log.warning(resultado.stderr[:200], "AuditEngine")
        s.log.audit(f"Vulnscan en {target}", "AuditEngine")

    def sqlcheck(self):
        s = self.s
        if not self._modulo_ok("audit_engine"):
            return
        url = Validador.pedir_url(self.console, "[?] URL Objetivo")
        if not url:
            return
        resultado = s.audit_engine.auditoria_sql(url)
        if resultado.error:
            self.console.print(
                f"[red][!] Error en SQLmap: {resultado.error}[/red]")
            return
        contenido = resultado.stdout or "[dim]Sin resultados.[/dim]"
        self.console.print(
            Panel(contenido, title="INFORME SQLMAP", border_style="yellow"))
        if resultado.stderr:
            s.log.warning(resultado.stderr[:200], "AuditEngine")
        s.log.audit(f"SQLcheck en {url}", "AuditEngine")
