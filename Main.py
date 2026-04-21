import os
import sys
import json
import time
import socket
import threading
import requests
import subprocess
import hashlib


# --- COMPATIBILIDAD WINDOWS ---
if sys.platform == 'win32':
    path_proyecto = os.path.abspath(os.path.dirname(__file__))
    os.add_dll_directory(path_proyecto)

# --- LIBRERÍAS DE INTERFAZ ---
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt
from rich.box import DOUBLE_EDGE

# --- IMPORTACIÓN DE MÓDULOS TÁCTICOS ---
from HydraModule import HydraModule
from DictionaryManager import DictionaryManager
from SystemChecker import SystemChecker
from AuditEngine import AuditEngine
from RadarSentinel import RadarSentinel
from GeomapSentinel import GeomapSentinel

# Módulos de Anubis OS
from WifiAtack import WifiAttack
from EvilTwinServer import iniciar_servidor
from RFScanner import RFScanner
from ExifAnalyzer import ExifAnalyzer
from db_extractor import DatabaseExtractor
from ForensicReader import ForensicReader
from MobileSentinel import MobileSentinel
from TacticalSniffer import TacticalSniffer
from GeoPrecise import GeoPrecise
from LocatorModule import LocatorModule
from SweepModule import SweepModule
from AdvancedScanner import AdvancedScanner
from DuckyModule import DuckyModule
from scapy.all import ARP, Ether, srp
from bt_module import BluetoothModule
from Network import NetworkModule
from Security import SecurityModule
from Stealth import StealthModule
from ReportManager import ReportManager
from WADecryptor import WhatsAppDecryptor
from rich.layout import Layout
from rich.table import Table
from PhishingModule import PhishingModule


class ApexSentinel:
    def __init__(self):
        self.console = Console()
        self.config = self.cargar_config()

     # --- NUEVA LÓGICA DE SEGURIDAD ---
        # Verificamos si es la primera vez que se usa el sistema
        self.primer_arranque = self.config["sistema"].get(
            "primer_arranque", True)
        self.password_hash = self.config["sistema"].get("password_hash", None)
        # --------------------------------

        # 1. Motores de Diagnóstico y Auditoría
        self.checker = SystemChecker()
        self.audit_engine = AuditEngine(self)
        self.dict_manager = DictionaryManager()
        self.hydra = HydraModule(self)

        # 2. Módulos de Campo e Inteligencia
        self.locator = LocatorModule(self)
        self.exif = ExifAnalyzer(self)
        self.geopreciose = GeoPrecise(self)
        self.wifi_attack = WifiAttack(self)
        self.reader = ForensicReader(self)
        self.radar = RadarSentinel(interface="Wi-Fi")
        self.radar.start_sniffing()
        self.geomap = GeomapSentinel()
        self.rf = RFScanner(self)
        self.sniffer = TacticalSniffer(self)
        self.bt = BluetoothModule(self)
        self.sweep = SweepModule(self)
        self.ducky = DuckyModule(self)
        self.stealth = StealthModule(self)
        self.adv_scanner = AdvancedScanner(self)
        self.mobile = MobileSentinel(self)
        self.security = SecurityModule(self)
        self.network = NetworkModule(self)
        self.reportes = ReportManager()
        self.phishing = PhishingModule()

        self.nombre = self.config["sistema"]["nombre"]
        self.version = self.config["sistema"]["version"]

    def cargar_config(self):
        try:
            with open("config.json", "r") as f:
                return json.load(f)
        except:
            # Configuración por defecto para el primer inicio
            return {"sistema": {"nombre": "Sentinel", "version": "2.1", "primer_arranque": True}}

    def configurar_primera_vez(self):
        self.limpiar_pantalla()
        self.console.print(Panel(
            "[bold cyan]ANUBIS OS: SETUP DE SEGURIDAD[/bold cyan]\n"
            "[white]No se detectó una clave de operador. Configure su acceso maestro.[/white]",
            border_style="cyan"
        ))

        while True:
            nueva_pass = Prompt.ask(
                "[?] Cree su Contraseña Maestra (mín. 8 caracteres)", password=True)
            if len(nueva_pass) < 8:
                self.console.print(
                    "[red][!] Contraseña demasiado débil.[/red]")
                continue

            confirmar = Prompt.ask("[?] Confirme su Contraseña", password=True)

            if nueva_pass == confirmar:
                # Protegemos la clave con SHA-256
                hash_generado = hashlib.sha256(nueva_pass.encode()).hexdigest()

                # Guardamos en el archivo de configuración
                self.config["sistema"]["password_hash"] = hash_generado
                self.config["sistema"]["primer_arranque"] = False

                with open("config.json", "w") as f:
                    json.dump(self.config, f, indent=4)

                self.password_hash = hash_generado
                self.console.print(
                    "[green][+] Acceso configurado. Iniciando sistema...[/green]")
                time.sleep(2)
                break
            else:
                self.console.print("[red][!] Las claves no coinciden.[/red]")

    def solicitar_acceso(self):
        # Si es la primera vez, obligamos a configurar
        if self.config["sistema"].get("primer_arranque", True):
            self.configurar_primera_vez()
            return True

        self.limpiar_pantalla()
        self.console.print(
            f"[bold white]--- {self.nombre} : LOGIN ---[/bold white]")

        intentos = 3
        while intentos > 0:
            # Usamos Prompt.ask para que la contraseña no se vea al escribirla (password=True)
            entrada = Prompt.ask(
                f"[?] Ingrese clave de acceso ({intentos} intentos)", password=True)

            # Convertimos lo que el usuario escribió a Hash
            hash_entrada = hashlib.sha256(entrada.encode()).hexdigest()

            # Comparamos el Hash nuevo con el Hash guardado en lugar de texto plano
            if hash_entrada == self.password_hash:
                self.animar_barra("DESCIFRANDO NÚCLEO...")
                return True
            else:
                intentos -= 1
                self.console.print(
                    f"[red][!] Clave incorrecta. Quedan {intentos} intentos.[/red]")

        return False

    def limpiar_pantalla(self):
        os.system("cls" if os.name == "nt" else "clear")

    def mostrar_dashboard_exito(self, ip, servicio, credencial):
        tabla = Table(title="🔓 ACCESO OBTENIDO",
                      show_header=True, header_style="bold green")
        tabla.add_column("Objetivo", style="cyan", justify="center")
        tabla.add_column("Protocolo", style="yellow", justify="center")
        tabla.add_column("Credenciales (U:P)",
                         style="bold white", justify="center")
        tabla.add_row(ip, servicio.upper(), credencial)

        self.console.print("\n")
        self.console.print(Panel(
            tabla,
            title="[bold green]MISSION ACCOMPLISHED[/bold green]",
            border_style="bright_green",
            expand=False
        ))
        self.console.print(
            f"[dim]LOG: Resultado exportado a ./data/evidence/audit_{ip}.txt[/dim]\n")

    def animar_barra(self, tarea):
        print(f"\n{tarea}")
        barra_largo = 20
        for i in range(barra_largo + 1):
            porcentaje = int((i / barra_largo) * 100)
            relleno = "█" * i
            espacios = "-" * (barra_largo - i)
            print(f"\r[{relleno}{espacios}] {porcentaje}%", end="")
            time.sleep(0.05)
        print("\n[OK] Tarea completada.\n")

    def mostrar_bootloader(self):
        self.limpiar_pantalla()
        # Aquí es donde se enviaría el bitmap al OLED
        print(" [ DIBUJANDO ANIMACIÓN ANUBIS EN OLED... ] ")
        time.sleep(1)

    def mostrar_banner(self):
        self.limpiar_pantalla()
        banner = fr"""
        \033[1;33m      .---.        \033[1;37mAPEX SENTINEL \033[1;31m[v{self.version}]\033[0m
        \033[1;33m     /     \       \033[1;32mOPERADOR: \033[1;37m{self.nombre}\033[0m
        \033[1;33m    | () () |      \033[1;32mESTADO:   \033[1;37mACTIVE\033[0m
        \033[1;33m     \  ^  /       \033[1;32mIFACE:    \033[1;37m{getattr(self.bt, 'iface', 'wlan0mon')}\033[0m
        \033[1;33m      |||||        \033[1;31mCAUTION:  \033[1;37mAUTHORIZED USE ONLY\033[0m
        \033[0m"""
        print(banner)
        print("-" * 50)

    def obtener_fabricante(self, mac):
        try:
            url = f"https://api.macvendors.com/{mac}"
            respuesta = requests.get(url, timeout=1)
            return respuesta.text if respuesta.status_code == 200 else "Desconocido"
        except:
            return "Error"

    def comando_scan_red(self):
        rango = input(f"\n{self.nombre} [NETWORK RANGE] > ")
        if not rango.strip():
            return
        self.animar_barra(f"ESCANEANDO HOSTS EN {rango}...")
        try:
            arp = ARP(pdst=rango)
            ether = Ether(dst="ff:ff:ff:ff:ff:ff")
            resultado = srp(ether/arp, timeout=3, verbose=False)[0]
            print(f"\n{'IP':<15} | {'MAC':<18} | {'FABRICANTE'}")
            print("-" * 60)
            for env, reci in resultado:
                fabricante = self.obtener_fabricante(reci.hwsrc)
                print(f"{reci.psrc:<15} | {reci.hwsrc:<18} | {fabricante}")
        except:
            print("[!] Error de permisos. Ejecute como administrador/root.")

    def mostrar_ayuda(self):
        table = Table(
            title=f"   ANUBIS OS - COMMAND INDEX (v{self.version})   ",
            style="bold cyan",
            box=DOUBLE_EDGE,
            header_style="bold magenta"
        )
        table.add_column("Categoría", style="magenta")
        table.add_column("Comando", style="green")
        table.add_column("Descripción", style="white")

        table.add_row("SISTEMA", "status", "Estado de módulos y hardware")
        table.add_row("", "clear", "Limpia la terminal y recarga banner")
        table.add_row("", "logs", "Historial de operaciones")
        table.add_row("", "files", "Explorador de archivos local")
        table.add_row("", "exit", "Cierre seguro del Sentinel")
        table.add_section()

        table.add_row("NETWORK", "scan", "Escaneo rápido")
        table.add_row("", "netscan", "Mapeo detallado ARP de red local")
        table.add_row("", "advscan", "Escaneo de objetivo específico")
        table.add_row("", "portscan", "Auditoría de puertos abiertos")
        table.add_row("", "sweep", "Escaneo de perímetro")
        table.add_row("", "sniff", "Captura de tráfico real")
        table.add_row(
            "radar", "Inicia el Radar de Intercepción Wi-Fi (Proximidad RSSI)")
        table.add_section()

        table.add_row("AUDIT ACTIVAS", "audit", "Ataque fuerza bruta (Hydra)")
        table.add_row("", "vulnscan", "Escaneo de fallas (Nmap NSE)")
        table.add_row("", "sqlcheck", "Auditoría SQL Injection (SQLmap)")
        table.add_row("", "msf", "Consola Metasploit RPC")
        table.add_section()

        table.add_row("WIRELESS & RF", "wifi", "Ataques Beacon Spam / Deauth")
        table.add_row("", "eviltwin", "Lanzar Gemelo Malvado")
        table.add_row("", "rfscan", "Escaneo de radiofrecuencia")
        table.add_row("", "btjumper", "Salto de dispositivos Bluetooth")
        table.add_section()

        table.add_row("FORENSICS", "mobile", "Triaje Android/iOS y Screenshot")
        table.add_row("", "mobile-deep", "Extracción profunda (WA/Chrome)")
        table.add_row("", "view", "Visualizador táctico de DBs")
        table.add_section()

        table.add_row("INTEL & STEALTH", "locate", "Rastreo IP / GPS")
        table.add_row("", "locate -p", "Triangulación por redes")
        table.add_row("", "geofoto", "Metadatos GPS en fotos (EXIF)")
        table.add_row("", "ducky", "Ejecutar payload BadUSB")
        table.add_row("", "stealth", "Verificar huella digital")
        table.add_row(
            "", "panic", "[bold red]Cifrado y borrado de rastro[/bold red]")

        self.console.print("\n", table, "\n")

    def ejecutar(self):
        if not self.solicitar_acceso():
            return

        self.mostrar_bootloader()

        # CHEQUEO DE SALUD ANTES DE INICIAR
        self.console.print(
            "[bold blue][*] Diagnosticando dependencias...[/bold blue]")
        self.checker.verificar_dependencias()

        self.reportes.verificar_y_limpiar()
        self.mostrar_banner()
        self.stealth.verificar_identidad()

        while True:
            comando = input(f"AnubisOS@Sentinel:~# ").strip().lower()
            if not comando:
                continue

            if comando == "help" or comando == "?":
                self.mostrar_ayuda()

            # --- SISTEMA ---
            elif comando == "status":
                print(
                    f"Sistema: {self.nombre} | Versión: {self.version} | Estado: Operacional")

            elif comando == "hora":
                print(f"Hora actual: {time.strftime('%H:%M:%S')}")

            elif comando == "clear" or comando == "cls":
                self.mostrar_banner()

            elif comando == "logs":
                self.reportes.mostrar_historial()

            elif comando == "files":
                self.animar_barra("EXPLORANDO DIRECTORIO LOCAL...")
                archivos = os.listdir(".")
                for f in archivos:
                    tamano = os.path.getsize(f)
                    print(f"> {f} ({tamano} bytes)")

            elif comando == "exit":
                print("[!] Desconectando Sentinel...")
                break

            elif comando == "advscan":
                target_ip = input("[?] IP del objetivo: ")
                self.adv_scanner.escanear_objetivo(target_ip)
            elif comando == "radar":
                self.limpiar_pantalla()
                self.geomap.abrir_mapa()
                try:
                    while True:
                        panel_radar = self.radar.render_radar()
                        self.geomap.generar_mapa(self.radar.targets)
                        self.limpiar_pantalla()
                        self.console.print(panel_radar)
                        time.sleep(2)
                except KeyboardInterrupt:
                    self.console.print("\n[yellow][!] Deteniendo...[/yellow]")
            elif comando == "portscan":
                objetivo = input(f"\n{self.nombre} [TARGET IP] > ")
                self.animar_barra(f"AUDITANDO PUERTOS EN {objetivo}...")
                puertos = [21, 22, 23, 80, 443, 445, 3306]
                for p in puertos:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.5)
                    resultado = sock.connect_ex((objetivo, p))
                    if resultado == 0:
                        print(f" [+] Puerto {p}: ABIERTO")
                    sock.close()

            elif comando == "sweep":
                rango = input("Rango IP (ej. 192.168.1.0/24): ")
                if not rango:
                    rango = "192.168.1.0/24"
                self.sweep.escanear_perimetro(rango)

            elif comando == "sniff":
                filtro = input("  [?] Filtro: ")
                tiempo = int(input("  [?] Segundos: ") or 30)
                self.sniffer.iniciar_captura(filtro=filtro, duracion=tiempo)

            # --- AUDITORÍA Y VULN ---
            elif comando == "audit":
                self.console.print(
                    "\n[bold magenta]⚔️ MÓDULO HYDRA INICIADO[/bold magenta]")
                target = Prompt.ask("[?] IP del objetivo")
                servicio = Prompt.ask("[?] Servicio", choices=[
                                      "ssh", "ftp", "mysql", "http-get", "telnet"], default="ssh")
                diccionario = self.dict_manager.obtener_ruta_diccionario(
                    servicio)

                if Prompt.ask(f"¿Iniciar ataque con {diccionario}?", choices=["s", "n"], default="n") == "s":
                    resultado = self.hydra.ejecutar_ataque(
                        target, servicio, "root", diccionario)
                    if resultado:
                        self.mostrar_dashboard_exito(
                            target, servicio, resultado)

            elif comando == "vulnscan":
                target = input(" [?] IP a analizar: ")
                resultado = self.audit_engine.escaneo_vulnerabilidades(target)
                self.console.print(
                    Panel(resultado, title="RESULTADOS DE VULNERABILIDAD", border_style="red"))

            elif comando == "sqlcheck":
                url = input(" [?] URL Objetivo: ")
                resultado = self.audit_engine.auditoria_sql(url)
                self.console.print(
                    Panel(resultado, title="INFORME SQLMAP", border_style="yellow"))

            # --- WIRELESS Y RADIOFRECUENCIA ---
            elif comando == "wifi":
                print("\n1. Beacon Spam | 2. Deauth Attack")
                opt = input(" > ")
                if opt == "1":
                    prefijo = input("Prefijo SSID: ")
                    self.bt.beacon_spam(prefijo)
                elif opt == "2":
                    mac_vic = input("MAC Víctima: ")
                    mac_ap = input("MAC AP: ")
                    self.bt.deauth(mac_vic, mac_ap)

            elif comando == "eviltwin":
                ssid = input(" [?] SSID: ")
                self.wifi_attack.crear_gemelo_malvado(ssid, 6)
                threading.Thread(target=iniciar_servidor, daemon=True).start()
                input("[!] Presiona Enter para detener...")
                self.wifi_attack.detener_ataques()

            elif comando == "rfscan":
                freq = float(input(" [?] Frecuencia (MHz): "))
                self.rf.escanear_frecuencia(freq)

            elif comando == "btjumper":
                self.bt.iniciar_jumper()

            # --- INGENIERÍA SOCIAL ---
            elif comando == "phishing":
                self.limpiar_pantalla()
                self.console.print(
                    "[bold red][!][/bold red] Iniciando Suite de Phishing...")

                # Ruta completa hacia el script
                ruta_z = "./tools/zphisher/zphisher.sh"
                bash_path = r"C:\Program Files\Git\bin\bash.exe"

                try:
                    # Agregamos shell=True para ayudar a Windows a encontrar a Bash
                    subprocess.run([bash_path, ruta_z], check=True)
                except Exception as e:
                    self.console.print(f"[red]Error al lanzar: {e}[/red]")
            # --- FORENSE ---
            elif comando == "mobile":
                print("\n[1] Android Triage | [2] iOS Info | [3] Screenshot Remoto")
                opt = input("> ")
                if opt == "1":
                    self.mobile.triage_android()
                elif opt == "2":
                    self.mobile.triage_ios()
                elif opt == "3":
                    path = self.mobile.preparar_directorio("Android_Screen")
                    print("[*] Tomando captura...")
                    subprocess.run(
                        ["adb", "shell", "screencap", "-p", "/sdcard/s.png"])
                    subprocess.run(
                        ["adb", "pull", "/sdcard/s.png", f"{path}/s.png"])
                    print(f"[+] Captura guardada en {path}/s.png")

            elif comando == "mobile-deep":
                path = "./data/evidence/mobile/Deep_Extraction/"
                if not os.path.exists(path):
                    os.makedirs(path)
                extractor = DatabaseExtractor()
                decryptor = WhatsAppDecryptor()
                print("\n[1] Extraer WhatsApp Full | [2] Extraer Chrome History")
                opt = input("> ")
                if opt == "1":
                    self.animar_barra("EXTRAYENDO DB Y LLAVE...")
                    extractor.extraer_whatsapp(path)
                    extractor.extraer_whatsapp_key(path)
                elif opt == "2":
                    self.animar_barra("EXTRAYENDO HISTORIAL CHROME...")
                    # Lógica de Chrome extractor

            elif comando == "view":
                opcion = input(" [1] Leer WhatsApp | [2] Leer Chrome: ")
                ruta_base = "./data/evidence/mobile/Deep_Extraction/"
                if opcion == "1":
                    self.reader.leer_whatsapp_mensajes(
                        os.path.join(ruta_base, "whatsapp_messages.db"))
                elif opcion == "2":
                    self.reader.leer_historial_chrome(
                        os.path.join(ruta_base, "chrome_history.db"))

            # --- INTELIGENCIA, EXPLOIT Y STEALTH ---
            elif comando == "locate":
                ip_target = input("IP: ")
                self.locator.rastrear_ip(ip_target)

            elif comando == "locate -p":
                redes = self.adv_scanner.obtener_redes_formateadas()
                self.geopreciose.triangular_posicion(redes)

            elif comando == "geofoto":
                ruta = input("Ruta de imagen: ").strip().replace(
                    "'", "").replace('"', '')
                self.exif.analizar_foto(ruta)

            elif comando == "ducky":
                self.ducky.ejecutar_payload()

            elif comando == "stealth":
                self.stealth.verificar_identidad()

            elif comando == "panic":
                self.stealth.activar_panico()

            else:
                print(
                    f"[-] Comando '{comando}' no reconocido. Escribe 'help' para ver la lista de comandos.")


if __name__ == "__main__":
    app = ApexSentinel()
    app.ejecutar()
