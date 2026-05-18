# APEX SENTINEL — Anubis OS

> OS táctico de terminal para trabajo en campo. Sin GUI, sin mouse. Python, hardware RF y un teclado.

[![CI](https://github.com/bernalmariano457-hash/Sentinel-Anubis-os/actions/workflows/ci.yml/badge.svg)](https://github.com/bernalmariano457-hash/Sentinel-Anubis-os/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/bernalmariano457-hash/Sentinel-Anubis-os/branch/main/graph/badge.svg)](https://codecov.io/gh/bernalmariano457-hash/Sentinel-Anubis-os)
[![Python](https://img.shields.io/badge/Python-3.13-blue)](https://python.org)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Platform](https://img.shields.io/badge/Platform-uConsole%20%7C%20Kali%20%7C%20Termux-green)](#instalación)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

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
  Forense           disponible
  OSINT             disponible
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
│   ├── rf/                  ← RTL-SDR · FFT · waterfall · ADS-B · MockSDR
│   ├── network/             ← radar Wi-Fi · ARP scan · sniffer · Evil Twin
│   ├── forense/             ← EXIF · triaje móvil · stealth · panic
│   ├── osint/               ← CVE lookup · geolocalización · reconocimiento
│   ├── audit/               ← Rubber Ducky HID · credenciales
│   └── reporte/             ← generación de reportes · exportación
│
└── plugins/                 ← módulos de terceros · hot-reload
```

El `ModuleRegistry` carga cada módulo con un `ModuleSpec` declarativo. Si el hardware o la librería no están disponibles, el módulo falla silenciosamente y el sistema arranca igualmente — esencial en un dispositivo embebido donde no todo el hardware está siempre presente.

---

## Módulos

### RF / SDR

El módulo más completo del proyecto. Motor propio sobre `pyrtlsdr` con `MockSDR` como fallback para desarrollo sin hardware físico.

- Análisis espectral FFT en tiempo real con vista de cascada (waterfall)
- Detección automática de señales en 35 bandas de frecuencia conocidas
- Demodulación WFM · NFM · AM · USB · LSB
- Grabación IQ a archivos `.iq` — compatibles con SDR#, GQRX y GNU Radio
- Decodificación ADS-B a 1090 MHz — seguimiento de aeronaves en vivo
- Estadísticas de sesión por banda y tipo de señal

### Red

- Escaneo ARP con resolución OUI de fabricantes (caché + API)
- Escaneo avanzado de puertos TCP con detección de servicios
- Captura de paquetes con filtros BPF
- Radar Wi-Fi por RSSI — mapa de señal en tiempo real
- Portal cautivo para auditoría wireless

### Forense

- Extracción de coordenadas GPS de EXIF de imágenes
- Triaje básico de dispositivos móviles
- Verificación de identidad digital (VPN/proxy/exposición)
- Protocolo de pánico — cifrado de emergencia + purga de historial

### OSINT

- Búsqueda de CVEs por servicio y versión
- Geolocalización por IP con coordenadas
- Reconocimiento pasivo de dominios y servicios

### Proyectos

Workspace de operación que agrupa evidencias, hallazgos por severidad y genera reportes al cierre. Cada proyecto tiene su propio directorio y archivo JSON.

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
pip install -e ".[uconsole]"   # network + RTL-SDR + ADS-B
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

---

## Comandos

### Sistema

| Comando | Descripción |
|---------|-------------|
| `help` / `?` | Menú de ayuda completo |
| `status` | Estado del sistema y módulos cargados |
| `logs` | Historial de eventos de la sesión |
| `hora` | Hora del sistema |
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

### RF / SDR

| Comando | Descripción |
|---------|-------------|
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
| `adsb` | Monitor ADS-B — aeronaves en 1090 MHz |

### Forense

| Comando | Descripción |
|---------|-------------|
| `geofoto` | Extraer coordenadas GPS de fotos (EXIF) |
| `mobile` | Triaje básico de dispositivo móvil |
| `mobile-deep` | Triaje profundo de dispositivo móvil |
| `view` | Leer archivo forense |
| `stealth` | Verificar identidad digital y exposición de red |
| `panic` | Protocolo de emergencia — cifra todo y sale |

### OSINT

| Comando | Descripción |
|---------|-------------|
| `osint` | Reconocimiento pasivo de un objetivo |
| `cve` | Búsqueda de CVEs por servicio / versión |
| `locate` | Geolocalización por IP |
| `locate -p` | Geolocalización de IP pública del operador |

### Proyectos

| Comando | Descripción |
|---------|-------------|
| `proyecto nuevo` | Crear workspace de operación |
| `proyecto abrir` | Cargar proyecto existente |
| `proyecto info` | Ver detalles del proyecto activo |
| `proyecto cerrar` | Cerrar y guardar proyecto |
| `reporte` | Generar reporte del proyecto activo |

### Ofensivo

| Comando | Descripción |
|---------|-------------|
| `phishing` | Suite de phishing (zphisher) |
| `ducky` | Ejecutar payload HID (Rubber Ducky) |

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

Desarrollo actual: Termux en Android con MockSDR para la parte RF y hardware real para todo lo demás.

---

## Desarrollo

```bash
# Setup completo para desarrollo
git clone https://github.com/bernalmariano457-hash/Sentinel-Anubis-os.git
cd Sentinel-Anubis-os
pip install -e ".[all]"

# Comandos disponibles
make test          # tests sin hardware (58 tests)
make check         # lint + tipos + tests — idéntico al CI
make format        # corrige y formatea con ruff
make test-hardware # requiere RTL-SDR conectado
make run           # arrancar Sentinel
```

El CI corre automáticamente en cada push a `main` y en cada PR — lint con ruff, type checking con pyright y tests excluyendo hardware físico.

### Estructura de tests

```
tests/
└── test_auth_security.py   # Auth · bcrypt · lockout · Fernet · rotación de clave
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
- [x] Sistema de proyectos con evidencias y hallazgos por severidad
- [x] pyproject.toml — dependencias por plataforma (uConsole / Kali / Termux)
- [x] CI/CD con GitHub Actions — lint + types + tests
- [x] 58 tests unitarios — Auth, Security, VendorResolver

### En progreso

- [ ] Arranque nativo en uConsole (reemplazar el login shell)
- [ ] Tests del ModuleRegistry y CommandHandler

### Próximo

- [ ] Decodificador de imágenes de satélite NOAA (137 MHz)
- [ ] Decodificador ADS-B completo con pyModeS
- [ ] Triangulación Wi-Fi con mapa en vivo en terminal
- [ ] Cobertura de tests al 80%

---

Construido por [@bernalmariano457](https://github.com/bernalmariano457) — feedback bienvenido, especialmente de alguien corriendo Python en hardware embebido.
