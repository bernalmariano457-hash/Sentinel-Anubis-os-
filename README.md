# APEX SENTINEL — Anubis OS

> A terminal-based tactical OS I'm building for the ClockworkPi uConsole. No GUI, no mouse. Just Python, RF hardware, and a keyboard.

![Python](https://img.shields.io/badge/Python-3.13-blue) ![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Android%20%7C%20uConsole-green) ![Status](https://img.shields.io/badge/Status-In%20Development-orange) ![License](https://img.shields.io/badge/License-MIT-yellow)

---

## What is this?

I wanted a portable security tool that actually fits in a pocket and runs without a desktop environment. The uConsole is exactly the hardware I had in mind — clamshell, keyboard, expansion port for an RTL-SDR dongle. So I started building the software to match.

Anubis OS is a Python application that boots into its own terminal interface, asks for a master password, and gives you a set of modules for network analysis, RF scanning, OSINT, and field forensics. It's designed to run natively on the uConsole but also works on Kali, Debian, and Termux on Android.

The goal isn't to replace Kali. It's something different — a purpose-built system with its own auth, its own interface, and tight integration with SDR hardware.

---

## What's working right now

```
AnubisOS@Sentinel~# (): help

  APEX SENTINEL  v2.2
  ANUBIS OS — Sistema Operativo Táctico

  SISTEMA          DESCRIPCIÓN
  help / ?         Show this menu
  status           System status
  logs             Event history
  exit             Close Sentinel

  RED              DESCRIPCIÓN
  scan             ARP scan of local network
  advscan          Advanced scan (Nmap)
  portscan         TCP port scan
  sniff            Packet capture
  radar            Wi-Fi RSSI radar mode

  RF / SDR         DESCRIPCIÓN
  rfscan           RF frequency scan
  rfbarrido        Spectrum sweep by range
  radio            Listen and demodulate (WFM/NFM/AM/SSB)
  rfgrabar         Record IQ signal to file
  rfplay           Replay recorded IQ file
  adsb             ADS-B monitor — live aircraft transponders at 1090 MHz

  FORENSE          DESCRIPCIÓN
  geofoto          Extract GPS from photo EXIF
  locate           IP geolocation
  mobile           Basic mobile triage
  view             Read forensic file

  PROYECTOS        DESCRIPCIÓN
  proyecto nuevo   Create operation workspace
  reporte          Generate full report
```

---

## RF / SDR module

This is the part I'm most excited about for the uConsole. The RF engine supports RTL-SDR natively with a MockSDR fallback for development without hardware.

Right now it does:
- Real-time FFT spectrum analysis with waterfall display
- Signal detection across 35 known frequency bands
- WFM / NFM / AM / USB / LSB demodulation
- IQ recording to `.iq` files (compatible with SDR#, GQRX, GNU Radio)
- ADS-B decoding at 1090 MHz — live aircraft tracking in the terminal

When the uConsole arrives, the RTL-SDR connects through the expansion port and everything runs natively. On Android/Termux it uses MockSDR for development.

---

## Security

- bcrypt with auto-generated salt (migrates from legacy SHA-256 on first login)
- Credentials stored separately, never in `config.json`
- Persistent lockout between sessions — rate limiting survives restarts
- Fernet symmetric encryption for sensitive files
- Key rotation with dated backups

---

## Running it

**On Linux / Kali / Debian:**
```bash
git clone https://github.com/bernalmariano457-hash/Sentinel-Anubis-os.git
cd Sentinel-Anubis-os
pip install -r requirements.txt
python Main.py
```

**On Android (Termux):**
```bash
pkg update && pkg install git python
git clone https://github.com/bernalmariano457-hash/Sentinel-Anubis-os.git
cd Sentinel-Anubis-os
pip install -r requirements.txt --break-system-packages
python Main.py
```

First boot will ask you to set a master password. After that it goes straight to the interface.

**For RTL-SDR support:**
```bash
# Linux
sudo apt install rtl-sdr
pip install pyrtlsdr

# Termux
pkg install rtl-sdr
pip install pyrtlsdr --break-system-packages
```

---

## Project structure

```
Sentinel-Anubis-os/
├── Main.py
├── core/           # auth, logging, command routing, plugins
├── modules/
│   ├── rf/         # RTL-SDR, spectrum analysis, demodulation, ADS-B
│   ├── network/    # radar, scanner, sniffer, Wi-Fi
│   ├── geo/        # geolocation, Wi-Fi triangulation
│   ├── forense/    # EXIF, mobile triage, forensic reader
│   ├── osint/      # passive recon, CVE lookup
│   ├── audit/      # credential audit, phishing, payloads
│   └── reporte/    # report generation, evidence management
├── plugins/        # hot-loadable modules
├── data/           # logs, evidence, security (gitignored)
└── tools/          # setup scripts
```

---

## Hardware target

**ClockworkPi uConsole with RTL-SDR V3**

The uConsole is the whole reason this project exists in the shape it's in. Terminal-native, keyboard-driven, compact enough to carry anywhere. The expansion port takes an RTL-SDR dongle directly, which means the RF module runs on real hardware without adapters.

My uConsole is on its way. Until then, development runs on Termux (Android) with MockSDR for the RF parts and real hardware for everything else.

---

## Roadmap

- [ ] Native boot mode for uConsole (replace login shell)
- [ ] NOAA satellite image decoder (137 MHz)
- [ ] Full ADS-B decoder with pyModeS
- [ ] install.sh for one-command setup on Debian/Kali
- [ ] Wi-Fi geolocation triangulation with live map

---

## Dependencies

Core: `rich` `python-dotenv` `requests` `bcrypt` `cryptography`  
RF: `numpy` `scipy` `sounddevice` `pyrtlsdr` (optional)  
Network: `scapy` `netifaces`  
Forensics: `Pillow` `python-whois`

---

Built by [@bernalmariano457](https://github.com/bernalmariano457) — feedback welcome, especially from anyone running Python tools on embedded hardware.
