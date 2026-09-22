# APEX SENTINEL — Anubis OS

> OS táctico de terminal para trabajo en campo. Sin GUI, sin mouse. Python, hardware RF y un teclado.

[![CI](https://github.com/bernalmariano457-hash/Sentinel-Anubis-os/actions/workflows/ci.yml/badge.svg)](https://github.com/bernalmariano457-hash/Sentinel-Anubis-os/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/bernalmariano457-hash/Sentinel-Anubis-os/branch/main/graph/badge.svg)](https://codecov.io/gh/bernalmariano457-hash/Sentinel-Anubis-os)
[![Python](https://img.shields.io/badge/Python-3.13-blue)](https://python.org)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Platform](https://img.shields.io/badge/Platform-uConsole%20%7C%20Kali%20%7C%20Termux-green)](#instalación)
[![License](https://img.shields.io/badge/License-Modified_MIT-yellow)](LICENSE)

---

```
╔══════════════════════════════════════════════════════════════════╗
║          APEX SENTINEL  v2.3  —  ANUBIS OS                      ║
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
  Flipper Zero      bridge serie  ·  conectado
  Proyectos         sin proyecto activo

  AnubisOS@Sentinel~# (): rfscan
  [*] Escaneando espectro 88–108 MHz...
  ████████████████░░░░  80%  0:00:04

  [SEÑAL] 101.3 MHz  ·  FM Estéreo  ·  –42 dBm
  [SEÑAL] 104.1 MHz  ·  FM Estéreo  ·  –51 dBm
```

---

## ¿Qué es esto?

Una herramienta de seguridad portátil construida para la **ClockworkPi uConsole** — consola clamshell con teclado físico que cabe en una mochila. El objetivo era algo que arrancara rápido, no dependiera de entorno gráfico y tuviera integración real con hardware SDR sin adaptadores.

Anubis OS no es un wrapper de Kali. Es un sistema con su propio ciclo de autenticación, su propia interfaz de terminal construida con Rich, y módulos de dominio independientes que se cargan al arranque según el hardware disponible.

Corre nativamente en la uConsole, en Kali / Debian, y en Termux en Android.

---

## Arquitectura

```
Main.py (ApexSentinel)
├── core/
│   ├── ModuleRegistry       ← carga declarativa de módulos en runtime
│   ├── CommandHandler       ← despacho de comandos por dominio (mixins)
│   ├── auth.py              ← bcrypt · lockout persistente · migración SHA-256
│   ├── Security.py          ← Fernet · rotación de clave · backups fechados
│   ├── GestorProyectos      ← workspaces de operación · evidencias · hallazgos
│   ├── vendor_resolver      ← OUI lookup · caché · API macvendors
│   ├── sentinel_ui          ← componentes Rich reutilizables
│   └── log_sistema          ← logging con niveles · auditoría · rotación
│
├── modules/
│   ├── rf/                  ← RTL-SDR · FFT · waterfall · ADS-B · NOAA · MockSDR
│   ├── network/             ← radar Wi-Fi · ARP scan · sniffer · Evil Twin · Bluetooth · triangulación
│   ├── geo/                 ← GeoPrecise · GeomapSentinel · LocatorModule · KML · GeoJSON
│   ├── forense/             ← EXIF · triaje móvil · stealth · panic · db_extractor
│   ├── osint/               ← CVE lookup · geolocalización · reconocimiento
│   ├── audit/               ← Rubber Ducky HID · credenciales · diccionarios
│   ├── hardware/            ← FlipperModule · flipper_bridge (puente serie Flipper Zero)
│   └── reporte/             ← generación de reportes · exportación · timeline
│
└── plugins/                 ← módulos de terceros · hot-reload
```

El `ModuleRegistry` carga cada módulo con un `ModuleSpec` declarativo. Si el hardware o la librería no están disponibles, el módulo falla silenciosamente y el sistema arranca igualmente — esencial en un dispositivo embebido donde no todo el hardware está siempre presente.

---

## Módulos

### RF / SDR

Motor propio sobre `pyrtlsdr` con `MockSDR` como fallback para desarrollo sin hardware físico.

- Análisis espectral FFT en tiempo real con vista de cascada (waterfall)
- **SpectrumAnalyzer** — analizador de espectro interactivo en tiempo real (`spectrum / sa`)
- Detección automática de señales en 35 bandas de frecuencia conocidas
- Demodulación WFM · NFM · AM · USB · LSB
- Grabación IQ a archivos `.iq` — compatibles con SDR#, GQRX y GNU Radio
- **Decodificación ADS-B** a 1090 MHz con pyModeS — seguimiento de aeronaves en vivo con mensajes extendidos
- **Decodificador NOAA APT** a 137 MHz — imágenes meteorológicas de satélite en tiempo real
- Estadísticas de sesión por banda y tipo de señal

### Red

- Escaneo ARP con resolución OUI de fabricantes (caché + API)
- Escaneo avanzado de puertos TCP con detección de servicios
- Captura de paquetes con filtros BPF
- Radar Wi-Fi por RSSI — mapa de señal en tiempo real
- **Triangulación Wi-Fi** — estimación de posición por RSSI con suavizado adaptativo
- Portal cautivo para auditoría wireless
- **WifiAtack / WADecryptor** — auditoría de redes Wi-Fi

### Bluetooth

- Escaneo BLE en tiempo real con `bleak` — descubrimiento de dispositivos y datos de publicidad
- Monitor continuo con umbral de proximidad (cerca / medio / lejos) por RSSI
- Resolución OUI de fabricantes para direcciones MAC BLE
- **Mapa BLE en tiempo real** — visualización interactiva TUI de dispositivos BLE activos con intensidad de señal, fabricante y coordenadas relativas renderizadas en terminal Rich
- Registro de evidencias por sesión

### Geo

- **GeoPrecise** — geolocalización por triangulación de redes Wi-Fi cercanas (API externa)
- **GeomapSentinel** — generación de mapas HTML interactivos con `folium` coloreados por fabricante
- **LocatorModule** — localización por IP con coordenadas y volcado a evidencias
- **Triangulación híbrida Wi-Fi + BLE** — algoritmo de fusión de señales RSSI Wi-Fi y BLE para estimación de posición física con mayor precisión que cualquiera de las dos fuentes de forma independiente
- **Exportación geo avanzada** — generación automática de evidencias espaciales en KML (Google Earth / Maps) y GeoJSON (estándar abierto) además de los mapas HTML existentes
- Resultados guardados en `data/evidence/geo/`

### Flipper Zero

Integración táctica con Flipper Zero vía puerto serie. El módulo `flipper_bridge` establece el puente de comunicación y expone las capacidades del dispositivo directamente desde la interfaz de Sentinel.

- **Bridge serie** — conexión automática por VID/PID (`0x0483 / 0x5740`) con descubrimiento de puerto y reconexión automática
- **Telemetría del dispositivo** — batería, voltaje, temperatura y estado del almacenamiento externo
- **Escaneo NFC (HF)** — lectura de tarjetas de alta frecuencia con extracción de UID y tipo
- **Lectura RFID (LF 125 kHz)** — lectura de tarjetas de baja frecuencia
- **Captura Sub-GHz** — grabación de señales a archivos `.sub` en el almacenamiento del Flipper
- **Gestión de capturas** — listado y acceso a archivos `.sub` guardados en `/ext/subghz/`
- Integrado en el ciclo de apagado coordinado de Sentinel — desconexión limpia al salir

### Forense

- Extracción de coordenadas GPS de EXIF de imágenes
- Triaje básico y profundo de dispositivos móviles
- Extractor de bases de datos (`db_extractor`) para análisis de archivos SQLite
- Verificación de identidad digital (VPN/proxy/exposición)
- Protocolo de pánico — cifrado de emergencia + purga de historial

### OSINT

- Búsqueda de CVEs por servicio y versión
- Geolocalización por IP con coordenadas
- Reconocimiento pasivo de dominios y servicios

### Proyectos

Workspace de operación que agrupa evidencias, hallazgos por severidad y genera reportes al cierre. Cada proyecto tiene su propio directorio y archivo JSON. El motor de reportes exporta en Markdown, texto plano y timeline.

---

## Instalación

### Auto-detect (recomendado)

```bash
git clone https://github.com/bernalmariano457-hash/Sentinel-Anubis-os.git
cd Sentinel-Anubis-os
chmod +x install.sh && ./install.sh
```

El script detecta la plataforma automáticamente — uConsole, Kali o Termux — e instala únicamente las dependencias disponibles para ese entorno.

### Por plataforma

**Linux / Kali / Debian:**
```bash
pip install -e ".[network,rtlsdr]"
python Main.py
```

**ClockworkPi uConsole:**
```bash
pip install -e ".[uconsole]"   # network + RTL-SDR + ADS-B + NOAA
python Main.py
```

**Android (Termux):**
```bash
pkg install python rtl-sdr
pip install -e ".[termux]" --break-system-packages
python Main.py
```

El primer arranque configura la contraseña maestra. Después va directo a la interfaz.

### Soporte RTL-SDR

```bash
# Linux / uConsole
sudo apt install rtl-sdr librtlsdr-dev

# Termux
pkg install rtl-sdr
```

### Soporte Flipper Zero

El módulo Flipper Zero requiere `pyserial`. Se instala automáticamente con el grupo `hardware`:

```bash
pip install -e ".[hardware]"
```

Conecta el Flipper Zero por USB antes de arrancar Sentinel. El bridge detecta el dispositivo automáticamente por VID/PID. Si hay más de un puerto serie disponible, usa `--port /dev/ttyACM0` al lanzar el comando correspondiente desde la CLI del bridge.

---

## Comandos

### Sistema

| Comando | Descripción |
|---------|-------------|
| `help` / `?` | Menú de ayuda completo |
| `status` | Estado del sistema y módulos cargados |
| `logs` | Historial de eventos de la sesión |
| `hora` | Hora del sistema |
| `files` | Explorar directorio actual |
| `clear` / `cls` | Limpiar pantalla |
| `exit` | Cerrar Sentinel |

### Red

| Comando | Descripción |
|---------|-------------|
| `scan` | Escaneo ARP — hosts activos en la red local |
| `advscan` | Escaneo avanzado con detección de SO |
| `portscan` | Escaneo TCP de puertos de un objetivo |
| `sweep` | Barrido de hosts por rango CIDR |
| `sniff` | Captura de paquetes con filtro BPF |
| `radar` | Radar Wi-Fi por RSSI en tiempo real |
| `audit` | Auditoría de credenciales |
| `vulnscan` | Escaneo de vulnerabilidades |
| `wifi` | Gestión de interfaces wireless |
| `eviltwin` | Portal cautivo para auditoría wireless |
| `wifitri` | Triangulación Wi-Fi por RSSI |
| `btmapa` | Mapa radar BLE en tiempo real (TUI) |

### RF / SDR

| Comando | Descripción |
|---------|-------------|
| `spectrum` / `sa` | Analizador de espectro en tiempo real |
| `rfscan` | Escaneo de frecuencias con detección de señales |
| `rfmenu` | Menú interactivo de opciones RF |
| `rfbarrido` | Barrido espectral por rango personalizado |
| `rfbandas` | Ver 35 bandas de frecuencia conocidas |
| `radio` | Demodular y escuchar en tiempo real (WFM/NFM/AM/SSB) |
| `rfgrabar` | Grabar señal IQ a archivo `.iq` |
| `rfplay` | Reproducir archivo IQ grabado |
| `rfdb` | Base de datos de señales capturadas |
| `rfstats` | Estadísticas de sesión RF |
| `rfstatus` | Estado del hardware SDR |
| `adsb` | Monitor ADS-B — aeronaves en 1090 MHz (pyModeS) |
| `noaa` | NOAA APT — imágenes de satélite meteorológico a 137 MHz |

### Flipper Zero

| Comando | Descripción |
|---------|-------------|
| `flipper` | Menú interactivo del módulo Flipper Zero |
| `flipper-status` | Telemetría del dispositivo: batería, temperatura, almacenamiento |
| `flipper-nfc` | Escaneo NFC de alta frecuencia — extrae UID y tipo de tarjeta |
| `flipper-rfid` | Lectura RFID de baja frecuencia (125 kHz) |
| `flipper-capture` | Captura señal Sub-GHz y la guarda como archivo `.sub` en el Flipper |
| `flipper-list` | Listar archivos `.sub` guardados en `/ext/subghz/` del dispositivo |

### Forense

| Comando | Descripción |
|---------|-------------|
| `geofoto` | Extraer coordenadas GPS de fotos (EXIF) |
| `mobile` | Triaje básico de dispositivo móvil |
| `mobile-deep` | Triaje profundo de dispositivo móvil |
| `view` | Leer archivo forense |
| `stealth` | Verificar identidad digital y exposición de red |
| `panic` | Protocolo de emergencia — cifra todo y sale |
| `recover` | File carving forense (.dd / .img o /dev/sdX) |
| `recover ver <id>` | Tabla de resultados de un job de carving |

### OSINT

| Comando | Descripción |
|---------|-------------|
| `osint` | Reconocimiento pasivo de un objetivo |
| `cve` | Búsqueda de CVEs por servicio / versión |
| `locate` | Geolocalización por IP |
| `locate -p` | Geolocalización de IP pública del operador |
| `geofoto` | Triangulación híbrida Wi-Fi + BLE con exportación geo |

### Proyectos

| Comando | Descripción |
|---------|-------------|
| `proyecto nuevo` | Crear workspace de operación |
| `proyecto cargar` | Cargar proyecto existente |
| `proyecto lista` | Listar todos los proyectos |
| `proyecto estado` | Resumen del proyecto activo |
| `proyecto cerrar` | Cerrar y guardar proyecto |
| `reporte` | Generar reporte del proyecto activo |

### Ofensivo

| Comando | Descripción |
|---------|-------------|
| `phishing` | Suite de phishing (zphisher) |
| `ducky` | Ejecutar payload HID (Rubber Ducky) |

### Sistema de tareas y plugins

| Comando | Descripción |
|---------|-------------|
| `jobs` | Ver cola de tareas asíncronas activas |
| `plugins` | Listar plugins cargados |
| `plugins reload` | Recargar plugins en caliente |

---

## Seguridad

- **bcrypt** con salt autogenerado — migra desde SHA-256 legacy automáticamente al primer login
- **Lockout persistente** — bloqueo por intentos fallidos que sobrevive reinicios
- **Fernet** para cifrado de evidencias con rotación de clave y backups fechados
- **Credenciales separadas** — nunca en `config.json`, siempre en `data/security/`
- **Auditoría completa** — cada acción sensible queda registrada con timestamp y módulo

---

## Hardware objetivo

**ClockworkPi uConsole + RTL-SDR V3**

La uConsole es la razón por la que este proyecto tiene la forma que tiene. Terminal puro, teclado físico, cabe en una mochila. El puerto de expansión acepta el RTL-SDR directamente — sin adaptadores, sin hubs — lo que hace que el módulo RF corra en hardware real sin fricción.

El Flipper Zero complementa el stack de hardware táctica: actúa como extensión de campo para Sub-GHz, NFC, RFID y BadUSB, controlado directamente desde Sentinel vía `flipper_bridge` sobre puerto serie.

Desarrollo actual: Termux en Android con MockSDR para la parte RF y hardware real para todo lo demás.

---

## Desarrollo

```bash
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
```

El CI corre automáticamente en cada push a `main` y en cada PR — lint con ruff, type checking con pyright y tests excluyendo hardware físico.

### Estructura de tests

```
tests/
├── test_auth_security.py     # Auth · bcrypt · lockout · Fernet · rotación de clave
├── test_module_registry.py   # ModuleRegistry · carga · fallback silencioso
└── test_sentinel.py          # Sistema · integración · CommandHandler
```

### Añadir un módulo

Registra un `ModuleSpec` en `core/ModuleRegistry.py`:

```python
ModuleSpec(
    attr="mi_modulo",
    clase="MiClase",
    ruta="modules.dominio.MiModulo",
    display_name="MiModulo",
    opcional=True,        # no bloquea el arranque si falla
)
```

El módulo quedará disponible como `self.mi_modulo` en `ApexSentinel` y en todos los `CommandHandler`.

### Añadir un plugin

Crea un archivo en `plugins/` que herede de `PluginBase`:

```python
from core.PluginSystem import PluginBase

class MiPlugin(PluginBase):
    nombre   = "mi_plugin"
    version  = "1.0"
    comandos = {"micomando": "Descripción del comando"}

    def ejecutar(self, comando: str, args: list[str]) -> None:
        self.console.print(f"[green]Ejecutando {comando}[/green]")
```

Los plugins se cargan en caliente — no hace falta reiniciar Sentinel.

---

## Roadmap

### Completado

- [x] Autenticación bcrypt con migración desde SHA-256 legacy
- [x] Lockout persistente entre sesiones
- [x] Cifrado Fernet con rotación de clave y backups
- [x] ModuleRegistry — carga declarativa con fallback silencioso
- [x] Motor RF: FFT · waterfall · demodulación · ADS-B · MockSDR
- [x] SpectrumAnalyzer — analizador de espectro en tiempo real
- [x] Decodificador NOAA APT — imágenes de satélite a 137 MHz
- [x] Decodificador ADS-B completo con pyModeS
- [x] Módulo Bluetooth — escaneo BLE con bleak · proximidad · evidencias
- [x] Triangulación Wi-Fi — estimación de posición por RSSI
- [x] Módulo Geo — GeoPrecise · GeomapSentinel · mapas HTML con folium
- [x] Sistema de proyectos con evidencias y hallazgos por severidad
- [x] pyproject.toml — dependencias por plataforma (uConsole / Kali / Termux)
- [x] CI/CD con GitHub Actions — lint + types + tests
- [x] Suite de tests — Auth, Security, ModuleRegistry, integración
- [x] Mapa BLE en tiempo real — visualización de dispositivos en terminal Rich TUI
- [x] Triangulación híbrida Wi-Fi + BLE para estimación de posición de alta precisión
- [x] Exportación de mapas geo a formatos KML y GeoJSON
- [x] Integración de puente con Flipper Zero (Flipper Bridge) — NFC · RFID · Sub-GHz · telemetría

### En progreso

- [ ] Arranque nativo en uConsole (reemplazar el login shell)
- [ ] Cobertura de tests al 80%

---

Construido por [@bernalmariano457](https://github.com/bernalmariano457) — feedback bienvenido, especialmente de alguien corriendo Python en hardware embebido.
