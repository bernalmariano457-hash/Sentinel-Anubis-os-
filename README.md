<div align="center">

```
   ╔═══════════════════╗
   ║    /\       /\    ║
   ║   (  \_____/  )   ║
   ║    \         /    ║
   ║    /\  ___  /\    ║
   ║   / / | A | \ \   ║
   ╚═══════════════════╝
```

# APEX SENTINEL
### Anubis OS — Framework Táctico de Ciberseguridad

[![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-lightgrey?style=flat-square)]()
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Status](https://img.shields.io/badge/Status-En%20desarrollo-yellow?style=flat-square)]()

*Framework de análisis de seguridad para entornos autorizados, laboratorios y CTFs.*

</div>

---

> **⚠ AVISO LEGAL**
> Este software es exclusivamente para uso en sistemas sobre los que tienes **permiso explícito y por escrito** del propietario, entornos de laboratorio controlados y competencias CTF. El uso contra sistemas ajenos sin autorización es un delito tipificado en la mayoría de jurisdicciones. El autor no se responsabiliza del mal uso de esta herramienta.

---

## Índice

- [Características](#características)
- [Requisitos del sistema](#requisitos-del-sistema)
- [Instalación](#instalación)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Primer inicio](#primer-inicio)
- [Módulos disponibles](#módulos-disponibles)
- [Comandos](#comandos)
- [Hardware objetivo](#hardware-objetivo)
- [Tecnologías](#tecnologías)
- [Contribuir](#contribuir)
- [Licencia](#licencia)

---

## Características

- **Análisis de red** — ARP sweep, port scan, traffic sniff, Wi-Fi radar
- **Módulo RF** — Escáner de espectro con FFT/CFAR, demodulación AM/FM/SSB, waterfall terminal
- **TSCM** — Detección de hardware de vigilancia por OUI (cámaras, IoT, ESP32)
- **Forense digital** — Lectura de WhatsApp, Chrome, Firefox, Telegram sin modificar los datos
- **Criptografía** — Descifrado AES-256-GCM de bases de datos WhatsApp (crypt14/crypt15)
- **Bluetooth** — Escaneo BLE y Bluetooth clásico con clasificación de dispositivos
- **OSINT** — Geolocalización por IP, metadatos EXIF/GPS en imágenes
- **Seguridad** — Autenticación bcrypt, logs con rotación, evidencia en CSV/SigMF
- **Sin hardware requerido** — MockSDR para desarrollo y tests sin RTL-SDR físico

---

## Requisitos del sistema

| Componente    | Mínimo                        | Recomendado              |
|---------------|-------------------------------|--------------------------|
| Python        | 3.10+                         | 3.11+                    |
| Sistema       | Linux / Windows 10+           | Debian 12 / Ubuntu 22.04 |
| RAM           | 512 MB                        | 2 GB+                    |
| Permisos      | Usuario normal                | root para módulos de red |
| Hardware SDR  | Ninguno (MockSDR disponible)  | RTL-SDR v3 / CM5         |

---

## Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/bernalmariano457-hash/Sentinel-Anubis-os-.git
cd Sentinel-Anubis-os-

# 2. Crear entorno virtual (recomendado)
python -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows

# 3. Instalar dependencias del sistema (Linux)
sudo apt install -y \
  rtl-sdr librtlsdr-dev \
  python3-pyaudio portaudio19-dev \
  python3-dev libbluetooth-dev

# 4. Instalar dependencias Python
pip install -r requirements.txt

# 5. Ejecutar
python main.py
```

> **Nota para uConsole / ARM:**
> ```bash
> pip install -r requirements.txt --break-system-packages
> ```

---

## Estructura del proyecto

```
Sentinel-Anubis-os/
│
├── main.py                    # Punto de entrada — CLI principal
├── bootscreen.py              # Banner y pantalla de arranque
├── requirements.txt           # Dependencias Python
│
├── modules/                   # Módulos del sistema
│   │
│   ├── ── Red ──────────────────────────────────────────
│   ├── SweepModule.py         # Barrido ARP + detección TSCM por OUI
│   ├── AdvancedScanner.py     # Escaneo de puertos detallado
│   ├── TacticalSniffer.py     # Captura y análisis de tráfico
│   ├── RadarSentinel.py       # Radar Wi-Fi por RSSI
│   ├── NetworkModule.py       # Utilidades de red general
│   │
│   ├── ── RF / Espectro ─────────────────────────────────
│   ├── RFScanner.py           # Escáner de espectro RF (FFT + CFAR)
│   ├── rf_demod.py            # Demodulación AM/NFM/WFM/SSB
│   ├── rf_mock.py             # MockSDR para tests sin hardware
│   ├── dsp.py                 # Motor DSP (Welch, CFAR, BW -3dB)
│   ├── bands.py               # Base de datos de bandas RF
│   ├── rf_database.py         # Persistencia SQLite de señales
│   ├── rf_storage.py          # Almacenamiento IQ / SigMF
│   │
│   ├── ── Forense ───────────────────────────────────────
│   ├── ForensicReader.py      # WhatsApp / Chrome / Firefox / Telegram
│   ├── WADecryptor.py         # Descifrado AES-GCM crypt14/crypt15
│   ├── ExifAnalyzer.py        # Metadatos GPS en imágenes
│   ├── MobileSentinel.py      # Triaje Android / iOS
│   │
│   ├── ── Bluetooth ─────────────────────────────────────
│   ├── BluetoothModule.py     # BLE + clásico — detección y puente
│   │
│   ├── ── OSINT / Geolocalización ───────────────────────
│   ├── LocatorModule.py       # Rastreo IP / GPS
│   ├── GeomapSentinel.py      # Mapa de señales geolocalizadas
│   ├── GeoPrecise.py          # Precisión GPS aumentada
│   │
│   ├── ── Ataques controlados (laboratorio) ────────────
│   ├── WifiAtack.py           # Beacon spam / Deauth (lab only)
│   ├── EvilTwinServer.py      # AP gemelo malicioso (lab only)
│   ├── HydraModule.py         # Fuerza bruta de credenciales
│   ├── PhishingModule.py      # Plantillas de phishing (CTF)
│   ├── DuckyModule.py         # Payloads USB Rubber Ducky
│   │
│   └── ── Sistema ───────────────────────────────────────
│       ├── SecurityModule.py  # Autenticación y control de acceso
│       ├── StealthModule.py   # Verificación de huella digital
│       ├── SystemChecker.py   # Diagnóstico de dependencias
│       ├── AuditEngine.py     # Motor de auditoría
│       ├── DictionaryManager.py # Gestión de wordlists
│       └── ReportManager.py   # Generación de reportes
│
├── data/
│   ├── logs/                  # Logs con rotación automática
│   ├── evidence/              # Resultados de escaneos (CSV, WAV, IQ)
│   │   ├── rf/                # Capturas de espectro y señales
│   │   ├── sweep/             # Evidencia de barridos de red
│   │   └── mobile/            # Triaje forense móvil
│   └── wordlists/             # Diccionarios para auditoría
│
└── tools/
    └── zphisher/              # Herramienta de phishing externa
```

---

## Primer inicio

Al ejecutar por primera vez se crea una contraseña maestra almacenada como hash bcrypt. **Nunca se guarda en texto plano.**

```
╔══════════════════════════════════╗
║   ANUBIS OS — SETUP DE SEGURIDAD ║
╚══════════════════════════════════╝

[?] Contraseña Maestra (mín. 8 caracteres): ············
[?] Confirme la contraseña:                 ············
[+] Hash bcrypt generado y almacenado.
[+] Sistema listo.
```

---

## Módulos disponibles

### Red y Perímetro

| Módulo           | Descripción                                              |
|------------------|----------------------------------------------------------|
| `SweepModule`    | Barrido ARP con detección TSCM por OUI — cámaras, IoT, ESP32 |
| `AdvancedScanner`| Escaneo de puertos con fingerprinting de servicio        |
| `TacticalSniffer`| Captura pasiva de tráfico con análisis de protocolos     |
| `RadarSentinel`  | Mapa de redes Wi-Fi ordenadas por RSSI                   |

### RF / Espectro

| Módulo        | Descripción                                                 |
|---------------|-------------------------------------------------------------|
| `RFScanner`   | Escáner de espectro con FFT Welch + CFAR bilateral          |
| `rf_demod`    | Demodulación AM / NFM / WFM / USB / LSB en numpy puro       |
| `rf_mock`     | MockSDR — señales sintéticas sin hardware real              |
| `dsp`         | Motor DSP: PSD, picos, BW -3dB, supresión DC               |

### Forense Digital

| Módulo           | Descripción                                              |
|------------------|----------------------------------------------------------|
| `ForensicReader` | Mensajes WhatsApp, historial Chrome/Firefox, Telegram    |
| `WADecryptor`    | Descifrado AES-256-GCM de bases de datos WhatsApp        |
| `ExifAnalyzer`   | Extracción de metadatos GPS en fotos                     |
| `MobileSentinel` | Triaje completo de dispositivos Android / iOS            |

### Bluetooth

| Módulo            | Descripción                                             |
|-------------------|---------------------------------------------------------|
| `BluetoothModule` | Escaneo BLE + clásico, clasificación por RSSI, puente TCP |

---

## Comandos

| Categoría | Comando     | Descripción                               |
|-----------|-------------|-------------------------------------------|
| Sistema   | `help`      | Índice completo de comandos               |
|           | `status`    | Estado de módulos y dependencias          |
|           | `clear`     | Recarga el banner                         |
|           | `logs`      | Historial de operaciones                  |
|           | `files`     | Explorador de evidencias                  |
|           | `exit`      | Cierre seguro con hash de sesión          |
| Red       | `sweep`     | Barrido ARP + detección TSCM             |
|           | `portscan`  | Auditoría de puertos TCP/UDP              |
|           | `sniff`     | Captura pasiva de tráfico                 |
|           | `advscan`   | Escaneo detallado de objetivo             |
|           | `radar`     | Radar Wi-Fi por RSSI                      |
| RF        | `rf`        | Escáner de espectro RF                    |
|           | `rfscan`    | Escaneo rápido en frecuencia dada         |
| Forense   | `mobile`    | Triaje Android / iOS                      |
|           | `geofoto`   | Metadatos GPS en imágenes                 |
|           | `locate`    | Rastreo IP / GPS                          |
| BT        | `btjumper`  | Menú Bluetooth                            |
|           | `btscan`    | Escaneo BLE rápido                        |
| Stealth   | `stealth`   | Verificar huella digital del sistema      |

---

## Hardware objetivo

El sistema fue diseñado para correr en hardware compacto de campo:

| Hardware              | Estado          | Notas                              |
|-----------------------|-----------------|-------------------------------------|
| Raspberry Pi 4        | ✅ Soportado    | Probado con RTL-SDR v3              |
| **Compute Module 5**  | 🔜 En camino    | Target principal — todo listo       |
| uConsole (CM4)        | ✅ Soportado    | ARM — usar `--break-system-packages`|
| PC Linux x86_64       | ✅ Soportado    | Entorno de desarrollo               |
| Windows 10/11         | ⚠ Parcial      | Sin módulos de red raw              |

> El módulo RF funciona en **modo MockSDR** sin hardware SDR hasta que llegue el CM5.

---

## Tecnologías

| Librería          | Uso                                               |
|-------------------|---------------------------------------------------|
| [Rich](https://github.com/Textualize/rich)         | Interfaz de terminal — tablas, paneles, waterfall |
| [Scapy](https://scapy.net/)                         | ARP scan, captura de paquetes                     |
| [NumPy](https://numpy.org/)                         | FFT, PSD, CFAR, demodulación RF                   |
| [bcrypt](https://pypi.org/project/bcrypt/)          | Hash seguro de contraseña maestra                 |
| [PyCryptodome](https://pycryptodome.readthedocs.io/)| Descifrado AES-256-GCM WhatsApp                   |
| [Bleak](https://bleak.readthedocs.io/)              | Escaneo Bluetooth Low Energy (BLE)                |
| [Pillow](https://python-pillow.org/)                | Análisis de metadatos EXIF                        |
| [pyrtlsdr](https://pyrtlsdr.readthedocs.io/)        | Driver RTL-SDR hardware                           |
| SQLite3           | Persistencia de señales y evidencias (stdlib)     |

---

## Contribuir

```bash
# 1. Fork del repositorio en GitHub
# 2. Crear rama de feature
git checkout -b feature/nombre-del-modulo

# 3. Desarrollar y testear
python -m pytest tests/ -v

# 4. Commit con mensaje descriptivo
git commit -m "feat(ModuloX): descripción concisa del cambio"

# 5. Push y Pull Request
git push origin feature/nombre-del-modulo
```

**Convenciones de commits:**
- `feat(modulo):` — nueva funcionalidad
- `fix(modulo):` — corrección de bug
- `refactor(modulo):` — mejora de código sin cambio funcional
- `docs:` — cambios en documentación

---

## Licencia

MIT License — consulta el archivo [LICENSE](LICENSE) para más detalles.

---

<div align="center">
<sub>Apex Sentinel — Anubis OS | Desarrollado para CM5 🔜</sub>
</div>
