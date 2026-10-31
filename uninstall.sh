#!/usr/bin/env bash
set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}====================================================${NC}"
echo -e "${CYAN}      DESINSTALADOR DE APEX SENTINEL                ${NC}"
echo -e "${CYAN}====================================================${NC}"

if [ -f "/etc/systemd/system/sentinel.service" ]; then
    echo -e "[*] Deteniendo y eliminando servicio systemd..."
    sudo systemctl stop sentinel.service || true
    sudo systemctl disable sentinel.service || true
    sudo rm /etc/systemd/system/sentinel.service
    sudo systemctl daemon-reload
    echo -e "${GREEN}[+] Servicio systemd eliminado.${NC}"
else
    echo -e "[*] No se encontró servicio systemd."
fi

echo -e "[*] Eliminando entorno virtual..."
rm -rf .venv

echo -e "${GREEN}[+] Desinstalación completada. Los datos en data/ se han conservado por seguridad.${NC}"