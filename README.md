# APEX SENTINEL — Anubis OS

```
   ╔═══════════╗
   ║  /\   /\  ║
   ║ (  \_/  ) ║
   ║  \     /  ║
   ║  /\___/\  ║
   ║ / / | \ \ ║
   ╚═══════════╝
   APEX SENTINEL v2.1
```

> Framework táctico de ciberseguridad para uso en entornos autorizados, laboratorios y CTFs.

---

## Advertencia legal

Este software es exclusivamente para uso en sistemas sobre los que tienes **permiso explícito** del propietario, entornos de laboratorio controlados y competencias CTF. El uso no autorizado contra sistemas ajenos es ilegal. El autor no se responsabiliza del mal uso de esta herramienta.

---

## Requisitos del sistema

| Requisito     | Mínimo             |
|---------------|--------------------|
| Python        | 3.10+              |
| Sistema       | Linux (recomendado) / Windows 10+ |
| RAM           | 512 MB             |
| Permisos      | root / administrador para módulos de red |

---

## Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/bernalmariano457-hash/Sentinel-Anubis-os.git
cd Sentinel-Anubis-os

# 2. Crear entorno virtual (recomendado)
python -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Ejecutar
python main.py
```

---

## Estructura del proyecto

```
Sentinel-Anubis-os/
│
├── main.py                  # Punto de entrada principal
├── bootscreen.py            # Pantalla de arranque y banner
├── config.json              # Configuración del sistema (generado al primer inicio)
├── requirements.txt         # Dependencias Python
│
├── modules/                 # Módulos del sistema
│   ├── HydraModule.py
│   ├── TacticalSniffer.py
│   ├── RadarSentinel.py
│   ├── GeomapSentinel.py
│   ├── ExifAnalyzer.py
│   ├── ForensicReader.py
│   ├── BluetoothModule.py
│   ├── RFScanner.py
│   ├── WifiAtack.py
│   ├── EvilTwinServer.py
│   ├── MobileSentinel.py
│   ├── GeoPrecise.py
│   ├── LocatorModule.py
│   ├── SweepModule.py
│   ├── AdvancedScanner.py
│   ├── DuckyModule.py
│   ├── StealthModule.py
│   ├── SecurityModule.py
│   ├── NetworkModule.py
│   ├── PhishingModule.py
│   ├── WADecryptor.py
│   ├── DictionaryManager.py
│   ├── SystemChecker.py
│   ├── AuditEngine.py
│   └── ReportManager.py
│
├── data/
│   ├── logs/                # Logs del sistema
│   │   └── sentinel.log
│   ├── evidence/            # Resultados de auditorías
│   │   └── mobile/
│   └── wordlists/           # Diccionarios para auditoría
│
└── tools/                   # Herramientas externas
    └── zphisher/
```

---

## Primer inicio

Al ejecutar por primera vez, el sistema te pedirá crear una **contraseña maestra**. Esta se almacena como hash bcrypt en `config.json`. Nunca se guarda en texto plano.

```
ANUBIS OS: SETUP DE SEGURIDAD
[?] Contraseña Maestra (mín. 8 caracteres): ********
[?] Confirme la contraseña: ********
[+] Acceso configurado.
```

---

## Comandos disponibles

| Categoría     | Comando       | Descripción                          |
|---------------|---------------|--------------------------------------|
| Sistema       | `help`        | Índice de comandos                   |
|               | `status`      | Estado de módulos                    |
|               | `clear`       | Recarga el banner                    |
|               | `logs`        | Historial de operaciones             |
|               | `files`       | Explorador de archivos               |
|               | `exit`        | Cierre seguro                        |
| Red           | `portscan`    | Auditoría de puertos                 |
|               | `sweep`       | Escaneo de perímetro ARP             |
|               | `sniff`       | Captura de tráfico                   |
|               | `advscan`     | Escaneo detallado de objetivo        |
|               | `radar`       | Radar Wi-Fi por RSSI                 |
| Forense       | `mobile`      | Triaje Android / iOS                 |
|               | `geofoto`     | Metadatos GPS en imágenes            |
|               | `locate`      | Rastreo IP / GPS                     |
| Stealth       | `stealth`     | Verificar huella digital             |

---

## Tecnologías utilizadas

- [Rich](https://github.com/Textualize/rich) — Interfaz de terminal
- [Scapy](https://scapy.net/) — Manipulación de paquetes de red
- [bcrypt](https://pypi.org/project/bcrypt/) — Hashing seguro de contraseñas
- [Pillow](https://python-pillow.org/) — Análisis de imágenes EXIF
- [PyCryptodome](https://pycryptodome.readthedocs.io/) — Criptografía

---

## Contribuir

1. Haz fork del repositorio
2. Crea una rama: `git checkout -b feature/nueva-funcion`
3. Haz commit de tus cambios: `git commit -m 'Agrega nueva función'`
4. Haz push: `git push origin feature/nueva-funcion`
5. Abre un Pull Request

---

## Licencia

MIT License — consulta el archivo `LICENSE` para más detalles.
