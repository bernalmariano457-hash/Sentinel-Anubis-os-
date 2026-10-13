APEX SENTINEL — Anubis OS
OS táctico de terminal para trabajo en campo. Sin GUI, sin mouse. Python, hardware RF y un teclado.

https://github.com/bernalmariano457-hash/Sentinel-Anubis-os/actions/workflows/ci.yml/badge.svg
https://codecov.io/gh/bernalmariano457-hash/Sentinel-Anubis-os/branch/main/graph/badge.svg
https://img.shields.io/badge/Python-3.13-blue
https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json
https://img.shields.io/badge/Platform-uConsole%20%7C%20Kali%20%7C%20Termux-green
https://img.shields.io/badge/License-MIT-yellow

text
╔══════════════════════════════════════════════════════════════════╗
║          APEX SENTINEL  v2.3  —  ANUBIS OS                       ║
║          Sistema Operativo Táctico  ·  uConsole Edition          ║
╚══════════════════════════════════════════════════════════════════╝

  AnubisOS@Sentinel~# (): status

  MÓDULOS           ESTADO
  ──────────────────────────────────────────
  RF / SDR          RTL-SDR V3  ·  1246 MHz
  Network           wlan0mon  ·  activo
  Bluetooth         BLE  ·  disponible
  Geo               GeoPrecise  ·  disponible
  Forense           disponible
  OSINT             disponible
  Proyectos         sin proyecto activo
  Power             SoC 45°C  ·  Bat 78%  ·  Duty 100%

  AnubisOS@Sentinel~# (): rfscan
  [*] Escaneando espectro 88–108 MHz...
  ████████████████░░░░  80%  0:00:04

  [SEÑAL] 101.3 MHz  ·  FM Estéreo  ·  –42 dBm
  [SEÑAL] 104.1 MHz  ·  FM Estéreo  ·  –51 dBm
¿Qué es esto?
Una herramienta de seguridad portátil construida para la ClockworkPi uConsole — consola clamshell con teclado físico que cabe en una mochila. El objetivo era algo que arrancara rápido, no dependiera de entorno gráfico y tuviera integración real con hardware SDR sin adaptadores.

Anubis OS no es un wrapper de Kali. Es un sistema con su propio ciclo de autenticación, su propia interfaz de terminal construida con Rich, y módulos de dominio independientes que se cargan al arranque según el hardware disponible.

Corre nativamente en la uConsole, en Kali / Debian, y en Termux en Android.

Arquitectura
text
Main.py (ApexSentinel)
├── core/
│   ├── ModuleRegistry       ← carga declarativa de módulos en runtime
│   ├── CommandHandler       ← despacho de comandos por dominio (mixins)
│   ├── auth.py              ← bcrypt · lockout persistente · migración SHA-256
│   ├── Security.py          ← Fernet · rotación de clave · backups fechados
│   ├── GestorProyectos      ← workspaces de operación · evidencias · hallazgos
│   ├── vendor_resolver      ← OUI lookup · caché · API macvendors
│   ├── sentinel_ui          ← componentes Rich reutilizables
│   ├── log_sistema          ← logging con niveles · auditoría · rotación
│   ├── sdr_broker.py        ← broker de acceso único al SDR · time-slicing ponderado
│   └── power_manager.py     ← gestión térmica · batería · throttling · periféricos
│
├── modules/
│   ├── rf/                  ← RTL-SDR · FFT · waterfall · ADS-B · NOAA · MockSDR
│   ├── network/             ← radar Wi-Fi · ARP scan · sniffer · Evil Twin · Bluetooth · triangulación
│   ├── geo/                 ← GeoPrecise · GeomapSentinel · LocatorModule · KML · GeoJSON
│   ├── forense/             ← EXIF · triaje móvil · stealth · panic · db_extractor
│   ├── osint/               ← CVE lookup · geolocalización · reconocimiento
│   ├── audit/               ← Rubber Ducky HID · credenciales · diccionarios
│   └── reporte/             ← generación de reportes · exportación · timeline
│
└── plugins/                 ← módulos de terceros · hot-reload
El ModuleRegistry carga cada módulo con un ModuleSpec declarativo. Si el hardware o la librería no están disponibles, el módulo falla silenciosamente y el sistema arranca igualmente — esencial en un dispositivo embebido donde no todo el hardware está siempre presente.

Broker SDR
El SDR físico solo puede estar sintonizado a una configuración a la vez. SDRBroker centraliza el acceso al hardware en una única instancia y hace time-slicing ponderado entre suscriptores:

Cada consumidor (SpectrumAnalyzer, RFScanner, NOAADecoder, ADS-B) se suscribe con su propia configuración y recibe bloques IQ.

Reparto por prioridad y dwellMs — el suscriptor con menor tiempo virtual acumulado gana el turno.

Cuando nadie lo usa durante idleSleepMs, el SDR pasa a modo sleep().

Todos los módulos RF comparten el mismo proceso dueño del hardware: nunca colisionan.

Gestión de energía
PowerManager monitorea la temperatura del SoC con histéresis y el estado de batería, y publica un dutyCycle() que el broker respeta:

Estado térmico	Duty cycle
Normal (<60 °C)	100 %
Warm (≥60 °C)	70 %
Hot (≥70 °C)	35 %
Critical (≥80 °C)	0 % (duerme periféricos)
Si la temperatura llega a crítico, el broker reduce automáticamente la carga del SDR. Todo configurable vía PowerConfig.

Módulos
RF / SDR
Motor propio sobre pyrtlsdr con MockSDR como fallback para desarrollo sin hardware físico. El acceso al hardware pasa por SDRBroker.

Análisis espectral FFT en tiempo real con vista de cascada (waterfall)

SpectrumAnalyzer — analizador de espectro interactivo en tiempo real (spectrum / sa)

Detección automática de señales en 35 bandas de frecuencia conocidas

Demodulación WFM · NFM · AM · USB · LSB

Grabación IQ a archivos .iq — compatibles con SDR#, GQRX y GNU Radio

Decodificación ADS-B a 1090 MHz con pyModeS — seguimiento de aeronaves en vivo con mensajes extendidos

Decodificador NOAA APT a 137 MHz — imágenes meteorológicas de satélite en tiempo real

Estadísticas de sesión por banda y tipo de señal

Red
Escaneo ARP con resolución OUI de fabricantes (caché + API)

Escaneo avanzado de puertos TCP con detección de servicios

Captura de paquetes con filtros BPF

Radar Wi-Fi por RSSI — mapa de señal en tiempo real

Triangulación Wi-Fi — estimación de posición por RSSI con suavizado adaptativo

Portal cautivo para auditoría wireless

WifiAtack / WADecryptor — auditoría de redes Wi-Fi

Bluetooth
Escaneo BLE en tiempo real con bleak — descubrimiento de dispositivos y datos de publicidad

Monitor continuo con umbral de proximidad (cerca / medio / lejos) por RSSI

Resolución OUI de fabricantes para direcciones MAC BLE

Mapa BLE en tiempo real — visualización interactiva TUI de dispositivos BLE activos con intensidad de señal, fabricante y coordenadas relativas renderizadas en terminal Rich

Registro de evidencias por sesión

Geo
GeoPrecise — geolocalización por triangulación de redes Wi-Fi cercanas (API externa)

GeomapSentinel — generación de mapas HTML interactivos con folium coloreados por fabricante

LocatorModule — localización por IP con coordenadas y volcado a evidencias

Triangulación híbrida Wi-Fi + BLE — algoritmo de fusión de señales RSSI Wi-Fi y BLE para estimación de posición física con mayor precisión que cualquiera de las dos fuentes de forma independiente

Exportación geo avanzada — generación automática de evidencias espaciales en KML (Google Earth / Maps) y GeoJSON (estándar abierto) además de los mapas HTML existentes

Resultados guardados en data/evidence/geo/

Forense
Extracción de coordenadas GPS de EXIF de imágenes

Triaje básico y profundo de dispositivos móviles

Extractor de bases de datos (db_extractor) para análisis de archivos SQLite

Verificación de identidad digital (VPN/proxy/exposición)

Protocolo de pánico — cifrado de emergencia + purga de historial

OSINT
Búsqueda de CVEs por servicio y versión

Geolocalización por IP con coordenadas

Reconocimiento pasivo de dominios y servicios

Proyectos
Workspace de operación que agrupa evidencias, hallazgos por severidad y genera reportes al cierre. Cada proyecto tiene su propio directorio y archivo JSON. El motor de reportes exporta en Markdown, texto plano y timeline.

Energía
Monitoreo térmico del SoC con histéresis configurable

Nivel y estado de batería (compatible con M5PM1 en modelos que lo soportan)

Throttling automático del SDR según temperatura

Dormir/despertar periféricos registrados en estado crítico

Comandos directos: power, temp, bat, throttle

Instalación
Auto-detect (recomendado)
bash
git clone https://github.com/bernalmariano457-hash/Sentinel-Anubis-os.git
cd Sentinel-Anubis-os
chmod +x install.sh && ./install.sh
El script detecta la plataforma automáticamente — uConsole, Kali o Termux — e instala únicamente las dependencias disponibles para ese entorno.

Por plataforma
Linux / Kali / Debian:

bash
pip install -e ".[network,rtlsdr]"
python Main.py
ClockworkPi uConsole:

bash
pip install -e ".[uconsole]"   # network + RTL-SDR + ADS-B + NOAA
python Main.py
Android (Termux):

bash
pkg install python rtl-sdr
pip install -e ".[termux]" --break-system-packages
python Main.py
El primer arranque configura la contraseña maestra. Después va directo a la interfaz.

Soporte RTL-SDR
bash
# Linux / uConsole
sudo apt install rtl-sdr librtlsdr-dev

# Termux
pkg install rtl-sdr
Arranque automático (systemd)
El servicio systemd arranca Sentinel en modo no-interactivo. Para evitar bloqueos en el prompt de contraseña:

bash
export SENTINEL_AUTH_MODE=systemd
Con la contraseña configurada previamente, el arranque es desatendido. Si no hay credencial, el sistema deniega el arranque y lo registra en el log sin quedarse colgado.

Comandos
Sistema
Comando	Descripción
help / ?	Menú de ayuda completo
status	Estado del sistema y módulos cargados
logs	Historial de eventos de la sesión
hora	Hora del sistema
files	Explorar directorio actual
clear / cls	Limpiar pantalla
exit	Cerrar Sentinel
Energía
Comando	Descripción
power	Estado de energía: temperatura, batería, throttling, SDR
temp	Temperatura actual del SoC
bat	Nivel de batería
throttle on	Forzar throttling térmico
throttle off	Liberar throttling
throttle auto	Restaurar throttling automático
Red
Comando	Descripción
scan	Escaneo ARP — hosts activos en la red local
advscan	Escaneo avanzado con detección de SO
portscan	Escaneo TCP de puertos de un objetivo
sweep	Barrido de hosts por rango CIDR
sniff	Captura de paquetes con filtro BPF
radar	Radar Wi-Fi por RSSI en tiempo real
audit	Auditoría de credenciales
vulnscan	Escaneo de vulnerabilidades
wifi	Gestión de interfaces wireless
eviltwin	Portal cautivo para auditoría wireless
wifitri	Triangulación Wi-Fi por RSSI
btmapa	Mapa radar BLE en tiempo real (TUI)
RF / SDR
Comando	Descripción
spectrum / sa	Analizador de espectro en tiempo real
rfscan	Escaneo de frecuencias con detección de señales
rfmenu	Menú interactivo de opciones RF
rfbarrido	Barrido espectral por rango personalizado
rfbandas	Ver 35 bandas de frecuencia conocidas
radio	Demodular y escuchar en tiempo real (WFM/NFM/AM/SSB)
rfgrabar	Grabar señal IQ a archivo .iq
rfplay	Reproducir archivo IQ grabado
rfdb	Base de datos de señales capturadas
rfstats	Estadísticas de sesión RF
rfstatus	Estado del hardware SDR
adsb	Monitor ADS-B — aeronaves en 1090 MHz (pyModeS)
noaa	NOAA APT — imágenes de satélite meteorológico a 137 MHz
Forense
Comando	Descripción
geofoto	Extraer coordenadas GPS de fotos (EXIF)
mobile	Triaje básico de dispositivo móvil
mobile-deep	Triaje profundo de dispositivo móvil
view	Leer archivo forense
stealth	Verificar identidad digital y exposición de red
panic	Protocolo de emergencia — cifra todo y sale
recover	File carving forense (.dd / .img o /dev/sdX)
recover ver <id>	Tabla de resultados de un job de carving
OSINT
Comando	Descripción
osint	Reconocimiento pasivo de un objetivo
cve	Búsqueda de CVEs por servicio / versión
locate	Geolocalización por IP
locate -p	Geolocalización de IP pública del operador
geofoto	Triangulación híbrida Wi-Fi + BLE con exportación geo
Proyectos
Comando	Descripción
proyecto nuevo	Crear workspace de operación
proyecto cargar	Cargar proyecto existente
proyecto lista	Listar todos los proyectos
proyecto estado	Resumen del proyecto activo
proyecto cerrar	Cerrar y guardar proyecto
reporte	Generar reporte del proyecto activo
Ofensivo
Comando	Descripción
phishing	Suite de phishing (zphisher)
ducky	Ejecutar payload HID (Rubber Ducky)
Sistema de tareas y plugins
Comando	Descripción
jobs	Ver cola de tareas asíncronas activas
plugins	Listar plugins cargados
plugins reload	Recargar plugins en caliente
Seguridad
bcrypt con salt autogenerado — migra desde SHA-256 legacy automáticamente al primer login

Lockout persistente — bloqueo por intentos fallidos que sobrevive reinicios

Fernet para cifrado de evidencias con rotación de clave y backups fechados

Credenciales separadas — nunca en config.json, siempre en data/security/

Auditoría completa — cada acción sensible queda registrada con timestamp y módulo

Modo systemd — autenticación no-interactiva para arranque desatendido

Hardware objetivo
ClockworkPi uConsole + RTL-SDR V3

La uConsole es la razón por la que este proyecto tiene la forma que tiene. Terminal puro, teclado físico, cabe en una mochila. El puerto de expansión acepta el RTL-SDR directamente — sin adaptadores, sin hubs — lo que hace que el módulo RF corra en hardware real sin fricción.

Desarrollo actual: Termux en Android con MockSDR para la parte RF y hardware real para todo lo demás.

Desarrollo
bash
# Setup completo para desarrollo
git clone https://github.com/bernalmariano457-hash/Sentinel-Anubis-os.git
cd Sentinel-Anubis-os
pip install -e ".[all]"

# Comandos disponibles
make test          # tests sin hardware
make check         # lint + tipos + tests — idéntico al CI
make format        # corrige y formatea con ruff
make test-hardware # requiere RTL-SDR conectado
make run           # arrancar Sentinel
El CI corre automáticamente en cada push a main y en cada PR — lint con ruff, type checking con pyright y tests excluyendo hardware físico.

Estructura de tests
text
tests/
├── test_auth_security.py     # Auth · bcrypt · lockout · Fernet · rotación de clave
├── test_module_registry.py   # ModuleRegistry · carga · fallback silencioso
└── test_sentinel.py          # Sistema · integración · CommandHandler
Añadir un módulo
Registra un ModuleSpec en core/ModuleRegistry.py:

python
ModuleSpec(
    attr="mi_modulo",
    clase="MiClase",
    ruta="modules.dominio.MiModulo",
    display_name="MiModulo",
    opcional=True,        # no bloquea el arranque si falla
)
El módulo quedará disponible como self.mi_modulo en ApexSentinel y en todos los CommandHandler.

Añadir un plugin
Crea un archivo en plugins/ que herede de PluginBase:

python
from core.PluginSystem import PluginBase

class MiPlugin(PluginBase):
    nombre   = "mi_plugin"
    version  = "1.0"
    comandos = {"micomando": "Descripción del comando"}

    def ejecutar(self, comando: str, args: list[str]) -> None:
        self.console.print(f"[green]Ejecutando {comando}[/green]")
Los plugins se cargan en caliente — no hace falta reiniciar Sentinel.

Roadmap
Completado
☑ Autenticación bcrypt con migración desde SHA-256 legacy
☑ Lockout persistente entre sesiones
☑ Cifrado Fernet con rotación de clave y backups
☑ ModuleRegistry — carga declarativa con fallback silencioso
☑ Motor RF: FFT · waterfall · demodulación · ADS-B · MockSDR
☑ SpectrumAnalyzer — analizador de espectro en tiempo real
☑ Decodificador NOAA APT — imágenes de satélite a 137 MHz
☑ Decodificador ADS-B completo con pyModeS
☑ Módulo Bluetooth — escaneo BLE con bleak · proximidad · evidencias
☑ Triangulación Wi-Fi — estimación de posición por RSSI
☑ Módulo Geo — GeoPrecise · GeomapSentinel · mapas HTML con folium
☑ Sistema de proyectos con evidencias y hallazgos por severidad
☑ pyproject.toml — dependencias por plataforma (uConsole / Kali / Termux)
☑ CI/CD con GitHub Actions — lint + types + tests
☑ Suite de tests — Auth, Security, ModuleRegistry, integración
☑ Mapa BLE en tiempo real — visualización de dispositivos en terminal Rich TUI
☑ Triangulación híbrida Wi-Fi + BLE para estimación de posición de alta precisión
☑ Exportación de mapas geo a formatos KML y GeoJSON
☑ SDRBroker — broker de acceso único al SDR con time-slicing ponderado
☑ PowerManager — gestión térmica, batería y throttling automático del SDR
En progreso
□ Arranque nativo en uConsole (reemplazar el login shell)
□ Cobertura de tests al 80%
Construido por @bernalmariano457-hash — feedback bienvenido, especialmente de alguien corriendo Python en hardware embebido.
