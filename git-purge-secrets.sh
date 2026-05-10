#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════
#  SENTINEL — git-purge-secrets.sh
#  Elimina PERMANENTEMENTE del historial de git los archivos
#  sensibles que se comprometieron por error.
#
#  ⚠ LEER ANTES DE EJECUTAR:
#    1. Hacer backup del repo: cp -r . ../sentinel-backup
#    2. Este script reescribe el historial — todos los colaboradores
#       deberán hacer `git clone` de nuevo tras ejecutarlo
#    3. Si el repo ya está en GitHub: contactar soporte para borrar
#       el cache de GitHub tras el push forzado
#
#  Uso: bash git-purge-secrets.sh
# ══════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Colores ───────────────────────────────────────────────────────
RED='\033[0;31m'
YEL='\033[1;33m'
GRN='\033[0;32m'
DIM='\033[2m'
RST='\033[0m'

echo -e "${YEL}"
echo "╔═══════════════════════════════════════════════════╗"
echo "║     SENTINEL — PURGA DE SECRETOS EN GIT           ║"
echo "╚═══════════════════════════════════════════════════╝"
echo -e "${RST}"

# ── Verificar que estamos en un repo git ─────────────────────────
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  echo -e "${RED}[!] No estás dentro de un repositorio git.${RST}"
  exit 1
fi

# ── Verificar git-filter-repo instalado ──────────────────────────
if ! command -v git-filter-repo &> /dev/null; then
  echo -e "${RED}[!] git-filter-repo no está instalado.${RST}"
  echo -e "${DIM}    Instalar con: pip install git-filter-repo${RST}"
  exit 1
fi

echo -e "${YEL}[!] ADVERTENCIA: Este script reescribe el historial de git.${RST}"
echo -e "${DIM}    Backup recomendado antes de continuar.${RST}"
read -rp "¿Continuar? [s/N]: " CONFIRM
[[ "$CONFIRM" =~ ^[sS]$ ]] || { echo "Cancelado."; exit 0; }

echo ""
echo -e "${GRN}[*] Paso 1: Eliminando archivos sensibles del historial...${RST}"

# Archivos a purgar del historial completo
ARCHIVOS_A_PURGAR=(
  "core/data/security/.credentials"
  "core/data/logs/sentinel.log"
  "core/data/logs/events.jsonl"
  "core/data/logs/historial.json"
  "core/data/logs/audit.log"
  "data/logs/events.jsonl"
  "data/logs/historial.json"
  "data/evidence/rf/scan_300.000MHz_20260503_222130.csv"
  "data/evidence/rf/scan_5.000MHz_20260503_222018.csv"
  "data/evidence/rf/scan_500.000MHz_20260504_202856.csv"
  "data/proyectos/20260424_212702_laboratory/proyecto.json"
  "__pycache__/HydraModule.cpython-313.pyc"
  "plugins/__pycache__/ejemplo_plugin.cpython-313.pyc"
)

for archivo in "${ARCHIVOS_A_PURGAR[@]}"; do
  echo -e "  ${DIM}→ purgando: $archivo${RST}"
  git filter-repo \
    --path "$archivo" \
    --invert-paths \
    --force \
    2>/dev/null || echo -e "  ${DIM}  (no encontrado en historial — ok)${RST}"
done

echo ""
echo -e "${GRN}[*] Paso 2: Eliminando directorios sensibles completos...${RST}"

DIRS_A_PURGAR=(
  "core/data/security"
  "core/data/logs"
  "data/logs"
  "data/evidence"
  "data/proyectos"
)

for dir in "${DIRS_A_PURGAR[@]}"; do
  echo -e "  ${DIM}→ purgando directorio: $dir/${RST}"
  git filter-repo \
    --path "$dir/" \
    --invert-paths \
    --force \
    2>/dev/null || echo -e "  ${DIM}  (no encontrado — ok)${RST}"
done

echo ""
echo -e "${GRN}[*] Paso 3: Creando estructura de directorios vacía (con .gitkeep)...${RST}"

DIRS_GITKEEP=(
  "core/data/logs"
  "core/data/security"
  "data/logs"
  "data/evidence"
  "data/evidence/rf"
  "data/evidence/rf/iq"
  "data/proyectos"
)

for dir in "${DIRS_GITKEEP[@]}"; do
  mkdir -p "$dir"
  touch "$dir/.gitkeep"
  echo -e "  ${DIM}→ creado: $dir/.gitkeep${RST}"
done

echo ""
echo -e "${GRN}[*] Paso 4: Copiando .gitignore actualizado...${RST}"
# El .gitignore actualizado debe estar en el mismo directorio que este script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/.gitignore" ]]; then
  cp "$SCRIPT_DIR/.gitignore" ./.gitignore
  echo -e "  ${DIM}→ .gitignore actualizado${RST}"
fi

echo ""
echo -e "${GRN}[*] Paso 5: Añadiendo archivos seguros al commit...${RST}"

git add .gitignore
for dir in "${DIRS_GITKEEP[@]}"; do
  git add "$dir/.gitkeep" 2>/dev/null || true
done

git commit -m "security: purgar credenciales y datos de sesión del historial

- Eliminar core/data/security/.credentials (hash bcrypt)
- Eliminar logs con IPs reales y UUIDs de sesión
- Eliminar evidencias RF con datos de operación
- Eliminar __pycache__ compilados
- Añadir .gitignore completo con cobertura correcta de rutas
- Añadir .gitkeep en directorios de datos (estructura sin contenido)" \
  2>/dev/null || echo -e "  ${DIM}  (sin cambios pendientes)${RST}"

echo ""
echo -e "${YEL}╔═══════════════════════════════════════════════════╗${RST}"
echo -e "${YEL}║  PASOS MANUALES REQUERIDOS DESPUÉS               ║${RST}"
echo -e "${YEL}╚═══════════════════════════════════════════════════╝${RST}"
echo ""
echo -e "  ${GRN}1.${RST} Push forzado al remote:"
echo -e "     ${DIM}git push origin --force --all${RST}"
echo -e "     ${DIM}git push origin --force --tags${RST}"
echo ""
echo -e "  ${GRN}2.${RST} Si el repo es público en GitHub:"
echo -e "     ${DIM}→ GitHub puede cachear el contenido eliminado${RST}"
echo -e "     ${DIM}→ Contactar: https://support.github.com${RST}"
echo -e "     ${DIM}→ Solicitar: 'cached views removal after force push'${RST}"
echo ""
echo -e "  ${GRN}3.${RST} Invalidar la contraseña comprometida:"
echo -e "     ${DIM}→ El hash \$2b\$12\$3K3... estaba en .credentials${RST}"
echo -e "     ${DIM}→ Aunque es bcrypt, cambiar la contraseña maestra${RST}"
echo -e "     ${DIM}→ del Sentinel como medida de precaución${RST}"
echo ""
echo -e "  ${GRN}4.${RST} Todos los colaboradores deben re-clonar:"
echo -e "     ${DIM}git clone <repo-url>${RST}"
echo ""
echo -e "${GRN}[✔] Purga completada.${RST}"
