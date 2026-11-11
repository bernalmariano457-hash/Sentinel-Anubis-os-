# APEX SENTINEL — Anubis OS

> OS táctico de terminal para trabajo en campo. Sin GUI, sin mouse. Python, hardware RF y un teclado.

[![CI](https://github.com/bernalmariano457-hash/Sentinel-Anubis-os/actions/workflows/ci.yml/badge.svg)](https://github.com/bernalmariano457-hash/Sentinel-Anubis-os/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/bernalmariano457-hash/Sentinel-Anubis-os/branch/main/graph/badge.svg)](https://codecov.io/gh/bernalmariano457-hash/Sentinel-Anubis-os)
![Python](https://img.shields.io/badge/Python-3.13-blue)
![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)
![Platform](https://img.shields.io/badge/Platform-uConsole%20%7C%20Kali%20%7C%20Termux-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

```text
╔══════════════════════════════════════════════════════════════════╗
║          APEX SENTINEL  v2.4  —  ANUBIS OS                       ║
║          Sistema Operativo Táctico  ·  uConsole Edition          ║
╚══════════════════════════════════════════════════════════════════╝

  AnubisOS@Sentinel~# (): status

  MÓDULOS           ESTADO
  ──────────────────────────────────────────
  SOC Táctico       DRY-RUN  ·  vigilando red
  RF / SDR          RTL-SDR V3  ·  1246 MHz
  Network           wlan0mon  ·  activo
  Bluetooth         BLE  ·  disponible
  Forense           Ed25519  ·  cadena custodia activa
  OSINT             disponible
  Power             SoC 45°C  ·  Bat 78%  ·  Duty 100%

  AnubisOS@Sentinel~# (): soc start --simulate
  [+] SOC táctico activo — modo: DRY-RUN (simulando bloqueo)

  ⚠️ [SOC] ALERTA CRÍTICA: ET SCAN Potential SSH Scan desde 192.168.1.100
  [*] Evidencia firmada y sellada en custodia (Ed25519).
¿Qué es esto?
Una herramienta de seguridad portátil construida para la ClockworkPi uConsole — consola clamshell con teclado físico que cabe en una mochila. El objetivo era algo que arrancara rápido, no dependiera de entorno gráfico y tuviera integración real con hardware SDR sin adaptadores.

Anubis OS no es un wrapper de Kali. Es un sistema con su propio ciclo de autenticación, su propia interfaz de terminal construida con Rich, y módulos de dominio independientes que se cargan al arranque según el hardware disponible.

Novedad v2.4: Integración del Tactical SOC (SOAR) y la Cadena de Custodia Criptográfica. Ahora el sistema no solo captura datos; detecta ataques en tiempo real, responde autónomamente y sella la evidencia con firmas Ed25519 para que sea legalmente defendible en un peritaje.

Corre nativamente en la uConsole, en Kali / Debian, en Termux (Android) y ahora también vía Docker.

Arquitectura
text
Main.py (ApexSentinel)
├── core/
│   ├── ModuleRegistry       ← carga declarativa de módulos en runtime
│   ├── CommandHandler       ← despacho de comandos por dominio (mixins)
│   ├── async_runtime.py     ← motor asíncrono compartido (hilos y loops)
│   ├── tactical_soc.py      ← motor de detección y respuesta autónoma (SOAR)
│   ├── soc_manager.py       ← puente entre el SOC y la interfaz TUI
│   ├── evidence_bridge.py   ← firma criptográfica y cadena de custodia
│   ├── forensic_bridge.py   ← monitor de integridad del sistema (baseline)
│   ├── auth.py              ← bcrypt · lockout persistente
│   ├── GestorProyectos      ← workspaces de operación · evidencias
│   ├── sentinel_ui          ← componentes Rich reutilizables
│   ├── log_sistema          ← logging con niveles · auditoría · rotación
│   ├── sdr_broker.py        ← broker de acceso único al SDR · time-slicing
│   └── power_manager.py     ← gestión térmica · batería · throttling
│
├── src/sentinel/            ← NÚCLEO FORENSE (Aislado)
│   ├── integrity/           ← hashing (SHA-256) · firmas (Ed25519) · baseline
│   ├── custody/             ← cadena de custodia (hash-chain append-only)
│   ├── security/            ← vault cifrado (Argon2id) · auto-lockdown
│   ├── packaging/           ← empaquetado de evidencia (.sae)
│   └── reporting/           ← generación de reportes JSON y PDF
│
├── modules/
│   ├── rf/                  ← RTL-SDR · FFT · waterfall · ADS-B · NOAA
│   ├── network/             ← radar Wi-Fi · ARP scan · sniffer · Evil Twin
│   ├── geo/                 ← GeoPrecise · GeomapSentinel · KML · GeoJSON
│   ├── forense/             ← EXIF · triaje móvil · stealth · panic
│   ├── osint/               ← CVE lookup · geolocalización · reconocimiento
│   ├── audit/               ← Rubber Ducky HID · credenciales
│   └── reporte/             ← exportación · timeline
│
└── plugins/                 ← módulos de terceros · hot-reload
Características Principales
🛡️ Tactical SOC (Security Orchestration, Automation and Response)
Un motor de respuesta autónoma diseñado para operar en el borde (Edge SOAR).

Ingesta de eventos: Lee alertas de red (por ejemplo, eve.json de Suricata) mediante un offset para no consumir CPU ni batería de más.

Respuesta autónoma: Si detecta una amenaza crítica, bloquea la IP atacante vía iptables (en modo --live).

Guardrails: Cuenta con allowlist para IPs protegidas, cooldown anti-flapping y modo Dry-Run por defecto para evitar falsos positivos.

Asincronía: Usa un AsyncRuntime compartido para no asfixiar el procesador del CM4.

⚖️ Cadena de Custodia y Forense Criptográfico
Hashing en streaming: Cada archivo capturado (audio, IQ, logs) se hashea con SHA-256 durante su escritura sin cargarlo en RAM.

Firmas Ed25519: El operador firma cada artefacto. Si alguien modifica un solo byte de la evidencia, la firma se rompe.

Custody Log: Un registro inmutable (append-only) encadenado por hashes. Cada entrada incluye un prev_hash para detectar si alguien borró o alteró el historial.

Vault de Evidencia: Cifrado en reposo usando Argon2id (ganador del PHC) y AES-GCM.

Auto-Lockdown: Si el IntegrityMonitor detecta que los archivos del sistema (baseline) fueron modificados, bloquea la ejecución de comandos automáticamente.

Instalación
Auto-detect (recomendado)
bash
git clone https://github.com/bernalmariano457-hash/Sentinel-Anubis-os.git
cd Sentinel-Anubis-os
chmod +x install.sh && ./install.sh
El script detecta la plataforma automáticamente — uConsole, Kali o Termux — e instala únicamente las dependencias disponibles para ese entorno.

Docker (Entornos aislados)
bash
# Construir la imagen
docker build -t anubis-os .

# Correr en modo interactivo (TUI)
docker run -it --rm anubis-os

# Correr con permisos de red (para probar el SOC o escaneos)
docker run -it --rm --cap-add=NET_ADMIN --cap-add=NET_RAW --network host anubis-os
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

Comandos
Sistema y Seguridad
Comando	Descripción
help / ?	Menú de ayuda completo
status	Estado del sistema y módulos cargados
power	Estado de energía: temperatura, batería, SDR
exit	Cerrar Sentinel
SOC (Respuesta Autónoma)
Comando	Descripción
soc start --simulate	Inicia el SOC en modo prueba (ataques falsos, no bloquea)
soc start --live	Inicia el SOC real (bloquea IPs vía iptables)
soc stop	Detiene el monitor de red
soc status	Muestra si el SOC está vigilando
Forense y Cadena de Custodia
Comando	Descripción
geofoto	Extraer coordenadas GPS de fotos (EXIF)
mobile / mobile-deep	Triaje de dispositivos móviles
recover	File carving forense (.dd / .img o /dev/sdX)
panic	Protocolo de emergencia — cifra todo y sale
proyecto nuevo	Crear workspace de operación (agrupa evidencia)
reporte	Generar reporte forense (con firmas criptográficas)
Red y RF
Comando	Descripción
scan / advscan	Escaneo de red (ARP / Nmap)
radar	Radar Wi-Fi por RSSI en tiempo real
eviltwin	Portal cautivo para auditoría wireless (con captura forense)
rfscan	Escaneo de frecuencias con detección de señales
rfgrabar	Grabar señal IQ a archivo (firmado automáticamente)
adsb / noaa	Decodificadores de satélites y aeronaves
Seguridad
bcrypt con salt autogenerado — migra desde SHA-256 legacy al primer login.

Argon2id + AES-GCM — cifrado de evidencia en reposo.

Firmas Ed25519 — autenticidad e integridad de toda la evidencia capturada.

Cadena de custodia (hash-chain) — registro inmutable que detecta cualquier alteración.

Auto-Lockdown — si el sistema es comprometido, se congela y bloquea comandos.

Modo systemd — autenticación no-interactiva para arranque desatendido.

Hardware objetivo
ClockworkPi uConsole + RTL-SDR V3

La uConsole es la razón por la que este proyecto tiene la forma que tiene. Terminal puro, teclado físico, cabe en una mochila. El puerto de expansión acepta el RTL-SDR directamente — sin adaptadores, sin hubs — lo que hace que el módulo RF corra en hardware real sin fricción.

Desarrollo actual: Termux / Windows con MockSDR y FeedSimulado para la parte RF y de red, esperando el hardware final.

Desarrollo y Tests
bash
# Setup completo para desarrollo
git clone https://github.com/bernalmariano457-hash/Sentinel-Anubis-os.git
cd Sentinel-Anubis-os
pip install -e ".[all]"

# Comandos disponibles
make test          # tests sin hardware
make check         # lint + tipos + tests — idéntico al CI
make format        # corrige y formatea con ruff
make run           # arrancar Sentinel
Roadmap
Completado
☑ Autenticación bcrypt con migración desde SHA-256 legacy
☑ Lockout persistente entre sesiones
☑ ModuleRegistry — carga declarativa con fallback silencioso
☑ Motor RF: FFT · waterfall · demodulación · ADS-B · MockSDR
☑ SDRBroker — broker de acceso único al SDR con time-slicing
☑ PowerManager — gestión térmica, batería y throttling
☑ Núcleo Forense: Hashing SHA-256 + Firmas Ed25519
☑ Vault de Evidencia: Cifrado en reposo con Argon2id
☑ Auto-Lockdown: Monitor de integridad (baseline) con bloqueo automático
☑ Cadena de Custodia: Log inmutable con hash-chain y firmas
☑ Tactical SOC (SOAR): Ingesta de Suricata, respuesta autónoma (iptables) y evidencia forense
☑ AsyncRuntime: Motor asíncrono compartido para CM4
☑ Empaquetado: Archivos .sae verificables y reportes PDF
☑ Docker: Despliegue aislado para entornos de prueba
En progreso
□ Arranque nativo en uConsole (reemplazar el login shell con la imagen oficial)
□ Integración de la regla anti-flapping en el firewall del kernel
Construido por @bernalmariano457-hash — feedback bienvenido, especialmente de alguien corriendo Python en hardware embebido.