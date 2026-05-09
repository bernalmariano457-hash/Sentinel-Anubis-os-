from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING

from rich import box
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from core.validators import Validador

if TYPE_CHECKING:
    from sentinel import ApexSentinel  # type: ignore


class CommandHandler:

    def __init__(self, sentinel: "ApexSentinel"):
        self.s = sentinel  # referencia corta al sentinel

    # ── Helpers ───────────────────────────────────────────────────────

    @property
    def console(self):
        return self.s.console

    def _modulo_ok(self, nombre_attr: str) -> bool:
        return self.s._modulo_ok(nombre_attr)

    # ── Generales ─────────────────────────────────────────────────────

    def status(self):
        s = self.s
        proy = s.gp.proyecto_activo.nombre if s.gp and s.gp.proyecto_activo else "Ninguno"
        rf_state = getattr(s.rf, "hw_nombre",
                           "No disponible") if s.rf else "No disponible"
        self.console.print(Panel(
            f"[cyan]Sistema:[/cyan]  {s.nombre}\n"
            f"[cyan]Versión:[/cyan]  {s.version}\n"
            f"[cyan]Estado:[/cyan]   [green]Operacional[/green]\n"
            f"[cyan]Hora:[/cyan]     {time.strftime('%H:%M:%S')}\n"
            f"[cyan]Iface:[/cyan]    {s._iface()}\n"
            f"[cyan]Proyecto:[/cyan] [green]{proy}[/green]\n"
            f"[cyan]RF HW:[/cyan]    {rf_state}",
            title="STATUS", border_style="cyan"
        ))

    def files(self):
        s = self.s
        s.animar_barra("EXPLORANDO DIRECTORIO LOCAL...")
        tabla = Table(header_style="bold cyan",
                      box=box.SIMPLE_HEAD, show_edge=False)
        tabla.add_column("Nombre", style="white")
        tabla.add_column("Tamaño", style="yellow", justify="right")
        tabla.add_column("Tipo",   style="green",  justify="center")
        try:
            for f in sorted(os.listdir(".")):
                try:
                    tabla.add_row(f, f"{os.path.getsize(f):,} bytes",
                                  "DIR" if os.path.isdir(f) else "FILE")
                except OSError:
                    tabla.add_row(f, "N/A", "?")
            self.console.print(tabla)
        except Exception as e:
            s.log.error(f"files: {e}", "Sistema")

    # ── Red ───────────────────────────────────────────────────────────

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
                s.gp.registrar_evidencia("arp_scan", f"Scan ARP en {rango}: {len(hosts)} hosts",
                                         {"rango": rango, "hosts": hosts})
            s.log.info(
                f"Scan ARP en {rango}: {len(resultado)} hosts", "NetworkScan")
        except Exception:
            self.console.print(
                "[red][!] Error de permisos. Ejecuta como root/administrador.[/red]")

    def portscan(self):
        s = self.s
        import socket
        objetivo = Validador.pedir_ip(
            self.console, f"\n{s.nombre} [TARGET IP]")
        if not objetivo:
            return
        s.animar_barra(f"AUDITANDO PUERTOS EN {objetivo}...")
        puertos = {21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
                   80: "HTTP", 443: "HTTPS", 445: "SMB", 3306: "MySQL",
                   5432: "PostgreSQL", 8080: "HTTP-Alt"}
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
            s.gp.registrar_evidencia("portscan", f"PortScan en {objetivo}: {len(abiertos)} puertos",
                                     {"ip": objetivo, "puertos": abiertos})
        s.log.info(
            f"PortScan {objetivo}: {len(abiertos)} puertos abiertos", "PortScan")
        if abiertos and s.cve:
            if Prompt.ask("\n[?] ¿Cruzar con CVE?", choices=["s", "n"], default="s") == "s":
                s.cve.analizar_resultado_scan(
                    [{"nombre": a["servicio"], "version": ""} for a in abiertos])

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

    def audit(self):
        s = self.s
        if not self._modulo_ok("hydra") or not self._modulo_ok("dict_manager"):
            return
        self.console.print(
            "\n[bold magenta]⚔  MÓDULO HYDRA INICIADO[/bold magenta]")
        target = Validador.pedir_ip(self.console, "[?] IP del objetivo")
        if not target:
            return
        servicio = Prompt.ask("[?] Servicio", choices=[
                              "ssh", "ftp", "mysql", "http-get", "telnet"], default="ssh")
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

    # ── Wireless ──────────────────────────────────────────────────────

    def wifi(self):
        s = self.s
        if not self._modulo_ok("bt"):
            return
        self.console.print("\n[1] Beacon Spam  [2] Deauth Attack")
        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()
        if opt == "1":
            prefijo = self.console.input(
                "[bold cyan]Prefijo SSID: [/bold cyan]").strip()
            s.bt.beacon_spam(prefijo)
        elif opt == "2":
            mac_vic = Validador.pedir(
                self.console, "MAC Víctima", Validador.es_mac, "MAC inválida. Ej: AA:BB:CC:DD:EE:FF")
            mac_ap = Validador.pedir(
                self.console, "MAC AP",      Validador.es_mac, "MAC inválida.")
            if mac_vic and mac_ap:
                s.bt.deauth(mac_vic, mac_ap)

    def eviltwin(self):
        s = self.s
        if not self._modulo_ok("wifi_attack"):
            return
        if s._evil_twin_server is None:
            self.console.print("[red][!] EvilTwinServer no disponible.[/red]")
            return
        ssid = self.console.input("[bold cyan] [?] SSID: [/bold cyan]").strip()
        if not ssid:
            return
        s.wifi_attack.crear_gemelo_malvado(ssid, 6)
        threading.Thread(target=s._evil_twin_server, daemon=True).start()
        input("[!] Presiona Enter para detener...")
        s.wifi_attack.detener_ataques()

    # ── RF ────────────────────────────────────────────────────────────

    def rfscan(self):
        if not self._modulo_ok("rf"):
            return
        freq = Validador.pedir_frecuencia(self.console)
        if freq is not None:
            duracion = Validador.pedir_segundos(
                self.console, "[?] Duración (segundos)", 1, 300, 10)
            self.s.rf.escanear_frecuencia(freq, duracion)

    def rfmenu(self):
        if not self._modulo_ok("rf"):
            return
        self.s.rf.menu()

    def rfbarrido(self):
        if not self._modulo_ok("rf"):
            return
        ini = Validador.pedir_frecuencia(
            self.console, "[?] Frecuencia inicial (MHz)")
        fin = Validador.pedir_frecuencia(
            self.console, "[?] Frecuencia final (MHz)")
        if ini is None or fin is None or ini >= fin:
            self.console.print("[red][!] Rango de frecuencias inválido.[/red]")
            return
        paso_s = self.console.input(
            "\n[bold cyan][?] Paso MHz [1.0]: [/bold cyan]").strip()
        try:
            paso = float(paso_s) if paso_s else 1.0
        except ValueError:
            paso = 1.0
        self.s.rf.barrido_espectro(ini, fin, paso)

    def rfbandas(self):
        if not self._modulo_ok("rf"):
            return
        self.s.rf.escaneo_bandas_conocidas()

    def rfdb(self):
        if not self._modulo_ok("rf"):
            return
        self.s.rf.db_consultar()

    def rfstats(self):
        if not self._modulo_ok("rf"):
            return
        self.s.rf.db_estadisticas()

    def rfestado(self):
        if not self._modulo_ok("rf"):
            return
        self.s.rf.estado()

    def radio(self):
        """Escucha y demodula una frecuencia en tiempo real."""
        if not self._modulo_ok("rf"):
            return
        freq = Validador.pedir_frecuencia(self.console, "[?] Frecuencia (MHz)")
        if freq is None:
            return
        self.console.print(
            "\n[bold cyan][?] Modo de demodulación:[/bold cyan]\n"
            "  [1] WFM — Radio FM comercial (87-108 MHz)\n"
            "  [2] NFM — PMR, repetidores, emergencias\n"
            "  [3] AM  — Aviación ATC, AM broadcast\n"
            "  [4] USB — HF amateur, aeronáutico HF\n"
            "  [5] LSB — HF amateur banda baja\n"
        )
        modos = {"1": "wfm", "2": "nfm", "3": "am", "4": "usb", "5": "lsb"}
        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()
        modo = modos.get(opt, "wfm")
        duracion = Validador.pedir_segundos(
            self.console, "[?] Duración (segundos)", 5, 300, 30)
        guardar = self.console.input(
            "\n[bold cyan][?] ¿Guardar audio WAV? (s/N): [/bold cyan]"
        ).strip().lower() == "s"

        self.console.print(
            f"\n[bold green][RF] Sintonizando {freq:.3f} MHz · "
            f"Modo: {modo.upper()} · {duracion}s[/bold green]\n"
            "[dim]Ctrl+C para detener[/dim]\n"
        )
        try:
            import time
            import numpy as np
            from pathlib import Path
            from datetime import datetime
            from modules.rf.rf_demod import Demodulator
            from modules.rf.rf_config import DemodConfig

            cfg = DemodConfig(mode=modo, audio_rate=48000, volume=0.85)
            demod = Demodulator(cfg, sample_rate=2_048_000)
            audio_total = []
            inicio = time.time()

            while (time.time() - inicio) < duracion:
                muestras = self.s.rf._capturar(freq * 1e6)
                if muestras is None:
                    break
                audio = demod.demodulate(muestras)
                if audio is not None:
                    demod.play(audio)
                    if guardar:
                        audio_total.append(audio.copy())

            if guardar and audio_total:
                ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                dest = Path("data/evidence/rf") / \
                    f"audio_{freq:.3f}MHz_{modo}_{ts}.wav"
                dest.parent.mkdir(parents=True, exist_ok=True)
                demod.save_wav(np.concatenate(audio_total), str(dest))
                self.console.print(
                    f"[green][+] Audio guardado: {dest}[/green]")

            demod.stop_audio()
        except KeyboardInterrupt:
            self.console.print("\n[yellow][!] Demodulación detenida.[/yellow]")
        except ImportError as e:
            self.console.print(f"[red][!] Dependencia faltante: {e}[/red]")
            self.console.print(
                "[dim]Instala: pip install scipy sounddevice --break-system-packages[/dim]")
        except Exception as e:
            self.console.print(f"[red][!] Error: {e}[/red]")

    def rfgrabar(self):
        """Graba señal IQ a archivo .iq (compatible SDR# / GQRX / GNU Radio)."""
        if not self._modulo_ok("rf"):
            return
        freq = Validador.pedir_frecuencia(
            self.console, "[?] Frecuencia a grabar (MHz)")
        if freq is None:
            return
        duracion = Validador.pedir_segundos(
            self.console, "[?] Duración (segundos)", 5, 300, 10)
        try:
            from modules.rf.rf_recorder import RFRecorder
            RFRecorder(self.s).grabar(freq_mhz=freq, duracion_seg=duracion)
        except ImportError:
            self.console.print("[red][!] rf_recorder.py no encontrado.[/red]")

    def rfplay(self):
        """Reproduce y demodula un archivo .iq grabado."""
        try:
            from modules.rf.rf_recorder import RFRecorder
            rec = RFRecorder(self.s)
            rec.listar()
            archivo = self.console.input(
                "\n[bold cyan][?] Nombre del archivo: [/bold cyan]").strip()
            if not archivo:
                return
            self.console.print("[bold cyan][?] Modo:[/bold cyan] "
                               "[1]WFM [2]NFM [3]AM [4]USB [5]LSB")
            modos = {"1": "wfm", "2": "nfm", "3": "am", "4": "usb", "5": "lsb"}
            modo = modos.get(
                self.console.input("[bold cyan] > [/bold cyan]").strip(), "wfm")
            rec.reproducir(archivo, modo=modo)
        except ImportError:
            self.console.print("[red][!] rf_recorder.py no encontrado.[/red]")

    def adsb(self):
        """Monitor ADS-B — decodifica transponders de aeronaves en 1090 MHz."""
        duracion_s = self.console.input(
            "\n[bold cyan][?] Duración segundos (Enter = indefinido): [/bold cyan]"
        ).strip()
        duracion = int(duracion_s) if duracion_s.isdigit() else None
        try:
            from modules.rf.adsb_decoder import ADSBDecoder
            ADSBDecoder(self.s).iniciar(duracion_seg=duracion)
        except ImportError:
            self.console.print("[red][!] adsb_decoder.py no encontrado.[/red]")

    # ── Mobile ────────────────────────────────────────────────────────

    def mobile(self):
        s = self.s
        if not self._modulo_ok("mobile"):
            return
        self.console.print(
            "\n[1] Android Triage  [2] iOS Info  [3] Screenshot")
        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()
        if opt == "1":
            s.mobile.triage_android()
        elif opt == "2":
            s.mobile.triage_ios()
        elif opt == "3":
            path = s.mobile.preparar_directorio("Android_Screen")
            self.console.print("[*] Tomando captura...")
            try:
                s._run(["adb", "shell", "screencap",
                       "-p", "/sdcard/s.png"], timeout=15)
                s._run(["adb", "pull", "/sdcard/s.png",
                       f"{path}/s.png"], timeout=15)
                self.console.print(
                    f"[green][+] Captura guardada en {path}/s.png[/green]")
                s.log.success(
                    f"Screenshot guardado en {path}/s.png", "MobileSentinel")
            except subprocess.TimeoutExpired:
                self.console.print(
                    "[red][!] ADB timeout. Verifica conexión.[/red]")
                s.log.error("ADB timeout screenshot", "MobileSentinel")
            except subprocess.CalledProcessError as e:
                self.console.print(
                    f"[red][!] Error ADB ({e.returncode}): {e}[/red]")
                s.log.error(f"Screenshot ADB: {e}", "MobileSentinel")
            except Exception as e:
                self.console.print(f"[red][!] Error inesperado ADB: {e}[/red]")

    def mobile_deep(self):
        s = self.s
        path = "./data/evidence/mobile/Deep_Extraction/"
        os.makedirs(path, exist_ok=True)

        self.console.print(
            "\n[1] Extraer WhatsApp Full  "
            "[2] Extraer Chrome History  "
            "[3] Descifrar crypt (WADecryptor)"
        )
        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()

        if opt in ("1", "2"):
            if s._db_extractor_cls is None:
                self.console.print(
                    "[red][!] DatabaseExtractor no disponible.[/red]")
                return
            extractor = s._db_extractor_cls()
            s.animar_barra("EXTRAYENDO DB Y LLAVE..." if opt ==
                           "1" else "EXTRAYENDO HISTORIAL CHROME...")
            if opt == "1":
                extractor.extraer_whatsapp(path)
                extractor.extraer_whatsapp_key(path)
                s.log.audit("Extracción WhatsApp completada", "MobileDeep")
            else:
                s.log.audit("Extracción Chrome completada", "MobileDeep")

        elif opt == "3":
            if s._wa_decryptor_cls is None:
                self.console.print("[red][!] WADecryptor no disponible.[/red]")
                return
            crypt_file = self.console.input(
                "[bold cyan][?] Ruta archivo .crypt12/.crypt14/.crypt15: [/bold cyan]").strip().strip("'\"")
            key_file = self.console.input(
                "[bold cyan][?] Ruta archivo key: [/bold cyan]").strip().strip("'\"")
            if not crypt_file or not key_file:
                self.console.print("[red][!] Rutas inválidas.[/red]")
                return
            output_file = os.path.join(path, "whatsapp_decrypted.db")
            try:
                decryptor = s._wa_decryptor_cls(verbose=False)
                if decryptor.descifrar(crypt_file, key_file, output_file):
                    s.log.audit(
                        f"WA descifrado OK → {output_file}", "MobileDeep")
                    self.console.print(
                        f"[green][+] DB lista en: {output_file}[/green]\n[dim]Usa el comando [bold white]view[/bold white] para leerla.[/dim]")
                else:
                    s.log.error(
                        "WADecryptor: descifrado fallido", "MobileDeep")
            except Exception as e:
                self.console.print(f"[red][!] Error en descifrado: {e}[/red]")
                s.log.error(f"WADecryptor: {e}", "MobileDeep")

    def view(self):
        s = self.s
        if not self._modulo_ok("reader"):
            return
        ruta_base = "./data/evidence/mobile/Deep_Extraction/"
        self.console.print(
            "\n[bold cyan]VIEW — Lector Forense[/bold cyan]\n"
            "[1] WhatsApp (Android/iOS auto)\n[2] Chrome History\n[3] Firefox places.sqlite\n"
            "[4] Safari History.db\n[5] Registro de llamadas WA\n"
            "[6] Buscar mensajes eliminados\n[7] Top contactos + timeline de actividad\n"
            "[8] Buscar palabras clave en mensajes\n[9] Exportar reporte HTML completo"
        )
        opcion = self.console.input("[bold cyan] > [/bold cyan]").strip()

        def _db(default_name: str) -> str:
            return (self.console.input(f"[dim][Enter] = {ruta_base}{default_name} > [/dim]").strip()
                    or os.path.join(ruta_base, default_name))

        if opcion == "1":
            s.reader.leer_whatsapp_mensajes(_db("whatsapp_decrypted.db"))
        elif opcion == "2":
            s.reader.leer_historial_chrome(_db("chrome_history.db"))
        elif opcion == "3":
            s.reader.leer_historial_firefox(_db("places.sqlite"))
        elif opcion == "4":
            s.reader.leer_historial_safari(_db("History.db"))
        elif opcion == "5":
            db = _db("whatsapp_decrypted.db")
            llamadas = s.reader.leer_llamadas_android(db)
            s.reader.mostrar_llamadas(llamadas)
        elif opcion == "6":
            db = _db("whatsapp_decrypted.db")
            eliminados = s.reader.leer_mensajes_eliminados(db)
            if eliminados:
                self.console.print(
                    f"[yellow][!] {len(eliminados)} registros potencialmente eliminados:[/yellow]")
                for e in eliminados:
                    self.console.print(
                        f"  [{e['fecha_display']}] [bold]{e['contacto']}[/bold]: {e['texto_recuperado']}")
            else:
                self.console.print(
                    "[dim]Sin registros eliminados detectados.[/dim]")
        elif opcion == "7":
            db = _db("whatsapp_decrypted.db")
            mensajes, _ = s.reader.leer_whatsapp_mensajes(db)
            if mensajes:
                stats = s.reader.analizar_frecuencia_contactos(mensajes)
                s.reader.mostrar_frecuencia_contactos(stats)
                tl = s.reader.analizar_timeline_horas(mensajes)
                s.reader.mostrar_timeline_horas(tl)
        elif opcion == "8":
            db = _db("whatsapp_decrypted.db")
            kw_raw = self.console.input(
                "[bold cyan][?] Palabras clave (separadas por espacio): [/bold cyan]").strip()
            if not kw_raw:
                return
            keywords = kw_raw.split()
            mensajes, _ = s.reader.leer_whatsapp_mensajes(db)
            encontrados = s.reader.buscar_palabras_clave(mensajes, keywords)
            self.console.print(
                f"[yellow]{len(encontrados)} mensajes con: {keywords}[/yellow]")
            for m in encontrados:
                self.console.print(
                    f"  [{m.fecha_iso}] [bold]{m.contacto}[/bold]: {m.texto}")
        elif opcion == "9":
            db = _db("whatsapp_decrypted.db")
            out_html = os.path.join(ruta_base, "reporte_forense.html")
            mensajes, resumen = s.reader.leer_whatsapp_mensajes(db)
            llamadas = s.reader.leer_llamadas_android(db)
            eliminados = s.reader.leer_mensajes_eliminados(db)
            frecuencia = s.reader.analizar_frecuencia_contactos(
                mensajes) if mensajes else None
            timeline = s.reader.analizar_timeline_horas(
                mensajes) if mensajes else None
            s.reader.exportar_html(out_html, mensajes=mensajes or None, resumen=resumen,
                                   llamadas=llamadas or None, eliminados=eliminados or None,
                                   frecuencia=frecuencia, timeline=timeline)
            s.log.audit(
                f"Reporte HTML generado → {out_html}", "ForensicReader")

    # ── OSINT / Geo ───────────────────────────────────────────────────

    def locate(self):
        s = self.s
        if not self._modulo_ok("locator"):
            return
        ip = Validador.pedir_ip(self.console, "IP objetivo")
        if ip:
            s.locator.rastrear_ip(ip)
            s.log.info(f"Locate en {ip}", "LocatorModule")

    def locate_p(self):
        s = self.s
        if not self._modulo_ok("adv_scanner") or not self._modulo_ok("geopreciose"):
            return
        redes = s.adv_scanner.obtener_redes_formateadas()
        s.geopreciose.triangular_posicion(redes)

    def geofoto(self):
        if not self._modulo_ok("exif"):
            return
        ruta = self.console.input(
            "[bold cyan]Ruta de imagen: [/bold cyan]").strip().replace("'", "").replace('"', "")
        if ruta:
            self.s.exif.analizar_foto(ruta)

    def osint(self):
        if not self._modulo_ok("osint"):
            return
        self.s.osint.menu()

    def cve(self):
        if not self._modulo_ok("cve"):
            return
        self.s.cve.busqueda_libre()

    # ── Ofensivo ──────────────────────────────────────────────────────

    def phishing(self):
        s = self.s
        s._limpiar()
        self.console.print(
            "[bold red][!][/bold red] Iniciando Suite de Phishing...")
        ruta_z = "./tools/zphisher/zphisher.sh"
        if not os.path.exists(ruta_z):
            self.console.print(
                "[red][!] zphisher no encontrado en ./tools/zphisher/[/red]\n"
                "[dim]  git clone https://github.com/htr-tech/zphisher.git tools/zphisher[/dim]"
            )
            return
        try:
            if sys.platform == "win32":
                bash_path = r"C:\Program Files\Git\bin\bash.exe"
                if not os.path.exists(bash_path):
                    self.console.print(
                        "[red][!] Git Bash no encontrado.[/red]")
                    return
                subprocess.run([bash_path, ruta_z], check=True)
            else:
                subprocess.run(["bash", ruta_z], check=True)
        except Exception as e:
            self.console.print(f"[red]Error al lanzar: {e}[/red]")
            s.log.error(f"Phishing: {e}", "PhishingModule")

    def ducky(self):
        if not self._modulo_ok("ducky"):
            return
        with self.s.ducky:
            self.s.ducky.ejecutar_payload()

    def stealth(self):
        if not self._modulo_ok("stealth"):
            return
        self.s.stealth.verificar_identidad()

    def panic(self):
        if not self._modulo_ok("stealth"):
            return
        self.s.stealth.activar_panico()

    # ── Proyectos / Reportes / Jobs / Plugins ─────────────────────────

    def proyecto(self, args: list):
        if not self._modulo_ok("gp"):
            return
        sub = args[0] if args else ""
        acciones = {
            "nuevo":  self.s.gp.crear_proyecto,
            "cargar": self.s.gp.cargar_proyecto,
            "lista":  self.s.gp.listar_proyectos,
            "list":   self.s.gp.listar_proyectos,
            "estado": self.s.gp.mostrar_resumen,
            "cerrar": self.s.gp.cerrar_proyecto,
        }
        accion = acciones.get(sub)
        if accion:
            accion()
        else:
            self.console.print(
                "[dim]Subcomandos: [bold white]nuevo | cargar | lista | estado | cerrar[/bold white][/dim]")

    def reporte(self, args: list):
        if not self._modulo_ok("motor_rep"):
            return
        sub = args[0] if args else ""
        if sub == "resumen":
            self.s.motor_rep.generar_resumen_ejecutivo()
        elif sub == "timeline":
            self.s.motor_rep.generar_timeline()
        else:
            self.s.motor_rep.generar_reporte_completo()

    def jobs(self, args: list):
        if not self._modulo_ok("cola"):
            return
        sub = args[0] if args else ""
        if sub == "resultado" and len(args) > 1:
            self.s.cola.resultado(args[1])
        elif sub == "cancelar" and len(args) > 1:
            self.s.cola.cancelar(args[1])
        elif sub == "limpiar":
            self.s.cola.limpiar_completadas()
        else:
            self.s.cola.listar()

    def plugins(self, args: list):
        s = self.s
        if not self._modulo_ok("plugins"):
            return
        sub = args[0] if args else ""
        if sub == "reload":
            s.plugins.recargar()
        elif sub == "ayuda" and len(args) > 1:
            p = s.plugins._plugins.get(args[1])
            if p:
                self.console.print(Panel(p.ayuda(), border_style="green"))
            else:
                self.console.print(
                    f"[red][!] Plugin '{args[1]}' no encontrado.[/red]")
        else:
            s.plugins.listar()
