#!/usr/bin/env bash
set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' 

echo -e "${CYAN}====================================================${NC}"
echo -e "${CYAN}      INSTALADOR DE APEX SENTINEL — ANUBIS OS       ${NC}"
echo -e "${CYAN}====================================================${NC}"

if [ -d "/data/data/com.termux" ]; then
    PLATFORM="termux"
elif grep -q "ClockworkPi" /proc/device-tree/model 2>/dev/null || grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    PLATFORM="uconsole"
else
    PLATFORM="linux"
fi
echo -e "${GREEN}[+] Plataforma detectada: $PLATFORM${NC}"

echo -e "${CYAN}[*] Instalando dependencias del sistema...${NC}"
if [ "$PLATFORM" = "termux" ]; then
    pkg update -y
    pkg install -y python python-pip rtl-sdr root-repo tsu git
elif [ "$PLATFORM" = "uconsole" ]; then
    sudo apt update
    sudo apt install -y python3 python3-pip python3-venv rtl-sdr librtlsdr-dev git
else
    sudo apt update
    sudo apt install -y python3 python3-pip python3-venv rtl-sdr librtlsdr-dev git
fi

echo -e "${CYAN}[*] Configurando entorno de Python...${NC}"
cd "$(dirname "$0")"

if [ "$PLATFORM" = "termux" ]; then
    pip install -e ".[termux]" --break-system-packages
else
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -e ".[all]"
fi

if [ "$PLATFORM" != "termux" ]; then
    echo -e "${CYAN}[*] Instalando servicio de arranque automático...${NC}"
    
    CURRENT_DIR=$(pwd)
    CURRENT_USER=$(whoami)
    
    cat <<EOF | sudo tee /etc/systemd/system/sentinel.service > /dev/null
[Unit]
Description=Apex Sentinel - Anubis OS Tactical Terminal
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$CURRENT_DIR
Environment="SENTINEL_AUTH_MODE=systemd"
ExecStart=$CURRENT_DIR/.venv/bin/python $CURRENT_DIR/Main.py
Restart=on-failure
RestartSec=5
StandardInput=tty
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable sentinel.service
    echo -e "${GREEN}[+] Servicio systemd instalado y habilitado.${NC}"
fi

# 5. Crear estructura de directorios de datos
echo -e "${CYAN}[*] Creando estructura de directorios...${NC}"
mkdir -p data/logs data/evidence data/evidence/rf data/evidence/rf/iq data/proyectos

echo -e "${GREEN}====================================================${NC}"
echo -e "${GREEN}      INSTALACIÓN COMPLETADA CON ÉXITO              ${NC}"
echo -e "${GREEN}====================================================${NC}"
echo -e "Para iniciar manualmente:"
if [ "$PLATFORM" = "termux" ]; then
    echo -e "  python Main.py"
else
    echo -e "  source .venv/bin/activate && python Main.py"
    echo -e "Para arrancar el servicio ahora:"
    echo -e "  sudo systemctl start sentinel"
fi