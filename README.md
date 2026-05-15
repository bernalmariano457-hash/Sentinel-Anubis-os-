# APEX SENTINEL — Anubis OS

> Un OS táctico para terminal que estoy construyendo para la ClockworkPi uConsole. Sin GUI, sin mouse. Solo Python, hardware RF y un teclado.


[![CI](https://github.com/bernalmariano457/Sentinel-Anubis-os/actions/workflows/ci.yml/badge.svg)](https://github.com/bernalmariano457/Sentinel-Anubis-os/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/TU_USUARIO/Sentinel-Anubis-os/branch/main/graph/badge.svg)](https://codecov.io/gh/bernalmariano457/Sentinel-Anubis-os)
[![Python](https://img.shields.io/badge/Python-3.13-blue)](https://python.org)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Platform](https://img.shields.io/badge/Platform-uConsole%20%7C%20Kali%20%7C%20Termux-green)](https://github.com/bernalmariano457/Sentinel-Anubis-os)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)


## ¿Qué es esto?

Quería una herramienta de seguridad portátil que cupiera en una bolsa, que no necesitara entorno gráfico y que se sintiera hecha para el trabajo en campo. La uConsole encajaba perfecto — diseño clamshell, teclado físico, puerto de expansión para conectar un RTL-SDR directamente.

Anubis OS es una aplicación Python que arranca en su propia interfaz de terminal, pide una contraseña maestra y te da acceso a un conjunto de módulos para análisis de red, escaneo RF, OSINT y forense. Funciona de forma nativa en la uConsole, pero también corre sin problemas en Kali, Debian y Termux en Android.

La idea no es reemplazar Kali. Es algo distinto — un sistema con su propia autenticación, su propia interfaz y una integración real con hardware SDR.

---

## Lo que ya funciona

```
AnubisOS@Sentinel~# (): help

  APEX SENTINEL  v2.2
  ANUBIS OS — Sistema Operativo Táctico

  SISTEMA          DESCRIPCIÓN
  help / ?         Muestra este menú
  status           Estado del sistema
  logs             Historial de eventos
  exit             Cerrar Sentinel

  RED              DESCRIPCIÓN
  scan             Escaneo ARP de la red local
  advscan          Escaneo avanzado (Nmap)
  portscan         Escaneo TCP de puertos
  sniff            Captura de paquetes
  radar            Modo radar Wi-Fi por RSSI

  RF / SDR         DESCRIPCIÓN
  rfscan           Escaneo de frecuencias RF
  rfbarrido        Barrido espectral por rango
  radio            Escuchar y demodular (WFM/NFM/AM/SSB)
  rfgrabar         Grabar señal IQ a archivo
  rfplay           Reproducir archivo IQ grabado
  adsb             Monitor ADS-B — transponders de aeronaves en 1090 MHz en vivo

  FORENSE          DESCRIPCIÓN
  geofoto          Extraer GPS de EXIF de fotos
  locate           Geolocalización por IP
  mobile           Triaje básico de móvil
  view             Leer archivo forense

  PROYECTOS        DESCRIPCIÓN
  proyecto nuevo   Crear workspace de operación
  reporte          Generar reporte completo
```

---

## Módulo RF / SDR

Esta es la parte que más me entusiasma para la uConsole. El motor RF usa RTL-SDR de forma nativa, con un MockSDR como fallback para desarrollar sin hardware físico.

Por ahora soporta:
- Análisis espectral FFT en tiempo real con vista de cascada (waterfall)
- Detección de señales en 35 bandas de frecuencia conocidas
- Demodulación WFM / NFM / AM / USB / LSB
- Grabación IQ a archivos `.iq` (compatibles con SDR#, GQRX y GNU Radio)
- Decodificación ADS-B a 1090 MHz — seguimiento de aeronaves en vivo desde la terminal

Cuando llegue la uConsole, el RTL-SDR se conecta directo por el puerto de expansión y todo corre en hardware real. Mientras tanto, el desarrollo va sobre Termux con MockSDR para la parte RF.

---

## Seguridad

- bcrypt con salt autogenerado (migra desde SHA-256 legacy al primer login)
- Credenciales almacenadas por separado, nunca en `config.json`
- Bloqueo persistente entre sesiones — el rate limiting sobrevive reinicios
- Cifrado simétrico Fernet para archivos sensibles
- Rotación de llaves con backups fechados

---

## Cómo correrlo

**En Linux / Kali / Debian:**
```bash
git clone https://github.com/bernalmariano457-hash/Sentinel-Anubis-os.git
cd Sentinel-Anubis-os
pip install -r requirements.txt
python Main.py
```

**En Android (Termux):**
```bash
pkg update && pkg install git python
git clone https://github.com/bernalmariano457-hash/Sentinel-Anubis-os.git
cd Sentinel-Anubis-os
pip install -r requirements.txt --break-system-packages
python Main.py
```

El primer arranque pedirá que configures una contraseña maestra. Después de eso, va directo a la interfaz.

**Para soporte RTL-SDR:**
```bash
# Linux
sudo apt install rtl-sdr
pip install pyrtlsdr

# Termux
pkg install rtl-sdr
pip install pyrtlsdr --break-system-packages
```

---

## Estructura del proyecto

```
Sentinel-Anubis-os/
├── Main.py
├── core/           # auth, logging, enrutamiento de comandos, plugins
├── modules/
│   ├── rf/         # RTL-SDR, análisis espectral, demodulación, ADS-B
│   ├── network/    # radar, escáner, sniffer, Wi-Fi
│   ├── geo/        # geolocalización, triangulación Wi-Fi
│   ├── forense/    # EXIF, triaje móvil, lector forense
│   ├── osint/      # reconocimiento pasivo, búsqueda de CVEs
│   ├── audit/      # auditoría de credenciales, phishing, payloads
│   └── reporte/    # generación de reportes, gestión de evidencia
├── plugins/        # módulos cargables en caliente
├── data/           # logs, evidencia, seguridad (ignorado por git)
└── tools/          # scripts de configuración
```

---

## Hardware objetivo

**ClockworkPi uConsole + RTL-SDR V3**

La uConsole es la razón por la que este proyecto existe con la forma que tiene. Terminal puro, teclado físico, cabe en una mochila. El puerto de expansión acepta el RTL-SDR directamente, sin adaptadores, lo que hace que el módulo RF corra en hardware real sin complicaciones.

Mi uConsole está en camino. Mientras tanto, desarrollo en Termux con MockSDR para la parte RF y hardware real para todo lo demás.

---

## Roadmap

- [ ] Modo de arranque nativo en uConsole (reemplazar el login shell)
- [ ] Decodificador de imágenes de satélite NOAA (137 MHz)
- [ ] Decodificador ADS-B completo con pyModeS
- [ ] `install.sh` para setup en un solo comando en Debian/Kali
- [ ] Triangulación Wi-Fi con mapa en vivo

---

## Dependencias

**Core:** `rich` `python-dotenv` `requests` `bcrypt` `cryptography`  
**RF:** `numpy` `scipy` `sounddevice` `pyrtlsdr` *(opcional)*  
**Red:** `scapy` `netifaces`  
**Forense:** `Pillow` `python-whois`

---

Construido por [@bernalmariano457](https://github.com/bernalmariano457) — feedback bienvenido, especialmente de alguien corriendo herramientas Python en hardware embebido.
