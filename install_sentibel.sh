#!/bin/bash

# --- Colores para la terminal ---
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${CYAN}[*] Iniciando forja del entorno Apex Sentinel...${NC}"

# 1. Actualizar el sistema
echo -e "${YELLOW}[1/4] Actualizando repositorios...${NC}"
sudo apt update && sudo apt upgrade -y

# 2. Instalar herramientas de auditoría
echo -e "${YELLOW}[2/4] Instalando herramientas principales...${NC}"
sudo apt install -y nmap hydra sqlmap adb metasploit-framework

# 3. Instalar dependencias de Python
echo -e "${YELLOW}[3/4] Instalando librerías de Python necesarias...${NC}"
pip install rich requests scapy fpdf2 pycryptodome piexif

# 4. Configurar carpetas de evidencia
echo -e "${YELLOW}[4/4] Creando estructura de directorios...${NC}"
mkdir -p data/evidence
mkdir -p data/wordlists

echo -e "${GREEN}[+] ¡Instalación completada! El Sentinel está listo para el despliegue.${NC}"
echo -e "${CYAN}[!] Ejecuta el sistema con: python3 Main.py${NC}"